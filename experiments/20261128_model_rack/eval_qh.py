#!/usr/bin/env python3
"""P1(KF + H)の qH0 を変えたときの予測の誤差(README の「追加」)。"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(Path(__file__).parent))
from eval_rack import arrays, other_mean, H, PAR, EVAL, M90, M30  # noqa: E402
from etc.kalman import NoiseParams, run_kf  # noqa: E402
from etc.model import ThermalParams  # noqa: E402

res = []
for q in (0.008, 0.08, 0.8, 8.0):
    e90, e30, sig = [], [], []
    for exp in EVAL:
        th, u, f, ok = arrays(exp)
        n = th.shape[1]
        for i, h in enumerate(H):
            if h == "raspi5":
                continue
            w = PAR[h]["withH"]
            p = ThermalParams(**{k: w[k] for k in ("a", "b", "d", "c", "rho", "z_base", "e", "dt")})
            if p.c <= 0:
                continue
            nz = NoiseParams(R=PAR[h]["R"], qT=PAR[h]["qT_H"], qH0=q, beta=PAR[h].get("beta", 2.0))
            nbr = other_mean(th, i, "nbr")
            r90 = run_kf(p, nz, th[i], u[i], nbr, M90, f=f[i]); r30 = run_kf(p, nz, th[i], u[i], nbr, M30, f=f[i])
            for k in range(n - M90):
                win = slice(k + 1, k + M90 + 1)
                if not (ok[i, k:k + M90 + 1].all() and f[i, k:k + M90 + 1].max() < 0.01 and u[i, win].max() - u[i, k] < 0.2):
                    continue
                e90.append(th[i, k + M90] - r90["pred"][k]); e30.append(th[i, k + M30] - r30["pred"][k]); sig.append(r30["sigma"][k])
    res.append(dict(qH0=q, n=len(e90), mae90=np.mean(np.abs(e90)), bias90=np.mean(e90), mae30=np.mean(np.abs(e30)), sigma30=np.mean(sig)))
df = pd.DataFrame(res).round(3); print(df.to_string(index=False))
df.to_csv(Path(__file__).parent / "results" / "qh_sweep.csv", index=False)
