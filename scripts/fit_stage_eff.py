#!/usr/bin/env python3
"""段階ごとのファンの相対的な効き(段階 4 = 1)を同定する(2026-11-26)。

データ:stage_ident の実験(2 コア一定、OFF 120 秒 → 段階 s で ON 240 秒)
モデル:θ_{t+1} = a θ_t + Σ_s e_s [段階 = s] + d(負荷は一定なので b は d に吸収される)。dt = 5 秒
強制 ON・スロットリング(クロック 1790 MHz 未満)を含む遷移は除く
出力:相対的な効き eff_s = e_s / e_4(0.05〜1 に収め、段階が上がるほど減らないようにする)。
      8 台の平均を、control_params_box.json の各ノードに "stage_eff" として足したものを書き出す

使い方:python scripts/fit_stage_eff.py experiments/20261126_stage_ident scripts/control_params_box.json scripts/control_params_box_ms.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DT = 5.0


def main(exp: Path, base: Path, out: Path):
    tel = pd.read_csv(exp / "raw" / "telemetry.csv")
    ev = pd.read_csv(exp / "events.csv")
    amb = pd.read_csv(exp / "raw" / "ambient.csv")
    amb = amb[amb.name.astype(str).str.contains("ハブ２")].sort_values("ts")
    ps = ev[ev.event == "phase_start"][["ts", "phase"]].reset_index(drop=True)
    ps["end"] = list(ps.ts[1:]) + [ev.ts.max()]
    idp = ps[ps.phase.str.startswith("id") & (ps.phase != "id_rest")]
    t0, t1 = idp.ts.min(), idp.end.max()
    n = int((t1 - t0) // DT)
    tk = t0 + np.arange(n) * DT + DT / 2
    Ta = np.interp(tk, amb.ts.to_numpy(), amb.temperature.to_numpy())
    effs = {}
    for h, g in tel[(tel.ts >= t0) & (tel.ts < t1)].groupby("host"):
        k = ((g.ts - t0) // DT).astype(int)
        a = g.groupby(k).agg(T=("temp", "mean"), st=("fan_stage", "max"), f=("fan", "mean"),
                             fs=("failsafe", "max"), clk=("clock", "min")).reindex(range(n)).ffill().bfill()
        th = a["T"].to_numpy() - Ta
        st = np.where(a.f.to_numpy() > 0.5, a.st.fillna(0).to_numpy(), 0).astype(int)
        ok = (a.fs.to_numpy() == 0) & (a.clk.to_numpy() >= 1790e6)
        m = ok[:-1] & ok[1:]
        X = np.column_stack([th[:-1]] + [(st[:-1] == s).astype(float) for s in (1, 2, 3, 4)] + [np.ones(n - 1)])
        y = th[1:]
        coef, *_ = np.linalg.lstsq(X[m], y[m], rcond=None)
        e = coef[1:5]
        if e[3] >= 0:
            print(f"{h}: e_4 が負でない({e[3]:.3f})→ 使わない")
            continue
        eff = np.clip(e / e[3], 0.05, 1.0)
        eff = np.maximum.accumulate(eff)
        effs[h] = eff
        print(f"{h}: a={coef[0]:.3f} e1..4={np.round(e, 3)} → eff={np.round(eff, 2)}  使った遷移 {int(m.sum())}")
    mean = np.mean(list(effs.values()), axis=0)
    mean = np.maximum.accumulate(np.clip(mean, 0.05, 1.0))
    print("8 台の平均 eff(段階 1〜4):", np.round(mean, 3))
    P = json.loads(base.read_text())
    P["stage_eff_source"] = str(exp)
    P["stage_eff_per_node"] = {h: [0.0] + [float(x) for x in v] for h, v in effs.items()}
    for h in P["nodes"]:
        P["nodes"][h]["stage_eff"] = [0.0] + [float(x) for x in mean]
    out.write_text(json.dumps(P, indent=2, ensure_ascii=False, default=float))
    print("保存:", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
