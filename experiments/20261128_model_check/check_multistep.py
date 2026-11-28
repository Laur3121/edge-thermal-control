#!/usr/bin/env python3
"""S1 の係数を 90 秒先までの再現誤差が最小になるように決める(S1-M)。README の「追加」。"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy.optimize import least_squares
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(ROOT / "experiments/20261128_model_rack"))
from check_models import arrays, H, IDENT, EVAL2, fit, sim_err, M90  # noqa: E402


def starts(ok, lo, hi):
    return np.array([k for k in range(max(lo, 1), hi - M90) if ok[k - 1:k + M90 + 1].all()])


def traj_resid(c, th, u, f, ks):
    a, b, e, d = c
    x = th[ks].copy(); r = []
    for j in range(M90):
        x = a * x + b * u[ks + j] + e * f[ks + j] + d
        r.append(th[ks + j + 1] - x)
    return np.concatenate(r)


thI, uI, fI, okI = arrays(IDENT); n = thI.shape[1]; cut = int(n * 0.6)
ev2 = [arrays(e) for e in EVAL2]
rows = []
for i, h in enumerate(H):
    if h == "raspi5":
        continue
    c1 = fit("S1", thI[i], uI[i], fI[i], okI[i], 0, cut)
    ks = starts(okI[i], 0, cut)
    res = least_squares(traj_resid, c1, args=(thI[i], uI[i], fI[i], ks))
    cM = res.x
    for name, c in (("S1", c1), ("S1-M", cM)):
        a1, _ = sim_err("S1", c, thI[i], uI[i], fI[i], okI[i], cut, n)
        b = np.concatenate([sim_err("S1", c, th[i], u[i], f[i], ok[i], 0, th.shape[1])[0] for th, u, f, ok in ev2])
        rows.append(dict(host=h, model=name, a=c[0], b=c[1], e=c[2], d=c[3], tau_s=-5 / np.log(c[0]) if 0 < c[0] < 1 else np.nan,
                         mae90_same=np.abs(a1).mean(), mae90_other=np.abs(b).mean(), bias90_other=b.mean()))
df = pd.DataFrame(rows)
out = Path(__file__).parent / "results"; df.to_csv(out / "multistep.csv", index=False)
print(df.round(3).to_string(index=False))
g = df.groupby("model")[["mae90_same", "mae90_other", "bias90_other", "tau_s"]].mean().round(2); print(g.to_string())
r1 = g.loc["S1-M", "mae90_same"] / g.loc["S1", "mae90_same"]; r2 = g.loc["S1-M", "mae90_other"] / g.loc["S1", "mae90_other"]
print(f"S1-M:同じ日 {r1:.2f}、別の日 {r2:.2f} →",
      "係数の決め方で良くなる" if r1 <= 0.8 and r2 <= 0.8 else "はっきりしない" if (r1 <= 0.8 or r2 <= 0.8) else "変わらない")
