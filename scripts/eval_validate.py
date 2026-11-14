#!/usr/bin/env python3
"""検証用ランダム実験(validate_random)で、Δ秒先予測・σ・マージンを手法間で比べる。

- データ:各ノードの 1 秒ログを dt 秒平均にし、室温(ハブ)からの上昇分 θ = T − T_amb で扱う
- 同定:実験の前半(時間で半分に近いフェーズ境界まで)。3 台それぞれ、案B(+e·f)の Self-only と H 入り
- 評価:後半(同定に使っていない区間)。A は 11/13 の同定値(別の日)でも評価し、日をまたいで使えるかを見る
- 隣接入力:物理的に隣のノードの θ(A←B、B←A・C の平均、C←B)。z_base は p0_baseline の平均
- 予測は時刻 k までの情報だけ。負荷・隣接温度・ファン状態は「今の値が続く」と仮定
- 評価区間を 2 つに分ける:全区間 / 入力一定(k から k+Δ の間にフェーズ境界=負荷・ファンの切り替えがない)
  切り替えをまたぐ予測は、未来の入力を知らない以上どの手法でも外れる。σ がそれを含むかを見るために分ける

案B(11/14 夜に追加。評価の仕方は結果を見る前に決めた):
  負荷の急上昇マージン M_B = α σ + δ + J_k、J_k = b (u_max − u_k) Σ_{i<m} a^i(今から負荷が最大に跳ねたときの Δ 秒後の上昇)。
  J_k を足すのは、同定区間で「Δ 秒以内に負荷が上がる確率 p」が 1 − Φ(α)(α=2 なら 2.3%)を超えるとき。
  上側 1 − Φ(α) の上限を守るには、それより起きやすい負荷の上昇を含めないといけないため
--c-nonneg(既定):c < 0 と同定されたら c = 0(H なし)にする。c < 0 は物理的にありえないため(11/14 合意)

出力:<run>/results/eval/ に prediction_metrics.csv、margin_metrics.csv、params.json、図
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from etc.baselines import fixed_margin_from, predict_arx, realized_errors, sakamoto_like  # noqa: E402
from etc.kalman import NoiseParams, dynamic_margin, run_kf  # noqa: E402
from etc.metrics import prediction_metrics  # noqa: E402
from etc.model import ThermalParams, fit_self_only, fit_with_H  # noqa: E402

NEIGHBORS = {"A": ["B"], "B": ["A", "C"], "C": ["B"]}  # 物理的な並び:A | B | C


def resample(tel, host, dt, t0, n):
    g = tel[tel.host == host]
    k = ((g.ts - t0) // dt).astype(int)
    agg = g.groupby(k).agg(T=("temp", "mean"), u=("cpu", "mean"), f=("fan", "mean"), clock=("clock", "min"))
    agg = agg.reindex(range(n))
    agg["u"] = agg.u / 100.0
    return agg


def margin_rows(theta, pred, M, m, idx):
    k = idx[idx < len(theta) - m]
    y, yh = theta[k + m], pred[k]
    Mk = np.broadcast_to(np.asarray(M, float), theta.shape)[k]
    ok = ~(np.isnan(y) | np.isnan(yh) | np.isnan(Mk))
    y, yh, Mk = y[ok], yh[ok], Mk[ok]
    return {"n": int(ok.sum()), "mean_margin": float(Mk.mean()), "p95_margin": float(np.quantile(Mk, 0.95)),
            "exceed_rate": float(np.mean(y > yh + Mk))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--identify-json", default="experiments/20261113_step_identify/results/identify.json",
                    help="A の別日の同定結果(案B)")
    ap.add_argument("--dt", type=float, default=5.0)
    ap.add_argument("--delta", type=float, default=30.0)
    ap.add_argument("--R", type=float, default=None,
                    help="観測ノイズ分散 [℃²]。省略時は identify.json の R_1s / dt(1 秒値の分散を dt 平均に換算)")
    ap.add_argument("--qH0", type=float, default=0.008)
    ap.add_argument("--beta", type=float, default=2.0)
    ap.add_argument("--alpha", type=float, default=2.0)
    ap.add_argument("--delta-margin", type=float, default=0.5)
    ap.add_argument("--fixed-q", type=float, default=0.977)
    ap.add_argument("--sakamoto-window", type=float, default=300.0, help="坂本型の誤差窓 [s]")
    ap.add_argument("--ambient", default="ハブ")
    ap.add_argument("--u-max", type=float, default=1.0, help="案B:負荷の最大値(4 コア = 1.0)")
    ap.add_argument("--no-c-nonneg", dest="c_nonneg", action="store_false", help="c < 0 でもそのまま使う")
    out_dir_default = "eval"
    ap.add_argument("--out-name", default=out_dir_default, help="results/ の下の出力先")
    args = ap.parse_args()

    d = Path(args.run_dir)
    out = d / "results" / args.out_name
    out.mkdir(parents=True, exist_ok=True)
    tel = pd.read_csv(d / "raw" / "telemetry.csv")
    ev = pd.read_csv(d / "events.csv")
    amb = pd.read_csv(d / "raw" / "ambient.csv")
    amb = amb[amb.name.str.contains(args.ambient)].sort_values("ts")
    nodes = json.loads((d / "config.json").read_text())["nodes"]
    ident = json.loads(Path(args.identify_json).read_text())
    dt, m = args.dt, int(round(args.delta / args.dt))
    R = args.R if args.R is not None else ident["noise"]["R_1s"] / dt

    ps = ev[ev.event == "phase_start"]
    t0 = float(ps.ts.iloc[0])
    t_end = float(ev[ev.event == "end"].ts.iloc[0])
    n = int((t_end - t0) // dt)
    tk = t0 + np.arange(n) * dt  # ビンの開始時刻
    # 同定/評価の分割:時間の中点に最も近いフェーズ境界
    bounds = ps.ts.to_numpy()
    t_split = bounds[np.argmin(np.abs(bounds - (t0 + t_end) / 2))]
    n_id = int((t_split - t0) // dt)
    idx_id, idx_ev = np.arange(n_id), np.arange(n_id, n)
    # 入力一定:[k, k+m] のビンにフェーズ境界を含まない
    steady = np.ones(n, bool)
    for b in bounds[1:]:
        kb = int((b - t0) // dt)
        steady[max(0, kb - m - 1):kb + 1] = False
    Tamb = np.interp(tk + dt / 2, amb.ts.to_numpy(), amb.temperature.to_numpy())
    base_end = int((bounds[1] - t0) // dt)  # p0_baseline の終わり

    D = {r: resample(tel, h, dt, t0, n) for r, h in nodes.items()}
    theta = {r: D[r]["T"].to_numpy() - Tamb for r in nodes}

    info = {"dt": dt, "m": m, "n": n, "n_identify": n_id, "split_time": t_split, "R": R,
            "qH0": args.qH0, "beta": args.beta, "alpha": args.alpha, "delta_margin": args.delta_margin,
            "steady_ratio_eval": float(steady[idx_ev].mean()),
            "ambient_range": [float(Tamb.min()), float(Tamb.max())], "nodes": {}}
    prow, mrow, keep = [], [], {}

    def qT_from(resid, a):
        return max(float(np.var(resid)) - (1 + a ** 2) * R, 1e-4)

    variants = [(r, "11/14 first half") for r in nodes] + [("A", "11/13 step")]
    for role, src in variants:
        df = D[role]
        th = theta[role]
        u, f = df.u.to_numpy(), df.f.to_numpy()
        nbr = np.nanmean(np.column_stack([theta[x] for x in NEIGHBORS[role]]), axis=1)
        if np.isnan(th).any() or np.isnan(u).any():  # 欠損は前の値で埋める(ログ欠けは数秒程度)
            th = pd.Series(th).ffill().bfill().to_numpy()
            u = pd.Series(u).ffill().bfill().to_numpy()
            f = pd.Series(f).ffill().bfill().to_numpy()
            nbr = pd.Series(nbr).ffill().bfill().to_numpy()
        z_base = float(nbr[:base_end].mean())
        fit = np.zeros(n - 1, bool)
        fit[: n_id - 1] = True
        p_self, r_self = fit_self_only(th[:n_id], u[:n_id], dt, f=f[:n_id])
        p_H, r_H = fit_with_H(th[:n_id], u[:n_id], nbr[:n_id], dt, z_base=z_base, f=f[:n_id],
                              rho_grid=np.linspace(0.5, 0.995, 100))
        H_clipped = False
        if args.c_nonneg and p_H.c < 0:  # 物理的にありえないので H なしにする
            p_H, r_H, H_clipped = ThermalParams(**{**{k: getattr(p_self, k) for k in
                                                     ("a", "b", "d", "e", "dt")}, "c": 0.0,
                                                  "rho": p_H.rho, "z_base": z_base}), r_self, True
        if src == "11/13 step":
            cb = ident["caseB"]
            p_self = ThermalParams(a=cb["a"], b=cb["b"], d=cb["d"], e=cb["e"], dt=dt)
            X = np.column_stack([th[:n_id - 1], u[:n_id - 1], f[:n_id - 1], np.ones(n_id - 1)])
            r_self = th[1:n_id] - X @ np.array([cb["a"], cb["b"], cb["e"], cb["d"]])
            # H 入りは別日の値がないので、11/13 の自己項に前半で同定した c, ρ を足す
            p_H = ThermalParams(a=cb["a"], b=cb["b"], d=cb["d"], e=cb["e"], c=p_H.c, rho=p_H.rho,
                                z_base=z_base, dt=dt)
        n_self = NoiseParams(R=R, qT=qT_from(r_self, p_self.a), qH0=args.qH0, beta=0.0)
        n_H = NoiseParams(R=R, qT=qT_from(r_H, p_H.a), qH0=args.qH0, beta=args.beta)
        label = f"{role} ({src})"
        info["nodes"][label] = {"host": nodes[role], "neighbors": NEIGHBORS[role], "z_base": z_base,
                                "self": {**p_self.to_dict(), "issues": p_self.check()},
                                "withH": {**p_H.to_dict(), "issues": p_H.check(),
                                          "steady_rise_per_degC_of_nbr": p_H.c / (1 - p_H.a)},
                                "H_clipped_to_c0": H_clipped,
                                "resid_var_self": float(np.var(r_self)), "resid_var_H": float(np.var(r_H)),
                                "noise_self": vars(n_self), "noise_H": vars(n_H),
                                "T_max": float(np.nanmax(df["T"])), "clock_min": float(np.nanmin(df.clock))}

        pred = {"Self-only": predict_arx(p_self, th, u, m, f=f)}
        sk_pred, sk_M = sakamoto_like(th, pred["Self-only"], m, window=int(round(args.sakamoto_window / dt)))
        pred["Sakamoto-like"] = sk_pred
        kf0 = run_kf(p_self, n_self, th, u, nbr, m, f=f)
        kfH = run_kf(p_H, n_H, th, u, nbr, m, f=f)
        pred["KF (no H)"] = kf0["pred"]
        pred["KF + H (proposed)"] = kfH["pred"]

        def fixed(name):
            return fixed_margin_from(realized_errors(th, pred[name], m)[:n_id - m], args.fixed_q)

        # 案B:負荷の急上昇マージン
        du = np.full(n, np.nan)
        for k in range(n_id - m):
            du[k] = u[k + 1:k + m + 1].max() - u[k]
        p_inc = float(np.nanmean(du[:n_id - m] > 0.1))  # Δ 秒以内に負荷が 10% 以上上がった割合(同定区間)
        tail = 1 - 0.5 * (1 + math.erf(args.alpha / math.sqrt(2)))
        geo = sum(p_H.a ** i for i in range(m))
        J = p_H.b * np.clip(args.u_max - u, 0, None) * geo if p_inc > tail else np.zeros(n)
        info["nodes"][label].update({"p_load_increase": p_inc, "tail": tail, "jump_used": bool(p_inc > tail),
                                     "J_max": float(J.max())})
        margins = {"Self-only + fixed": ("Self-only", fixed("Self-only")),
                   "Sakamoto-like": ("Sakamoto-like", sk_M),
                   "KF + H + fixed": ("KF + H (proposed)", fixed("KF + H (proposed)")),
                   "Proposed (KF + H, ασ+δ)": ("KF + H (proposed)",
                                                dynamic_margin(kfH["sigma"], args.alpha, args.delta_margin)),
                   "Plan B (ασ+δ + load jump)": ("KF + H (proposed)",
                                                  dynamic_margin(kfH["sigma"], args.alpha, args.delta_margin) + J)}
        subsets = {"all": idx_ev, "steady": idx_ev[steady[idx_ev]], "switch": idx_ev[~steady[idx_ev]]}
        for name, pr in pred.items():
            for sub, idx in subsets.items():
                prow.append({"node": label, "method": name, "subset": sub,
                             **prediction_metrics(th, pr, m, idx)})
        for name, (pname, M) in margins.items():
            for sub, idx in subsets.items():
                mrow.append({"node": label, "method": name, "subset": sub,
                             **margin_rows(th, pred[pname], M, m, idx)})
        # σ の較正:標準化誤差 (実測 − 予測) / σ
        e = realized_errors(th, kfH["pred"], m)
        keep[label] = {"pred": pred, "margins": margins, "kfH": kfH, "z": e / kfH["sigma"], "u": u, "f": f,
                       "th": th}

    pm, mm = pd.DataFrame(prow), pd.DataFrame(mrow)
    pm.to_csv(out / "prediction_metrics.csv", index=False, float_format="%.4f")
    mm.to_csv(out / "margin_metrics.csv", index=False, float_format="%.4f")
    (out / "params.json").write_text(json.dumps(info, indent=2, ensure_ascii=False, default=float))

    # ---- 図1:A の評価区間の一部(約 40 分)を拡大 ----
    tmin = (tk - t0) / 60
    lab = "A (11/14 first half)"
    K = keep[lab]
    a0 = n_id + int(20 * 60 / dt)
    a1 = min(n, a0 + int(40 * 60 / dt))
    sl = slice(a0, a1)
    fig, ax = plt.subplots(3, 1, figsize=(8, 7.5), sharex=True, gridspec_kw={"height_ratios": [3, 1.3, 1]})
    tt = tmin[sl]
    tf = tmin[sl] + args.delta / 60  # 予測が指す時刻
    amb_s = Tamb[sl]
    ax[0].plot(tt, K["th"][sl] + amb_s, "k-", lw=1.3, label="Measured")
    ax[0].plot(tf, K["pred"]["KF + H (proposed)"][sl] + amb_s, "C0-", lw=1, label=f"KF + H, {args.delta:.0f} s ahead")
    Mp = K["margins"]["Proposed (KF + H, ασ+δ)"][1][sl]
    ax[0].fill_between(tf, K["pred"]["KF + H (proposed)"][sl] + amb_s,
                       K["pred"]["KF + H (proposed)"][sl] + amb_s + Mp, color="C0", alpha=0.2,
                       label="Proposed: prediction + M")
    Mf = K["margins"]["Self-only + fixed"][1]
    ax[0].plot(tf, K["pred"]["Self-only"][sl] + amb_s + Mf, "C3--", lw=0.9, label="Self-only + fixed margin")
    ax[0].set_ylabel("CPU temperature [°C]")
    ax[0].legend(fontsize=7, loc="upper left")
    for name, (_, M) in K["margins"].items():
        ax[1].plot(tt, np.broadcast_to(M, tmin.shape)[sl], lw=1, label=name)
    ax[1].set_ylabel("Margin M [°C]")
    ax[1].legend(fontsize=6.5, ncol=2, loc="upper left")
    ax[2].plot(tt, K["u"][sl] * 100, color="0.3", lw=1, label="CPU usage [%]")
    ax[2].set_ylabel("CPU usage [%]")
    ax2 = ax[2].twinx()
    ax2.step(tt, K["f"][sl], where="post", color="C2", lw=1)
    ax2.set_ylabel("Fan (0/1)", color="C2")
    ax2.set_ylim(-0.1, 1.5)
    ax[2].set_xlabel("Time from start [min]")
    fig.suptitle(f"Node A (raspi1), evaluation half (not used for identification), Δ = {args.delta:.0f} s", fontsize=9)
    fig.tight_layout()
    fig.savefig(out / "fig_A_zoom.png", dpi=150)

    # ---- 図2:標準化誤差のヒストグラム(σ の較正)----
    labs = [f"{r} (11/14 first half)" for r in nodes]
    fig, axes = plt.subplots(1, len(labs), figsize=(9, 3), sharey=True)
    xs = np.linspace(-6, 6, 200)
    for axx, lab in zip(axes, labs):
        z = keep[lab]["z"]
        for sub, color in (("steady", "C0"), ("switch", "C3")):
            idx = idx_ev[(steady if sub == "steady" else ~steady)[idx_ev]]
            zz = z[idx]
            zz = zz[~np.isnan(zz)]
            axx.hist(np.clip(zz, -6, 6), bins=np.linspace(-6, 6, 49), density=True, alpha=0.5, color=color,
                     label=f"{'inputs steady' if sub == 'steady' else 'input switch within Δ'} (n={len(zz)})")
        axx.plot(xs, np.exp(-xs ** 2 / 2) / np.sqrt(2 * np.pi), "k-", lw=1, label="N(0, 1)")
        axx.axvline(args.alpha, color="0.4", ls="--", lw=0.8)
        axx.set_title(lab.split(" ")[0] + f" ({nodes[lab[0]]})", fontsize=9)
        axx.set_xlabel("(measured − predicted) / σ  [-]")
    axes[0].set_ylabel("Density [-]")
    axes[0].legend(fontsize=6.5)
    fig.tight_layout()
    fig.savefig(out / "fig_sigma_calibration.png", dpi=150)

    pd.set_option("display.width", 200)
    print(json.dumps({k: v for k, v in info.items() if k != "nodes"}, default=float))
    for lab, v in info["nodes"].items():
        s, h = v["self"], v["withH"]
        print(f"{lab}: self a={s['a']:.3f} b={s['b']:.3f} e={s['e']:.3f} d={s['d']:.3f} tau={s['tau']:.0f}s "
              f"| H c={h['c']:.4f} rho={h['rho']:.3f} c/(1-a)={h['steady_rise_per_degC_of_nbr']:.3f} "
              f"| issues {s['issues'] + h['issues']} | qT={v['noise_H']['qT']:.3f} Tmax={v['T_max']:.1f}")
    print(pm.to_string(index=False, float_format="%.3f",
                       columns=["node", "method", "subset", "n", "bias", "MAE", "RMSE", "P97.7_err"]))
    print(mm.to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
