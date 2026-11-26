#!/usr/bin/env python3
"""8 台・囲いありの閉ループ制御に使うパラメータを同定する(2026-11-25 夜)。

- データ:20261125_pattern_box_front_open(囲いあり、同じ配置)の全区間。今夜の制御実験とは別の実験なので、同定と評価は分かれる
- θ = T − 室温(ハブ 2)、dt = 5 秒
- self(self_fixed 方式):θ_{t+1} = a θ + b u + e f + d
- withH(提案方式):θ_{t+1} = a θ + b u + c H + e f + d、H_{t+1} = ρ H + (1−ρ)(z − z_base)。z = 縦・横・斜めで接するノードの温度 − 室温 の平均。
  c < 0 は物理的にありえないので、その場合は c = 0(H なし)
- スロットリング中(クロックが 1790 MHz 未満)を含む遷移は除く
- ファンの係数 e:ファンを回した区間がスロットリングなしで十分(30 ステップ以上)あるノードだけ同定する。
  ほかのノードは、同定できたノードの定常の効き e/(1−a) の平均を使う(同じ PoE+ HAT のファン)
- qT:1 ステップ残差の分散 − (1 + a²) R。固定マージン:Self-only の Δ 秒先予測の誤差の 97.7% 分位点

出力:scripts/control_params_box.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from etc.baselines import fixed_margin_from, predict_arx, realized_errors  # noqa: E402
from etc.model import ThermalParams, fit_self_only, fit_with_H  # noqa: E402

EXP = Path("experiments/20261125_pattern_box_front_open")
OUT = Path("scripts/control_params_box.json")
DT, DELTA, FIXED_Q = 5.0, 30.0, 0.977
M = int(DELTA / DT)
GRID = {f"raspi{i}": ((i - 1) // 4, (i - 1) % 4) for i in range(1, 9)}
NBR = {h: [s for s, q in GRID.items() if s != h and max(abs(p[0] - q[0]), abs(p[1] - q[1])) == 1]
       for h, p in GRID.items()}
R = json.loads(Path("experiments/20261113_step_identify/results/identify.json").read_text())["noise"]["R_1s"] / DT


def load(exp):
    """1 つの実験を 5 秒ごとに。戻り値:{host: DataFrame(T, u, f, clk)}, 室温"""
    tel = pd.read_csv(exp / "raw" / "telemetry.csv")
    ev = pd.read_csv(exp / "events.csv")
    amb = pd.read_csv(exp / "raw" / "ambient.csv")
    amb = amb[amb.name.astype(str).str.contains("ハブ２")].sort_values("ts")
    t0 = float(ev[ev.event == "phase_start"].ts.iloc[0])
    n = int((float(ev[ev.event == "phase_end"].ts.max()) - t0) // DT)
    tk = t0 + np.arange(n) * DT + DT / 2
    Tamb = np.interp(tk, amb.ts.to_numpy(), amb.temperature.to_numpy())
    D = {}
    for h in GRID:
        g = tel[tel.host == h]
        k = ((g.ts - t0) // DT).astype(int)
        D[h] = g.groupby(k).agg(T=("temp", "mean"), u=("cpu", "mean"), f=("fan", "mean"),
                                clk=("clock", "min")).reindex(range(n)).ffill().bfill()
    return D, Tamb


def main():
    global EXP, OUT
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", nargs="+", default=[str(EXP)], help="同定に使う実験(複数可。つなげて使い、つなぎ目の遷移は除く)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--head-frac", type=float, default=1.0,
                    help="最後の実験は前からこの割合だけを使う(残りを確認に回すため。11/26 追加)")
    a = ap.parse_args()
    EXP, OUT = [Path(e) for e in a.exp], Path(a.out)
    parts = [load(e) for e in EXP]
    if a.head_frac < 1.0:  # 最後の実験の後半は同定に使わない(check_params_holdout.py の確認用に残す)
        D_last, T_last = parts[-1]
        m = int(len(T_last) * a.head_frac)
        parts[-1] = ({h: d.iloc[:m].reset_index(drop=True) for h, d in D_last.items()}, T_last[:m])
    Tamb = np.concatenate([p[1] for p in parts])
    D = {h: pd.concat([p[0][h] for p in parts], ignore_index=True) for h in GRID}
    seam = np.zeros(len(Tamb), bool)  # つなぎ目(各実験の最後の点)からの遷移は使わない
    pos = 0
    for p in parts:
        pos += len(p[1])
        seam[pos - 1] = True
    n = len(Tamb)

    fits = {}
    for h in GRID:
        th = D[h]["T"].to_numpy() - Tamb
        u, f = D[h].u.to_numpy() / 100, D[h].f.to_numpy()
        ok = D[h].clk.to_numpy() >= 1790e6
        mask = ok[:-1] & ok[1:] & ~seam[:-1]
        nbr = np.mean([D[s]["T"].to_numpy() - Tamb for s in NBR[h]], axis=0)
        has_fan = int(((f[:-1] > 0.5) & mask).sum()) >= 30
        ps, rs = fit_self_only(th, u, DT, mask=mask, f=f if has_fan else None)
        z_base = float(nbr[mask[:-1].nonzero()[0]].mean()) if mask.any() else float(nbr.mean())
        ph, rh = fit_with_H(th, u, nbr, DT, z_base=z_base, mask=mask, f=f if has_fan else None)
        fits[h] = dict(th=th, u=u, f=f, nbr=nbr, mask=mask, has_fan=has_fan, ps=ps, rs=rs, ph=ph, rh=rh)
        print(f"{h}: fan_steps={int(((f[:-1] > 0.5) & mask).sum())} self a={ps.a:.3f} b={ps.b:.2f} e={ps.e:.2f} "
              f"| H a={ph.a:.3f} c={ph.c:.3f} rho={ph.rho:.3f} e={ph.e:.2f}")
    gains = [x["ps"].e / (1 - x["ps"].a) for x in fits.values() if x["has_fan"]]
    gain = float(np.mean(gains))
    print("ファンの定常の効き e/(1−a):", np.round(gains, 1), "→ 平均", round(gain, 1))

    out = {"source": [str(e) for e in EXP], "dt": DT, "delta": DELTA, "R": R, "fixed_q": FIXED_Q, "fan_gain_mean": gain,
           "note": "温度は室温(ハブ 2)からの上昇分。囲いあり。fit_control_params_box.py", "nodes": {}}
    for h, x in fits.items():
        ps, ph = x["ps"], x["ph"]
        if not x["has_fan"]:
            ps.e = gain * (1 - ps.a)
            ph.e = gain * (1 - ph.a)
        if ph.c < 0:
            ph = ThermalParams(a=ps.a, b=ps.b, d=ps.d, e=ps.e, c=0.0, rho=ph.rho, z_base=ph.z_base, dt=DT)
            rh = x["rs"]
        else:
            rh = x["rh"]
        qT = max(float(np.var(x["rs"])) - (1 + ps.a ** 2) * R, 1e-4)
        qT_H = max(float(np.var(rh)) - (1 + ph.a ** 2) * R, 1e-4)
        pred = predict_arx(ps, x["th"], x["u"], M, f=x["f"])
        err = realized_errors(x["th"], pred, M)
        fm = fixed_margin_from(err[:n - M], FIXED_Q)
        out["nodes"][h] = {"self": ps.to_dict(), "withH": ph.to_dict(), "neighbors": NBR[h], "R": R,
                           "qT": qT, "qT_H": qT_H, "qH0": 0.008, "beta": 2.0, "fixed_margin": fm,
                           "e_identified": x["has_fan"], "issues": ps.check() + ph.check()}
        print(f"{h}: e={ps.e:.2f}{'' if x['has_fan'] else '(平均から)'} c={ph.c:.3f} qT={qT:.3f} qT_H={qT_H:.3f} "
              f"fixed_margin={fm:.2f} issues={ps.check() + ph.check()}")
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()
