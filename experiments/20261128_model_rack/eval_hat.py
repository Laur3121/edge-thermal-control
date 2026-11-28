#!/usr/bin/env python3
"""open_ident(HAT を付けた後)だけで自ノードのモデルを同定し直し、11/28 のデータで台ごとの誤差を比べる(README の追加 2)。"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from eval_rack import arrays, H, PAR, EVAL, M90  # noqa: E402

th, u, f, ok = arrays(ROOT / "experiments/20261126_open_ident")
co = {}
for i, h in enumerate(H):
    mk = ok[i, :-1] & ok[i, 1:]
    X = np.c_[th[i, :-1], u[i, :-1], f[i, :-1], np.ones(th.shape[1] - 1)][mk]
    co[h], *_ = np.linalg.lstsq(X, th[i, 1:][mk], rcond=None)
rows = []
for exp in EVAL:
    th, u, f, ok = arrays(exp)
    for i, h in enumerate(H):
        if h == "raspi5":
            continue
        s = PAR[h]["self"]; a2, b2, e2, d2 = co[h]
        for k in range(th.shape[1] - M90):
            win = slice(k + 1, k + M90 + 1)
            if not (ok[i, k:k + M90 + 1].all() and f[i, k:k + M90 + 1].max() < 0.01 and u[i, win].max() - u[i, k] < 0.2):
                continue
            x0 = x1 = th[i, k]
            for _ in range(M90):
                x0 = s["a"] * x0 + s["b"] * u[i, k] + s["d"]
                x1 = a2 * x1 + b2 * u[i, k] + d2
            rows.append(dict(host=h, P0=th[i, k + M90] - x0, P0new=th[i, k + M90] - x1))
df = pd.DataFrame(rows)
print({h: np.round(c, 3).tolist() for h, c in co.items()})
print("台ごとの 90 秒先の平均誤差 [℃]"); print(df.groupby("host").mean().round(2).to_string())
print("全体 MAE", df[["P0", "P0new"]].abs().mean().round(2).to_dict())
df.groupby("host").mean().to_csv(Path(__file__).parent / "results" / "hat_refit.csv")
