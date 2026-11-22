#!/usr/bin/env python3
"""温度の履歴だけから予測する AR モデルとの比較(オフライン)。条件は experiments/20261122_ar_baseline/README.md。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from eval_validate import resample  # noqa: E402
from etc.baselines import predict_arx  # noqa: E402
from etc.kalman import NoiseParams, run_kf  # noqa: E402
from etc.metrics import prediction_metrics  # noqa: E402
from etc.model import ThermalParams  # noqa: E402

RUN = ROOT / "experiments" / "20261114_validate_random"
OUT = ROOT / "experiments" / "20261122_ar_baseline"


def fit_ar_diff(theta, n_fit, pmax=12):
    """差分の AR(p)。前半で AIC 最小の p を選ぶ。"""
    d = np.diff(theta[:n_fit])
    best = None
    for p in range(1, pmax + 1):
        X = np.column_stack([d[p - 1 - i:len(d) - 1 - i] for i in range(p)])
        y = d[p:]
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        res = y - X @ coef
        aic = len(y) * np.log(np.mean(res ** 2)) + 2 * p
        if best is None or aic < best[0]:
            best = (aic, p, coef)
    return best[1], best[2]


def predict_ar_diff(theta, p, coef, m):
    n = len(theta)
    d = np.r_[np.nan, np.diff(theta)]
    pred = np.full(n, np.nan)
    for k in range(p, n):
        hist = list(d[k - p + 1:k + 1][::-1])  # 新しい順
        x = theta[k]
        for _ in range(m):
            dn = float(np.dot(coef, hist[:p]))
            x += dn
            hist.insert(0, dn)
        pred[k] = x
    return pred


def main():
    tel = pd.read_csv(RUN / "raw" / "telemetry.csv", usecols=["ts", "host", "temp", "cpu", "fan", "clock"])
    ev = pd.read_csv(RUN / "events.csv")
    amb = pd.read_csv(RUN / "raw" / "ambient.csv")
    amb = amb[amb.name.str.contains("ハブ")].sort_values("ts")
    prm = json.loads((RUN / "results" / "eval" / "params.json").read_text())
    dt, m, n, n_id = prm["dt"], prm["m"], prm["n"], prm["n_identify"]
    ps = ev[ev.event == "phase_start"]
    t0 = float(ps.ts.iloc[0])
    tk = t0 + np.arange(n) * dt
    kb = ((ps.ts.to_numpy()[1:] - t0) // dt).astype(int)
    steady = np.ones(n, bool)
    for b in kb:
        steady[max(0, b - m - 1):b + 1] = False
    Tamb = np.interp(tk + dt / 2, amb.ts.to_numpy(), amb.temperature.to_numpy())
    idx_ev = np.arange(n_id, n)
    subsets = {"all": idx_ev, "steady": idx_ev[steady[idx_ev]], "switch": idx_ev[~steady[idx_ev]]}
    rows, info = [], {}
    for role in ("A", "B", "C"):
        node = prm["nodes"][f"{role} (11/14 first half)"]
        D = resample(tel, node["host"], dt, t0, n).ffill().bfill()
        th = D["T"].to_numpy() - Tamb
        u, f = D.u.to_numpy(), D.f.to_numpy()
        sp, nz = node["self"], node["noise_self"]
        p = ThermalParams(a=sp["a"], b=sp["b"], d=sp["d"], e=sp["e"], c=0.0, dt=dt)
        order, coef = fit_ar_diff(th, n_id)
        preds = {"AR(温度の履歴のみ)": predict_ar_diff(th, order, coef, m),
                 "Self-only(負荷・ファンを入力)": predict_arx(p, th, u, m, f=f),
                 "KF(H なし)": run_kf(p, NoiseParams(R=nz["R"], qT=nz["qT"], qH0=0.0, beta=0.0),
                                     th, u, np.zeros(n), m, f=f)["pred"]}
        info[role] = {"ar_order": int(order), "ar_coef": [float(c) for c in coef]}
        for name, pr in preds.items():
            for sub, idx in subsets.items():
                r = prediction_metrics(th, pr, m, idx)
                rows.append({"node": role, "method": name, "subset": sub, "n": r["n"],
                             "MAE": r["mae"] if "mae" in r else r.get("MAE"),
                             "RMSE": r["rmse"] if "rmse" in r else r.get("RMSE")})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "prediction_metrics.csv", index=False, float_format="%.4f")
    (OUT / "info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))
    print(json.dumps(info, ensure_ascii=False))
    with pd.option_context("display.width", 200):
        print(df.pivot_table(index=["node", "method"], columns="subset", values=["MAE", "RMSE"]).round(2))


if __name__ == "__main__":
    main()
