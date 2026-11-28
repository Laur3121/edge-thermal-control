#!/usr/bin/env python3
"""S6 高次 ARX(README の追加 2)。"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "20261128_model_rack"))
from check_models import arrays, H, IDENT, EVAL2, fit, sim_err, M90  # noqa: E402
NA, NB = 4, 12
L = max(NA, NB)


def X_at(th, u, f, t):
    return np.r_[th[t - np.arange(NA)], u[t - np.arange(NB)], f[t - np.arange(NB)], 1.0]


def fit6(th, u, f, ok, lo, hi):
    ts = [t for t in range(max(lo, L), hi - 1) if ok[t - L:t + 2].all()]
    X = np.array([X_at(th, u, f, t) for t in ts]); c, *_ = np.linalg.lstsq(X, th[np.array(ts) + 1], rcond=None)
    return c


def err6(c, th, u, f, ok, lo, hi):
    e = []
    for k in range(max(lo, L), hi - M90):
        if not ok[k - L:k + M90 + 1].all():
            continue
        x = th.copy()  # 予測した値で上書きしていく(入力は実際の値)
        for j in range(M90):
            x[k + j + 1] = X_at(x, u, f, k + j) @ c
        e.append(th[k + M90] - x[k + M90])
    return np.array(e)


thI, uI, fI, okI = arrays(IDENT); n = thI.shape[1]; cut = int(n * 0.6)
ev2 = [arrays(e) for e in EVAL2]
rows = []
for i, h in enumerate(H):
    if h == "raspi5":
        continue
    c1 = fit("S1", thI[i], uI[i], fI[i], okI[i], 0, cut); c6 = fit6(thI[i], uI[i], fI[i], okI[i], 0, cut)
    a1 = np.abs(sim_err("S1", c1, thI[i], uI[i], fI[i], okI[i], cut, n)[0]).mean()
    b1 = np.abs(np.concatenate([sim_err("S1", c1, th[i], u[i], f[i], ok[i], 0, th.shape[1])[0] for th, u, f, ok in ev2])).mean()
    a6 = np.abs(err6(c6, thI[i], uI[i], fI[i], okI[i], cut, n)).mean()
    b6 = np.abs(np.concatenate([err6(c6, th[i], u[i], f[i], ok[i], 0, th.shape[1]) for th, u, f, ok in ev2])).mean()
    rows.append(dict(host=h, S1_same=a1, S6_same=a6, S1_other=b1, S6_other=b6))
df = pd.DataFrame(rows).round(2); print(df.to_string(index=False))
m = df.mean(numeric_only=True).round(2); print(m.to_string())
r1, r2 = m.S6_same / m.S1_same, m.S6_other / m.S1_other
print(f"S6:同じ日 {r1:.2f}、別の日 {r2:.2f} →", "形で取れる分がある" if r1 <= 0.8 and r2 <= 0.8 else
      "はっきりしない" if (r1 <= 0.8 or r2 <= 0.8) else "形では取れない")
df.to_csv(Path(__file__).parent / "results" / "arx_high.csv", index=False)
