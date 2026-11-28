#!/usr/bin/env python3
"""S6 のどの部分が効いているか(事後の分析、判定には使わない):温度・負荷・ファンの過去の長さを 1 つずつ戻す。"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "20261128_model_rack"))
from check_models import arrays, H, IDENT, EVAL2, M90  # noqa: E402
L = 12
VARIANTS = {"S1 相当(1,1,1)": (1, 1, 1), "温度だけ過去 4": (4, 1, 1), "負荷だけ過去 12": (1, 12, 1),
            "ファンだけ過去 12": (1, 1, 12), "負荷とファン過去 12": (1, 12, 12), "S6(4,12,12)": (4, 12, 12)}


def X_at(th, u, f, t, na, nu, nf):
    return np.r_[th[t - np.arange(na)], u[t - np.arange(nu)], f[t - np.arange(nf)], 1.0]


def fitv(th, u, f, ok, lo, hi, o):
    ts = [t for t in range(max(lo, L), hi - 1) if ok[t - L:t + 2].all()]
    X = np.array([X_at(th, u, f, t, *o) for t in ts]); return np.linalg.lstsq(X, th[np.array(ts) + 1], rcond=None)[0]


def errv(c, th, u, f, ok, lo, hi, o):
    e = []
    for k in range(max(lo, L), hi - M90):
        if not ok[k - L:k + M90 + 1].all():
            continue
        x = th.copy()
        for j in range(M90):
            x[k + j + 1] = X_at(x, u, f, k + j, *o) @ c
        e.append(th[k + M90] - x[k + M90])
    return np.abs(np.array(e)).mean()


thI, uI, fI, okI = arrays(IDENT); n = thI.shape[1]; cut = int(n * 0.6)
ev2 = [arrays(e) for e in EVAL2]
rows = []
for name, o in VARIANTS.items():
    s, t = [], []
    for i, h in enumerate(H):
        if h == "raspi5":
            continue
        c = fitv(thI[i], uI[i], fI[i], okI[i], 0, cut, o)
        s.append(errv(c, thI[i], uI[i], fI[i], okI[i], cut, n, o))
        t.append(np.mean([errv(c, th[i], u[i], f[i], ok[i], 0, th.shape[1], o) for th, u, f, ok in ev2]))
    rows.append(dict(variant=name, same=np.mean(s), other=np.mean(t)))
df = pd.DataFrame(rows).round(2); print(df.to_string(index=False))
df.to_csv(Path(__file__).parent / "results" / "arx_parts.csv", index=False)
# ファンのインパルス応答の形(S6 の係数から、ファン ON のステップ応答を作る)
