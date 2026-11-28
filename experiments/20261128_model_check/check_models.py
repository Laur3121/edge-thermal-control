#!/usr/bin/env python3
"""熱モデルの形(S1〜S5)と同定の長さを比べる(README の方法)。実際の負荷とファンを与えた 90 秒先・30 秒先の再現誤差。"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/20261128_model_rack"))
from eval_rack import arrays, H  # noqa: E402

DT = 5.0; M90, M30 = 18, 6
IDENT = ROOT / "experiments/20261126_open_ident"
EVAL2 = [ROOT / "experiments/20261127_delay_sweep/d60", ROOT / "experiments/20261127_delay_sweep/d30",
         ROOT / "experiments/20261127_tradeoff/d60"]
FORMS = ["S1", "S2", "S3", "S4", "S5"]


def feats(form, th, thp, u, f):
    """1 ステップの説明変数。th = θ_t、thp = θ_{t−1}"""
    cols = [th, u, f, np.ones_like(th)]
    if form in ("S2", "S5"): cols.append(thp)
    if form in ("S3", "S5"): cols.append(f * th)
    if form in ("S4", "S5"): cols.append(u * u)
    return np.c_[tuple(cols)] if np.ndim(th) else np.array(cols, float)


def fit(form, th, u, f, ok, lo, hi):
    t = np.arange(max(lo, 1), hi - 1)
    t = t[ok[t - 1] & ok[t] & ok[t + 1]]
    X = feats(form, th[t], th[t - 1], u[t], f[t])
    c, *_ = np.linalg.lstsq(X, th[t + 1], rcond=None)
    return c


def sim_err(form, c, th, u, f, ok, lo, hi):
    e90, e30 = [], []
    for k in range(max(lo, 1), hi - M90):
        if not ok[k - 1:k + M90 + 1].all():
            continue
        x, xp = th[k], th[k - 1]
        for j in range(M90):
            nx = float(feats(form, x, xp, u[k + j], f[k + j]) @ c)
            xp, x = x, nx
            if j == M30 - 1: e30.append(th[k + M30] - x)
        e90.append(th[k + M90] - x)
    return np.array(e90), np.array(e30)


def main():
    thI, uI, fI, okI = arrays(IDENT); n = thI.shape[1]; cut = int(n * 0.6)
    ev2 = [arrays(e) for e in EVAL2]
    rows = []
    for i, h in enumerate(H):
        if h == "raspi5":
            continue
        for form in FORMS:
            c = fit(form, thI[i], uI[i], fI[i], okI[i], 0, cut)
            a1, _ = sim_err(form, c, thI[i], uI[i], fI[i], okI[i], cut, n)
            b90, b30 = [], []
            for th, u, f, ok in ev2:
                x90, x30 = sim_err(form, c, th[i], u[i], f[i], ok[i], 0, th.shape[1]); b90.append(x90); b30.append(x30)
            b90 = np.concatenate(b90)
            rows.append(dict(host=h, form=form, mae90_same=np.abs(a1).mean(), mae90_other=np.abs(b90).mean(),
                             bias90_other=b90.mean(), mae30_other=np.abs(np.concatenate(b30)).mean()))
    df = pd.DataFrame(rows)
    out = Path(__file__).parent / "results"; out.mkdir(exist_ok=True); df.to_csv(out / "forms.csv", index=False)
    g = df.groupby("form")[["mae90_same", "mae90_other", "bias90_other", "mae30_other"]].mean().round(2)
    print("モデルの形(7 台の平均)"); print(g.to_string())
    for form in FORMS[1:]:
        r1 = g.loc[form, "mae90_same"] / g.loc["S1", "mae90_same"]; r2 = g.loc[form, "mae90_other"] / g.loc["S1", "mae90_other"]
        v = "今の形より良い" if r1 <= 0.8 and r2 <= 0.8 else "はっきりしない" if (r1 <= 0.8 or r2 <= 0.8) else "今の形で足りている"
        print(f"{form}:同じ日 {r1:.2f}、別の日 {r2:.2f} → {v}")
    print(df.pivot(index="host", columns="form", values="mae90_other").round(2).to_string())
    # 同定の長さ
    best = g["mae90_same"].idxmin()
    rows = []
    for form in sorted({"S1", best}):
        for mins in (10, 20, 30, 42):
            hi = min(int(mins * 60 / DT), cut)
            m = []
            for i, h in enumerate(H):
                if h == "raspi5":
                    continue
                c = fit(form, thI[i], uI[i], fI[i], okI[i], 0, hi)
                m.append(np.abs(sim_err(form, c, thI[i], uI[i], fI[i], okI[i], cut, n)[0]).mean())
            rows.append(dict(form=form, minutes=mins, mae90_same=np.mean(m)))
    L = pd.DataFrame(rows).round(2); L.to_csv(out / "length.csv", index=False)
    print("同定の長さ(評価 1、7 台の平均)"); print(L.to_string(index=False))


if __name__ == "__main__":
    main()
