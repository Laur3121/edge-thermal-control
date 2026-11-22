#!/usr/bin/env python3
"""切り替えの確率を含めたマージン(オフライン評価)。条件は experiments/20261122_risk_margin/README.md(実行前に記録)。

データ:experiments/20261114_validate_random。前半で同定・p と切り替え後の分布を求め、後半で評価する。
予測は自ノードのみのカルマンフィルタ(c = 0)。7 章と同じ前半の同定値(results/eval/params.json)を使う。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from eval_validate import margin_rows, resample  # noqa: E402
from etc.baselines import fixed_margin_from, realized_errors  # noqa: E402
from etc.kalman import NoiseParams, run_kf  # noqa: E402
from etc.model import ThermalParams  # noqa: E402

RUN = ROOT / "experiments" / "20261114_validate_random"
OUT = ROOT / "experiments" / "20261122_risk_margin"
ALPHA_Q = 0.5 * (1 + math.erf(2 / math.sqrt(2)))  # 97.7%(α = 2 と同じ)
DELTA = 0.5


def Phi(x):
    return 0.5 * (1 + np.vectorize(math.erf)(np.asarray(x) / math.sqrt(2)))


def mixture_quantile(sigma, p, J, q=ALPHA_Q):
    """(1−p) N(0,σ²) + p · 平均_j N(J_j, σ²) の q 点を二分法で求める。"""
    lo, hi = -10 * sigma + min(0.0, J.min()), 10 * sigma + max(0.0, J.max())
    for _ in range(60):
        x = 0.5 * (lo + hi)
        F = (1 - p) * Phi(x / sigma) + p * Phi((x - J) / sigma).mean()
        lo, hi = (x, hi) if F < q else (lo, x)
    return 0.5 * (lo + hi)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tel = pd.read_csv(RUN / "raw" / "telemetry.csv", usecols=["ts", "host", "temp", "cpu", "fan", "clock"])
    ev = pd.read_csv(RUN / "events.csv")
    amb = pd.read_csv(RUN / "raw" / "ambient.csv")
    amb = amb[amb.name.str.contains("ハブ")].sort_values("ts")
    prm = json.loads((RUN / "results" / "eval" / "params.json").read_text())
    dt, m, n, n_id = prm["dt"], prm["m"], prm["n"], prm["n_identify"]
    ps = ev[ev.event == "phase_start"]
    t0 = float(ps.ts.iloc[0])
    tk = t0 + np.arange(n) * dt
    bounds = ps.ts.to_numpy()
    kb = ((bounds[1:] - t0) // dt).astype(int)  # フェーズの境界のビン
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
        kf = run_kf(p, NoiseParams(R=nz["R"], qT=nz["qT"], qH0=0.0, beta=0.0), th, u, np.zeros(n), m, f=f)
        pred, sigma = kf["pred"], kf["sigma"]

        # 前半から:切り替えの確率 p と、切り替え後の (u', f') の分布
        p_sw = float(1 - steady[: n_id - m].mean())
        post = []
        edges = [0] + list(kb) + [n]
        for i in range(1, len(edges) - 1):
            s0, s1 = edges[i], edges[i + 1]
            if s1 > n_id:
                break
            seg = slice(s0 + 2, s1)  # 切り替え直後の 2 ビンを除いた平均
            post.append((float(np.mean(u[seg])), float(np.mean(f[seg]))))
        post = np.array(post)
        G = np.array([sum(p.a ** j for j in range(m - s)) for s in range(m)])  # 切り替えがステップ s のとき

        cache = {}
        M_risk = np.full(n, np.nan)
        for k in range(n):
            key = (round(u[k], 2), round(f[k], 1), round(sigma[k], 3))
            if key not in cache:
                dJ = p.b * (post[:, 0] - u[k]) + p.e * (post[:, 1] - f[k])
                J = (dJ[:, None] * G[None, :]).ravel()
                cache[key] = mixture_quantile(sigma[k], p_sw, J) + DELTA
            M_risk[k] = cache[key]
        M_prop = 2.0 * sigma + DELTA
        M_fix = fixed_margin_from(realized_errors(th, pred, m)[: n_id - m], ALPHA_Q)
        for name, M in (("提案(2σ+δ)", M_prop), ("Self-only + 固定", M_fix), ("切り替えの確率を含む", M_risk)):
            for sub, idx in subsets.items():
                rows.append({"node": role, "method": name, "subset": sub, **margin_rows(th, pred, M, m, idx)})
        info[role] = {"p_switch": p_sw, "n_transitions": len(post), "sigma": float(np.nanmean(sigma[n_id:])),
                      "fixed_margin": float(M_fix),
                      "risk_margin_range": [float(np.nanmin(M_risk[n_id:])), float(np.nanmax(M_risk[n_id:]))]}
        np.save(OUT / f"margin_{role}.npy", np.vstack([th, pred, M_prop, M_risk, u, f]))

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "margin_metrics.csv", index=False, float_format="%.4f")
    (OUT / "info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))
    piv = df.pivot_table(index=["node", "method"], columns="subset", values=["exceed_rate", "mean_margin"])
    with pd.option_context("display.width", 200):
        print(json.dumps(info, ensure_ascii=False, indent=1))
        print((piv * pd.Series({"exceed_rate": 100, "mean_margin": 1}, dtype=float).reindex(
            piv.columns.get_level_values(0)).to_numpy()).round(2))


if __name__ == "__main__":
    main()
