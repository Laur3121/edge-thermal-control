#!/usr/bin/env python3
"""pattern 実験で、温度の履歴だけの AR モデルの 30 秒先の予測を、Q2(eval_pattern_pred.py --swap)と同じ評価時刻で求める。

条件は experiments/20261125_pattern_box_front_open/README.md「温度の履歴だけの予測(AR)との比較」(11/26 13:55、実行前)。
使い方:python scripts/eval_pattern_ar.py experiments/20261125_pattern_open experiments/20261125_pattern_box_front_open
出力:<exp>/results/pred_swap/ar_metrics.csv と、提案などとの比較の表(標準出力)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_pattern_pred as E  # noqa: E402

DT, M = E.DT, E.M


def fit_ar(dT, mask, pmax=12):
    """差分 dT[t] = Σ φ_i dT[t-i]。mask[t] が True(t と t-p..t-1 がすべて同定区間)の行で最小二乗、AIC で p を選ぶ"""
    best = None
    for p in range(1, pmax + 1):
        rows = [t for t in range(pmax, len(dT)) if mask[t - pmax:t + 1].all()]
        X = np.array([[dT[t - i] for i in range(1, p + 1)] for t in rows])
        y = dT[rows]
        phi, *_ = np.linalg.lstsq(X, y, rcond=None)
        rss = float(((y - X @ phi) ** 2).sum())
        aic = len(y) * np.log(rss / len(y)) + 2 * p
        if best is None or aic < best[0]:
            best = (aic, p, phi)
    return best[1], best[2]


def predict(T, phi, k):
    p = len(phi)
    d = list(np.diff(T[k - p:k + 1]))  # 直近 p 個の差分(古い順)
    x = T[k]
    for _ in range(M):
        nd = float(np.dot(phi, d[::-1][:p]))
        d.append(nd)
        x += nd
    return x


def main(exp: Path):
    E.ID_BLOCKS, E.EV_BLOCKS = list(E.EV_BLOCKS), list(E.ID_BLOCKS)  # --swap と同じ
    tel = pd.read_csv(exp / "raw" / "telemetry.csv")
    ev = pd.read_csv(exp / "events.csv")
    ps = ev[ev.event == "phase_start"].reset_index(drop=True)
    pe = ev[ev.event == "phase_end"].set_index("phase").ts
    t0, t_end = float(ps.ts.iloc[0]), float(pe.max())
    n = int((t_end - t0) // DT)

    def block_mask(names):
        mk = np.zeros(n, bool)
        for p in names:
            s, e = float(ps[ps.phase == p].ts.iloc[0]), float(pe[p])
            mk[int((s - t0) // DT):int((e - t0) // DT)] = True
        return mk

    D = {}
    for r in E.GRID:
        g = tel[tel.host == f"raspi{r[1:]}"]
        k = ((g.ts - t0) // DT).astype(int)
        D[r] = g.groupby(k).agg(T=("temp", "mean"), u=("cpu", "mean"), f=("fan", "max")).reindex(range(n)).ffill().bfill()
    id_mask, ev_mask = block_mask(E.ID_BLOCKS), block_mask(E.EV_BLOCKS)
    load_mask = block_mask([b for b in E.EV_BLOCKS if b.endswith("_load")])
    rows = []
    for r in E.GRID:
        T, u, f = D[r]["T"].to_numpy(), D[r].u.to_numpy() / 100.0, D[r].f.to_numpy()
        fan_free = np.array([f[k:k + M + 1].max() == 0 for k in range(n)])
        dT = np.r_[0.0, np.diff(T)]
        okid = id_mask & (f == 0) & np.r_[False, f[:-1] == 0]
        p, phi = fit_ar(dT, okid)
        idx_ev = np.where(ev_mask & fan_free)[0]
        idx_ev = idx_ev[(idx_ev >= 13) & (idx_ev < n - M)]
        pred = np.full(n, np.nan)
        for k in idx_ev:
            pred[k] = predict(T, phi, k)
        nbr_heat = np.zeros(n, bool)
        for s_ in E.NBR[r]:
            nbr_heat |= D[s_].u.to_numpy() > 30
        err = lambda ix: float(np.nanmean(np.abs(T[ix + M] - pred[ix]))) if len(ix) else float("nan")
        rows.append({"role": r, "model": "AR(温度の履歴だけ)", "p": p, "MAE": round(err(idx_ev), 3),
                     "MAE_load": round(err(idx_ev[load_mask[idx_ev]]), 3),
                     "MAE_nbr_only": round(err(idx_ev[(u[idx_ev] < 0.1) & nbr_heat[idx_ev]]), 3), "n": len(idx_ev)})
    ar = pd.DataFrame(rows)
    out = exp / "results" / "pred_swap"
    ar.to_csv(out / "ar_metrics.csv", index=False)
    m = pd.read_csv(out / "metrics.csv")
    allm = pd.concat([m[["role", "model", "MAE", "MAE_load", "MAE_nbr_only", "n"]], ar.drop(columns="p")])
    top = allm[allm.role.isin(["r1", "r2", "r3"])].groupby("model")[["MAE", "MAE_load", "MAE_nbr_only"]].mean()
    print(f"# {exp.name}:30 秒先の MAE [℃]、上段 r1〜r3 の平均")
    print(top.round(2).to_string())
    print("8 台の平均")
    print(allm.groupby("model")[["MAE"]].mean().round(2).to_string())
    print("AR の次数:", dict(zip(ar.role, ar.p)), " 評価時刻の数(AR / Q2):",
          dict(zip(ar.role, ar.n)), dict(zip(m[m.model.str.startswith("②")].role, m[m.model.str.startswith("②")].n)))
    E.ID_BLOCKS, E.EV_BLOCKS = E.EV_BLOCKS, E.ID_BLOCKS


if __name__ == "__main__":
    for a in sys.argv[1:]:
        main(Path(a))
        print()
