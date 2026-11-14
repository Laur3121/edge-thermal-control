#!/usr/bin/env python3
"""閉ループ制御に使うパラメータを同定する(ノードごと、案B、c = 0)。

- データ:検証用ランダム実験(既定 20261114_validate_random)の全区間。閉ループ実験は別の日なので、ここは同定用として全部使う
- モデル:θ_{t+1} = a θ + b u + e f + d(θ は室温からの上昇分、dt = 5 秒)
- c = 0:ラックでは干渉がほぼなく、同定すると c が負(物理的にありえない)になるノードがあったため。
  c ≥ 0 の制約の下での最良値は 0(20261114_validate_random/README.md「KF の評価」)
- qT:1 ステップ残差の分散 − (1 + a²) R
- 固定マージン(self_fixed 方式用):Self-only の Δ 秒先予測(入力は今の値が続く)の誤差の 97.7% 分位点

出力:JSON(既定 scripts/control_params.json)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from etc.baselines import fixed_margin_from, predict_arx, realized_errors  # noqa: E402
from etc.model import fit_self_only  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="experiments/20261114_validate_random")
    ap.add_argument("--out", default="scripts/control_params.json")
    ap.add_argument("--dt", type=float, default=5.0)
    ap.add_argument("--delta", type=float, default=30.0)
    ap.add_argument("--R", type=float, default=0.068, help="観測ノイズ(11/13 の 1 秒値の分散 / 5)")
    ap.add_argument("--fixed-q", type=float, default=0.977)
    ap.add_argument("--ambient", default="ハブ")
    args = ap.parse_args()

    d = Path(args.run)
    tel = pd.read_csv(d / "raw" / "telemetry.csv")
    ev = pd.read_csv(d / "events.csv")
    amb = pd.read_csv(d / "raw" / "ambient.csv")
    amb = amb[amb.name.str.contains(args.ambient)].sort_values("ts")
    nodes = json.loads((d / "config.json").read_text())["nodes"]
    dt, m = args.dt, int(round(args.delta / args.dt))
    t0 = float(ev[ev.event == "phase_start"].ts.iloc[0])
    n = int((float(ev[ev.event == "end"].ts.iloc[0]) - t0) // dt)
    tk = t0 + np.arange(n) * dt
    Tamb = np.interp(tk + dt / 2, amb.ts.to_numpy(), amb.temperature.to_numpy())

    out = {"source": str(d), "dt": dt, "delta": args.delta, "R": args.R, "fixed_q": args.fixed_q,
           "note": "温度は室温からの上昇分。c = 0(干渉なし)", "nodes": {}}
    for role, host in nodes.items():
        g = tel[tel.host == host]
        k = ((g.ts - t0) // dt).astype(int)
        a = g.groupby(k).agg(T=("temp", "mean"), u=("cpu", "mean"), f=("fan", "mean")).reindex(range(n)).ffill().bfill()
        th, u, f = a["T"].to_numpy() - Tamb, a.u.to_numpy() / 100, a.f.to_numpy()
        p, r = fit_self_only(th, u, dt, f=f)
        qT = max(float(np.var(r)) - (1 + p.a ** 2) * args.R, 1e-4)
        pred = predict_arx(p, th, u, m, f=f)
        e = realized_errors(th, pred, m)
        fm = fixed_margin_from(e[:n - m], args.fixed_q)
        out["nodes"][host] = {"role": role, "self": p.to_dict(), "issues": p.check(), "R": args.R, "qT": qT,
                              "fixed_margin": fm, "mae_30s": float(np.nanmean(np.abs(e)))}
        print(f"{host}: a={p.a:.3f} tau={p.tau:.0f}s b={p.b:.3f} e={p.e:.3f} d={p.d:.3f} qT={qT:.3f} "
              f"fixed_margin={fm:.2f} issues={p.check()}")
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()
