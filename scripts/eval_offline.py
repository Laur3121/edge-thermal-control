#!/usr/bin/env python3
"""ログに対するオフライン評価:同定 → Δ秒先予測 → マージン。全手法を同じデータで比べる。

同定用と評価用は時間で分ける(--split の割合までを同定に使う)。
予測にはその時刻までの情報だけを使う(未来の負荷・隣接温度は「今の値が続く」と仮定)。

例:
python scripts/eval_offline.py \
  --target data/legacy/expC_2nodes_raspi2_2026-04-16.csv \
  --neighbor data/legacy/expC_2nodes_raspi1_2026-04-16.csv \
  --out experiments/20261112_legacy_kf_check/raspi2_target
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etc.baselines import (fixed_margin_from, predict_arx, realized_errors,  # noqa: E402
                           sakamoto_like)
from etc.data import align, load_node_log  # noqa: E402
from etc.kalman import NoiseParams, dynamic_margin, run_kf  # noqa: E402
from etc.metrics import margin_metrics, prediction_metrics  # noqa: E402
from etc.model import ThermalParams, fit_self_only, fit_with_H  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True)
    ap.add_argument("--neighbor", required=True)
    ap.add_argument("--target-host", default=None)
    ap.add_argument("--neighbor-host", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dt", type=float, default=None, help="刻み [s](省略時はログの中央値)")
    ap.add_argument("--delta", type=float, default=30.0, help="予測の先読み Δ [s]")
    ap.add_argument("--split", type=float, default=0.6, help="先頭からこの割合を同定に使う")
    ap.add_argument("--zbase-sec", type=float, default=60.0, help="先頭何秒の隣接温度の平均を z_base にするか")
    ap.add_argument("--fit-below", type=float, default=80.0,
                    help="この温度以上の遷移は同定に使わない(スロットリング区間を除く)")
    ap.add_argument("--u-smooth", type=float, default=0.0,
                    help="CPU 使用率を過去この秒数の移動平均にする(瞬時値しか記録されていないログ用)。0 で無効")
    ap.add_argument("--R", type=float, default=0.077)
    ap.add_argument("--qH0", type=float, default=0.008)
    ap.add_argument("--beta", type=float, default=2.0)
    ap.add_argument("--alpha", type=float, default=2.0)
    ap.add_argument("--delta-margin", type=float, default=0.5, help="マージン下限 δ [℃]")
    ap.add_argument("--tlimit", type=float, default=80.0)
    ap.add_argument("--fixed-q", type=float, default=0.977, help="固定マージンに使う誤差の分位点")
    ap.add_argument("--sakamoto-window", type=float, default=60.0, help="坂本型の誤差窓 [s]")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    s = align(load_node_log(args.target, args.target_host),
              load_node_log(args.neighbor, args.neighbor_host), dt=args.dt)
    dt, N = s.dt, len(s)
    if args.u_smooth > 0:  # 過去側だけの移動平均(その時刻までの情報だけを使う)
        w = max(1, int(round(args.u_smooth / dt)))
        s.u = pd.Series(s.u).rolling(w, min_periods=1).mean().to_numpy()
    m = int(round(args.delta / dt))
    n_id = int(N * args.split)
    idx_id, idx_ev = np.arange(n_id), np.arange(n_id, N)

    # ---- 同定(同定区間のみ、スロットリング域を除く)----
    T_id = s.T[:n_id]
    mask = T_id[:-1] < args.fit_below
    z_base = float(s.nbr[: max(2, int(args.zbase_sec / dt))].mean())
    p_self, r_self = fit_self_only(T_id, s.u[:n_id], dt, mask=mask)
    p_H, r_H = fit_with_H(T_id, s.u[:n_id], s.nbr[:n_id], dt, z_base=z_base, mask=mask)

    # qT:ARX の残差分散 ≈ qT + (1 + a^2) R(観測ノイズが前後2回入る)から逆算
    def qT_from(resid, a):
        return max(float(np.var(resid)) - (1 + a ** 2) * args.R, 1e-4)

    n_self = NoiseParams(R=args.R, qT=qT_from(r_self, p_self.a), qH0=args.qH0, beta=0.0)
    n_H = NoiseParams(R=args.R, qT=qT_from(r_H, p_H.a), qH0=args.qH0, beta=args.beta)

    # ---- 予測 ----
    pred = {}
    pred["Self-only"] = predict_arx(p_self, s.T, s.u, m)
    sk_pred, sk_margin = sakamoto_like(s.T, pred["Self-only"], m,
                                       window=int(round(args.sakamoto_window / dt)))
    pred["Sakamoto-like"] = sk_pred
    kf0 = run_kf(p_self, n_self, s.T, s.u, s.nbr, m)  # H なし KF(c = 0)
    kfH = run_kf(p_H, n_H, s.T, s.u, s.nbr, m)  # 提案
    pred["KF (no H)"] = kf0["pred"]
    pred["KF + H (proposed)"] = kfH["pred"]

    # ---- マージン ----
    def fixed(name):
        return fixed_margin_from(realized_errors(s.T, pred[name], m)[:n_id], args.fixed_q)

    margins = {
        "Self-only + fixed": ("Self-only", fixed("Self-only")),
        "Sakamoto-like": ("Sakamoto-like", sk_margin),
        "KF + H + fixed": ("KF + H (proposed)", fixed("KF + H (proposed)")),
        "Proposed (dynamic)": ("KF + H (proposed)", dynamic_margin(kfH["sigma"], args.alpha, args.delta_margin)),
    }

    # ---- 評価 ----
    rows = []
    for name, pr in pred.items():
        for part, idx in (("identify", idx_id), ("evaluate", idx_ev)):
            rows.append({"method": name, "part": part, **prediction_metrics(s.T, pr, m, idx)})
    pm = pd.DataFrame(rows)
    rows = []
    for name, (pname, M) in margins.items():
        for part, idx in (("identify", idx_id), ("evaluate", idx_ev)):
            rows.append({"method": name, "part": part,
                         **margin_metrics(s.T, pred[pname], M, m, args.tlimit, idx)})
    mm = pd.DataFrame(rows)
    pm.to_csv(out / "prediction_metrics.csv", index=False, float_format="%.4f")
    mm.to_csv(out / "margin_metrics.csv", index=False, float_format="%.4f")

    info = {
        "args": vars(args), "dt": dt, "m": m, "N": N, "n_identify": n_id,
        "n_fit_transitions": int(mask.sum()), "z_base": z_base,
        "self_only": p_self.to_dict(), "self_only_issues": p_self.check(),
        "with_H": p_H.to_dict(), "with_H_issues": p_H.check(),
        "noise_self": vars(n_self), "noise_H": vars(n_H),
    }
    (out / "params.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))

    # ---- 図 ----
    t = s.t
    tf = t + m * dt  # 予測が指す時刻
    fig, axes = plt.subplots(3, 1, figsize=(8, 8.5), sharex=True)
    ax = axes[0]
    ax.plot(t, s.T, "k-", lw=1.2, label="Measured (target)")
    ax.plot(t, s.nbr, color="0.6", lw=1.0, label="Neighbor")
    for name, ls in (("Self-only", "--"), ("KF (no H)", ":"), ("KF + H (proposed)", "-")):
        ax.plot(tf, pred[name], ls, lw=1.0, label=f"{name}, {args.delta:.0f} s ahead")
    ax.axhline(args.tlimit, color="r", lw=0.8)
    ax.axvline(t[n_id], color="0.3", lw=0.8, ls="-.")
    ax.set_ylabel("Temperature [°C]")
    ax.legend(fontsize=7, loc="lower right")
    ax = axes[1]
    ax.plot(t, s.u * 100, "k-", lw=1.0, label="Target CPU")
    ax.set_ylabel("CPU usage [%]")
    ax2 = ax.twinx()
    ax2.plot(t, kfH["H_hat"], "C2-", lw=1.0, label="Estimated H")
    ax2.set_ylabel("H [°C]")
    ax.axvline(t[n_id], color="0.3", lw=0.8, ls="-.")
    ax = axes[2]
    for name, (_, M) in margins.items():
        ax.plot(t, np.broadcast_to(M, t.shape), lw=1.0, label=name)
    ax.axvline(t[n_id], color="0.3", lw=0.8, ls="-.")
    ax.set_ylabel("Margin M [°C]")
    ax.set_xlabel("Time [s]  (dash-dot: identify | evaluate)")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "timeseries.png", dpi=150)

    print(f"dt={dt:.2f}s m={m} N={N} identify={n_id} fit_transitions={mask.sum()} z_base={z_base:.2f}")
    for lbl, p in (("self", p_self), ("withH", p_H)):
        print(f"[{lbl}] " + " ".join(f"{k}={v:.4f}" for k, v in p.to_dict().items()
                                    if k not in ("dt", "e")) + f"  issues={p.check()}")
    print(pm[pm.part == "evaluate"].drop(columns="part").to_string(index=False, float_format="%.3f"))
    print(mm[mm.part == "evaluate"].drop(columns="part").to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
