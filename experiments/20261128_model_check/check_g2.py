#!/usr/bin/env python3
"""2 段のモデル G2(README の追加 3)。"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy.optimize import least_squares
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "20261128_model_rack"))
from check_models import arrays, H, IDENT, EVAL2, fit, sim_err, M90  # noqa: E402


def observer(p, th, u, f):
    a11, a12, b1, e1, d1, a21, a22, b2, e2, d2 = p
    x2 = np.empty_like(th); x2[0] = th[0]
    for t in range(len(th) - 1):
        x2[t + 1] = a21 * th[t] + a22 * x2[t] + b2 * u[t] + e2 * f[t] + d2
    return x2


def multistep(p, th, u, f, ks):
    a11, a12, b1, e1, d1, a21, a22, b2, e2, d2 = p
    x2o = observer(p, th, u, f)
    x1, x2 = th[ks].copy(), x2o[ks].copy(); out = []
    for j in range(M90):
        x1, x2 = (a11 * x1 + a12 * x2 + b1 * u[ks + j] + e1 * f[ks + j] + d1,
                  a21 * x1 + a22 * x2 + b2 * u[ks + j] + e2 * f[ks + j] + d2)
        out.append(th[ks + j + 1] - x1)
    return np.array(out)  # (M90, K)


def starts(ok, lo, hi):
    return np.array([k for k in range(max(lo, 1), hi - M90) if ok[k - 1:k + M90 + 1].all()])


thI, uI, fI, okI = arrays(IDENT); n = thI.shape[1]; cut = int(n * 0.6)
ev2 = [arrays(e) for e in EVAL2]
rows, params = [], {}
for i, h in enumerate(H):
    if h == "raspi5":
        continue
    a, b, e, d = fit("S1", thI[i], uI[i], fI[i], okI[i], 0, cut)
    best = None
    for split in (0.3, 0.6):  # 初期値を 2 通り試す(負荷の何割をチップに入れるか)
        p0 = [a - 0.05, 0.05, b * split, e * 0.2, d * 0.5, 0.05, 0.93, b * (1 - split) * 0.3, e * 0.5, d * 0.3]
        ks = starts(okI[i], 0, cut)
        def resid(p):
            # 安定の制約(11/28 追加):状態の行列の固有値の大きさが 0.995 以上なら大きな罰を足す(温度が発散する解を除く)
            rho = np.abs(np.linalg.eigvals(np.array([[p[0], p[1]], [p[5], p[6]]]))).max()
            pen = 1e3 * max(0.0, rho - 0.995)
            r_ = multistep(p, thI[i][:cut + M90], uI[i][:cut + M90], fI[i][:cut + M90], ks).ravel()
            return np.r_[r_, pen] if np.isfinite(r_).all() else np.full(r_.size + 1, 1e3)
        # ヒートシンクの観測器が発散しないよう a22 を 0〜0.995 に制限(11/28 追加。r7 が a22 = 1.027 で発散したため)
        lo = [-np.inf] * 10; hi = [np.inf] * 10; lo[6], hi[6] = 0.0, 0.995
        r = least_squares(resid, p0, bounds=(lo, hi))
        if best is None or r.cost < best.cost:
            best = r
    pG = best.x; params[h] = pG.tolist()
    ksA = starts(okI[i], cut, n)
    g_same = np.abs(multistep(pG, thI[i], uI[i], fI[i], ksA)[-1]).mean()
    g_other = np.mean([np.abs(multistep(pG, th[i], u[i], f[i], starts(ok[i], 0, th.shape[1]))[-1]).mean() for th, u, f, ok in ev2])
    c1 = np.array([a, b, e, d])
    s_same = np.abs(sim_err("S1", c1, thI[i], uI[i], fI[i], okI[i], cut, n)[0]).mean()
    s_other = np.mean([np.abs(sim_err("S1", c1, th[i], u[i], f[i], ok[i], 0, th.shape[1])[0]).mean() for th, u, f, ok in ev2])
    A = np.array([[pG[0], pG[1]], [pG[5], pG[6]]]); ev = np.linalg.eigvals(A)
    taus = sorted(-5 / np.log(np.abs(ev))) if np.all(np.abs(ev) < 1) else [np.nan, np.nan]
    rows.append(dict(host=h, S1_same=s_same, G2_same=g_same, S1_other=s_other, G2_other=g_other, tau_fast=taus[0], tau_slow=taus[1]))
    print(h, np.round(pG, 3).tolist(), "時定数", np.round(taus, 1))
df = pd.DataFrame(rows).round(2); print(df.to_string(index=False))
m = df.mean(numeric_only=True).round(2); print(m.to_string())
r1, r2 = m.G2_same / m.S1_same, m.G2_other / m.S1_other
print(f"G2:同じ日 {r1:.2f}、別の日 {r2:.2f} →", "2 段のモデルで説明できる" if r1 <= 0.8 and r2 <= 0.8 else
      "はっきりしない" if (r1 <= 0.8 or r2 <= 0.8) else "だめ")
out = Path(__file__).parent / "results"; df.to_csv(out / "g2.csv", index=False)
import json; (out / "g2_params.json").write_text(json.dumps(params, indent=1))
