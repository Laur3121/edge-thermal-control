#!/usr/bin/env python3
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

try:
    from sklearn.metrics import r2_score
except ImportError:
    r2_score = None


def load_and_clean(csv_path, node=None):
    df = pd.read_csv(csv_path, low_memory=False)

    required = {"ts", "temp", "cpu_percent"}
    if not required.issubset(df.columns):
        raise SystemExit(f"{csv_path} must contain columns {required}")

    if node is not None and "host" in df.columns:
        df = df[df["host"] == node].copy()

    df["ts"] = pd.to_numeric(df["ts"], errors="coerce")
    df["temp"] = pd.to_numeric(df["temp"], errors="coerce")
    df["cpu_percent"] = pd.to_numeric(df["cpu_percent"], errors="coerce")

    df = df.dropna(subset=["ts", "temp", "cpu_percent"])
    df["cpu_percent"] = df["cpu_percent"].clip(0.0, 100.0)
    df = df.sort_values("ts").reset_index(drop=True)

    if len(df) < 10:
        raise SystemExit(f"not enough valid samples in {csv_path}")

    return df


def make_common_uniform_timeseries(t1, y1, u1, t2, z2, dt=None):
    t1 = np.asarray(t1, dtype=float)
    y1 = np.asarray(y1, dtype=float)
    u1 = np.asarray(u1, dtype=float)

    t2 = np.asarray(t2, dtype=float)
    z2 = np.asarray(z2, dtype=float)

    if dt is None:
        d1 = np.diff(t1)
        d2 = np.diff(t2)
        d1 = d1[d1 > 0]
        d2 = d2[d2 > 0]
        diffs = np.concatenate([d1, d2])
        if len(diffs) == 0:
            raise ValueError("time series too short or not increasing")
        dt = float(np.median(diffs))

    start = max(float(t1[0]), float(t2[0]))
    end = min(float(t1[-1]), float(t2[-1]))

    if end <= start:
        raise ValueError("no overlap between target and neighbor time ranges")

    tg = np.arange(start, end + 1e-9, dt)

    yg = np.interp(tg, t1, y1)
    ug = np.interp(tg, t1, u1)
    zg = np.interp(tg, t2, z2)

    return tg, yg, ug, zg, dt


def fit_model_self_only(T, u):
    """
    T_{k+1} = a*T_k + b*u_k + d
    """
    T0 = T[:-1]
    T1 = T[1:]
    u0 = u[:-1]

    X = np.column_stack([T0, u0, np.ones_like(T0)])
    theta, *_ = np.linalg.lstsq(X, T1, rcond=None)
    a, b, d = theta.tolist()
    return a, b, d


def fit_model_with_neighbor(T, u, z):
    """
    T_{k+1} = a*T_k + b*u_k + c*z_k + d
    ここで z は「中心化済みでも未中心化でも可」
    """
    T0 = T[:-1]
    T1 = T[1:]
    u0 = u[:-1]
    z0 = z[:-1]

    X = np.column_stack([T0, u0, z0, np.ones_like(T0)])
    theta, *_ = np.linalg.lstsq(X, T1, rcond=None)
    a, b, c, d = theta.tolist()
    return a, b, c, d


def predict_k_steps_self_only(T0, u_seq, a, b, d):
    Tk = float(T0)
    for uk in u_seq:
        Tk = a * Tk + b * uk + d
    return Tk


def calc_metrics(y_true, y_pred):
    e = y_true - y_pred
    mae = float(np.mean(np.abs(e)))
    rmse = float(np.sqrt(np.mean(e ** 2)))
    bias = float(np.mean(e))
    p95abs = float(np.quantile(np.abs(e), 0.95))
    maxabs = float(np.max(np.abs(e)))
    within_1c = float(np.mean(np.abs(e) <= 1.0))
    within_2c = float(np.mean(np.abs(e) <= 2.0))

    if r2_score is not None:
        r2 = float(r2_score(y_true, y_pred))
    else:
        ss_res = np.sum((y_true - y_pred) ** 2)
        ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
        r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else np.nan

    return {
        "bias_C": bias,
        "MAE_C": mae,
        "RMSE_C": rmse,
        "P95_abs_error_C": p95abs,
        "Max_abs_error_C": maxabs,
        "within_1C_ratio": within_1c,
        "within_2C_ratio": within_2c,
        "R2": r2,
    }, e


def summarize_prediction_method(name, y_true, y_pred):
    metrics, _ = calc_metrics(y_true, y_pred)
    out = {"method": name}
    out.update(metrics)
    return out


def summarize_method(name, ctrl, margin, violate, dt):
    control_count = int(np.sum(ctrl))
    control_ratio = float(np.mean(ctrl))
    mean_margin = float(np.mean(margin))
    max_margin = float(np.max(margin))
    miss_count = int(np.sum((~ctrl) & violate))
    violate_count = int(np.sum(violate))
    violate_time_s = float(np.sum(violate) * dt)

    return {
        "method": name,
        "control_count": control_count,
        "control_ratio": control_ratio,
        "mean_margin": mean_margin,
        "max_margin": max_margin,
        "miss_count": miss_count,
        "violate_count": violate_count,
        "violate_time_s": violate_time_s,
    }


def kalman_filter_estimate(
    T, u, z_centered,
    a, b, c, d,
    rho,
    qT, qH, r,
    H0=0.0,
    P0_scale=1.0,
    adaptive_qh=False,
    beta_qh=0.02
):
    """
    状態:
        x_k = [T_k, H_k]^T

    状態方程式:
        T_{k+1} = a*T_k + b*u_k + c*H_k + d + wT
        H_{k+1} = rho*H_k + (1-rho)*z_centered_k + wH

    adaptive_qh=True のとき:
        qH_k = qH + beta_qh * abs(z_k - z_{k-1})
    """
    n = len(T)
    if n < 2:
        raise ValueError("time series too short")

    A = np.array([[a, c],
                  [0.0, rho]], dtype=float)
    B = np.array([[b],
                  [0.0]], dtype=float)
    C = np.array([[1.0, 0.0]], dtype=float)

    R = np.array([[r]], dtype=float)

    x_filt = np.zeros((n, 2), dtype=float)
    P_filt = np.zeros((n, 2, 2), dtype=float)
    K_hist = np.zeros((n, 2), dtype=float)
    qH_hist = np.zeros(n, dtype=float)

    x_filt[0] = np.array([T[0], H0], dtype=float)
    P_filt[0] = np.eye(2, dtype=float) * P0_scale
    qH_hist[0] = qH

    for k in range(1, n):
        zk = float(z_centered[k - 1])

        if adaptive_qh:
            if k >= 2:
                dz = abs(float(z_centered[k - 1] - z_centered[k - 2]))
            else:
                dz = 0.0
            qH_k = qH + beta_qh * dz
        else:
            qH_k = qH

        qH_hist[k] = qH_k

        Qk = np.array([[qT, 0.0],
                       [0.0, qH_k]], dtype=float)

        bias_k = np.array([d, (1.0 - rho) * zk], dtype=float)

        x_pred = A @ x_filt[k - 1] + B.flatten() * u[k - 1] + bias_k
        P_pred = A @ P_filt[k - 1] @ A.T + Qk

        yk = float(T[k])
        innov = yk - float((C @ x_pred).item())
        S = C @ P_pred @ C.T + R
        K = P_pred @ C.T @ np.linalg.inv(S)

        x_filt[k] = x_pred + (K.flatten() * innov)
        P_filt[k] = (np.eye(2) - K @ C) @ P_pred
        K_hist[k] = K.flatten()

    return {
        "x_filt": x_filt,
        "P_filt": P_filt,
        "K_hist": K_hist,
        "A": A,
        "B": B,
        "C": C,
        "R": R,
        "rho": rho,
        "d": d,
        "qT": qT,
        "qH_base": qH,
        "qH_hist": qH_hist,
        "adaptive_qh": adaptive_qh,
        "beta_qh": beta_qh,
    }


def kalman_k_step_predict_from_filtered_state(
    x_now, P_now, u_seq, z_centered_seq,
    A, B, C, qT, qH, d, rho,
    steps,
    adaptive_qh=False,
    beta_qh=0.02
):
    """
    フィルタ済み状態から steps 先を予測する。
    adaptive_qh=True のときは、予測中も z の変化量に応じて qH を増やす。
    """
    x = x_now.copy()
    P = P_now.copy()

    qH_used = []

    for i in range(steps):
        uk = float(u_seq[i])
        zk = float(z_centered_seq[i])

        if adaptive_qh:
            if i >= 1:
                dz = abs(float(z_centered_seq[i] - z_centered_seq[i - 1]))
            else:
                dz = 0.0
            qH_k = qH + beta_qh * dz
        else:
            qH_k = qH

        qH_used.append(qH_k)

        Qk = np.array([[qT, 0.0],
                       [0.0, qH_k]], dtype=float)

        bias_k = np.array([d, (1.0 - rho) * zk], dtype=float)

        x = A @ x + B.flatten() * uk + bias_k
        P = A @ P @ A.T + Qk

    T_pred = float((C @ x).item())
    sigma_T = float(np.sqrt(max(P[0, 0], 0.0)))
    qH_mean = float(np.mean(qH_used)) if len(qH_used) > 0 else float(qH)

    return T_pred, P, sigma_T, qH_mean


def auto_noise_from_residuals(T, u, z, a, b, c, d):
    """
    回帰残差から Q, R の初期値をざっくり決める。
    z は中心化済み系列を渡す。
    """
    T0 = T[:-1]
    T1 = T[1:]
    u0 = u[:-1]
    z0 = z[:-1]

    pred = a * T0 + b * u0 + c * z0 + d
    resid = T1 - pred

    var_resid = float(np.var(resid)) if len(resid) > 1 else 0.1
    var_resid = max(var_resid, 1e-6)

    qT = 0.05 * var_resid
    qH = 0.01 * var_resid
    r = 0.10 * var_resid
    return qT, qH, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target_csv", required=True, help="CSV for target node (raspi1)")
    ap.add_argument("--neighbor_csv", required=True, help="CSV for neighbor node (raspi2)")
    ap.add_argument("--target_node", default=None, help="optional host filter for target csv")
    ap.add_argument("--neighbor_node", default=None, help="optional host filter for neighbor csv")
    ap.add_argument("--delta", type=float, default=30.0, help="prediction horizon [s]")
    ap.add_argument("--dt", type=float, default=None, help="uniform resample interval [s]")
    ap.add_argument("--p", type=float, default=0.95, help="quantile for fixed margin")
    ap.add_argument("--alpha", type=float, default=2.0, help="proposed margin coefficient")
    ap.add_argument("--k_sakamoto", type=float, default=1.0, help="Sakamoto-like correction coefficient")
    ap.add_argument("--err_window_s", type=float, default=60.0, help="window length for past-error correction [s]")
    ap.add_argument("--tlimit", type=float, default=80.0, help="temperature limit [degC]")
    ap.add_argument("--out", default="out_kalman")

    # kalman options
    ap.add_argument("--qT", type=float, default=None, help="process noise variance for T state")
    ap.add_argument("--qH", type=float, default=None, help="process noise variance for H state")
    ap.add_argument("--R", dest="Rval", type=float, default=None, help="measurement noise variance")
    ap.add_argument("--h0", type=float, default=0.0, help="initial external heat state")
    ap.add_argument("--p0", type=float, default=1.0, help="initial covariance scale")

    # revised state model option
    ap.add_argument("--rho", type=float, default=0.90, help="decay of external heat state")
    ap.add_argument("--z-base", dest="z_base", type=float, default=None, help="baseline neighbor temp")

    # adaptive qH
    ap.add_argument("--adaptive_qh", action="store_true",
                    help="enable adaptive qH based on neighbor temperature change")
    ap.add_argument("--beta_qh", type=float, default=0.02,
                    help="gain for adaptive qH: qH_k = qH + beta_qh * abs(dz)")

    args = ap.parse_args()

    # ---- load ----
    df_t = load_and_clean(args.target_csv, args.target_node)
    df_n = load_and_clean(args.neighbor_csv, args.neighbor_node)

    t1 = df_t["ts"].to_numpy(dtype=float)
    T1 = df_t["temp"].to_numpy(dtype=float)
    u1 = (df_t["cpu_percent"].to_numpy(dtype=float) / 100.0).clip(0.0, 1.0)

    t2 = df_n["ts"].to_numpy(dtype=float)
    z2 = df_n["temp"].to_numpy(dtype=float)

    # ---- resample ----
    tg, Tg, ug, zg, dt = make_common_uniform_timeseries(t1, T1, u1, t2, z2, dt=args.dt)
    time_rel = tg - tg[0]

    m = int(round(args.delta / dt))
    if m <= 0:
        raise SystemExit("delta too small")
    if m >= len(Tg) - 2:
        raise SystemExit("delta too large")

    # ---- baseline temperature of neighbor ----
    if args.z_base is None:
        z_base = float(np.median(zg[:max(10, len(zg)//10)]))
    else:
        z_base = float(args.z_base)

    # ---- 中心化した隣接温度 ----
    zg_centered = zg - z_base

    # ---- fit base models ----
    a0, b0, d0 = fit_model_self_only(Tg, ug)
    a1, b1, c1, d1 = fit_model_with_neighbor(Tg, ug, zg_centered)

    if 0 < a0 < 1:
        tau0 = -dt / np.log(a0)
    else:
        tau0 = np.nan

    if 0 < a1 < 1:
        tau1 = -dt / np.log(a1)
    else:
        tau1 = np.nan

    qT_auto, qH_auto, r_auto = auto_noise_from_residuals(Tg, ug, zg_centered, a1, b1, c1, d1)
    qT = qT_auto if args.qT is None else args.qT
    qH = qH_auto if args.qH is None else args.qH
    rval = r_auto if args.Rval is None else args.Rval

    print(f"[fit] dt={dt:.3f}s delta={args.delta:.3f}s steps={m}")
    print(f"[self-only] a={a0:.6f} b={b0:.6f} d={d0:.6f} tau≈{tau0:.2f}s")
    print(f"[neighbor ] a={a1:.6f} b={b1:.6f} c={c1:.6f} d={d1:.6f} tau≈{tau1:.2f}s")
    print(f"[kalman-revised] rho={args.rho:.4f} z_base={z_base:.3f}")
    print(f"[kalman-revised] qT={qT:.6f} qH={qH:.6f} R={rval:.6f}")
    print(f"[adaptive-qh] enabled={args.adaptive_qh} beta_qh={args.beta_qh:.6f}")

    # ---- self-only prediction ----
    T_pred_self = np.full_like(Tg, np.nan, dtype=float)
    for k in range(len(Tg) - m):
        T_pred_self[k] = predict_k_steps_self_only(Tg[k], ug[k:k + m], a0, b0, d0)

    t_plot = time_rel[:-m]
    T_meas_future = Tg[m:]
    T_pred_self_future = T_pred_self[:-m]

    # ---- Sakamoto-like correction ----
    _, e_self_tmp = calc_metrics(T_meas_future, T_pred_self_future)
    err_window = max(3, int(round(args.err_window_s / dt)))
    e_self_series = pd.Series(e_self_tmp)
    past_mean_err = (
        e_self_series.shift(1)
        .rolling(window=err_window, min_periods=3)
        .mean()
        .fillna(0.0)
        .to_numpy()
    )
    T_pred_saka_future = T_pred_self_future + args.k_sakamoto * past_mean_err

    # ---- revised Kalman filtering ----
    kf = kalman_filter_estimate(
        Tg, ug, zg_centered,
        a=a1, b=b1, c=c1, d=d1,
        rho=args.rho,
        qT=qT, qH=qH, r=rval,
        H0=args.h0,
        P0_scale=args.p0,
        adaptive_qh=args.adaptive_qh,
        beta_qh=args.beta_qh,
    )

    x_filt = kf["x_filt"]
    P_filt = kf["P_filt"]
    A = kf["A"]
    B = kf["B"]
    C = kf["C"]
    qH_hist = kf["qH_hist"]

    T_est = x_filt[:, 0]
    H_est = x_filt[:, 1]
    sigma_now = np.sqrt(np.maximum(P_filt[:, 0, 0], 0.0))

    # ---- proposed prediction ----
    T_pred_prop = np.full(len(Tg) - m, np.nan, dtype=float)
    sigma_prop = np.full(len(Tg) - m, np.nan, dtype=float)
    H_filt_now = np.full(len(Tg) - m, np.nan, dtype=float)
    qH_future_mean = np.full(len(Tg) - m, np.nan, dtype=float)

    for k in range(len(Tg) - m):
        Tpk, Ppk, spk, qh_mean_k = kalman_k_step_predict_from_filtered_state(
            x_now=x_filt[k],
            P_now=P_filt[k],
            u_seq=ug[k:k + m],
            z_centered_seq=zg_centered[k:k + m],
            A=A,
            B=B,
            C=C,
            qT=qT,
            qH=qH,
            d=d1,
            rho=args.rho,
            steps=m,
            adaptive_qh=args.adaptive_qh,
            beta_qh=args.beta_qh,
        )
        T_pred_prop[k] = Tpk
        sigma_prop[k] = spk
        H_filt_now[k] = x_filt[k, 1]
        qH_future_mean[k] = qh_mean_k

    T_pred_prop_future = T_pred_prop

    # ---- metrics ----
    base_metrics, e_self = calc_metrics(T_meas_future, T_pred_self_future)
    saka_metrics, e_saka = calc_metrics(T_meas_future, T_pred_saka_future)
    prop_metrics, e_prop = calc_metrics(T_meas_future, T_pred_prop_future)

    print(
        "[self-only] "
        f"bias={base_metrics['bias_C']:.3f}°C "
        f"MAE={base_metrics['MAE_C']:.3f}°C "
        f"RMSE={base_metrics['RMSE_C']:.3f}°C "
        f"95%|e|={base_metrics['P95_abs_error_C']:.3f}°C "
        f"R2={base_metrics['R2']:.4f}"
    )
    print(
        "[sakamoto ] "
        f"bias={saka_metrics['bias_C']:.3f}°C "
        f"MAE={saka_metrics['MAE_C']:.3f}°C "
        f"RMSE={saka_metrics['RMSE_C']:.3f}°C "
        f"95%|e|={saka_metrics['P95_abs_error_C']:.3f}°C "
        f"R2={saka_metrics['R2']:.4f}"
    )
    print(
        "[proposed-kf] "
        f"bias={prop_metrics['bias_C']:.3f}°C "
        f"MAE={prop_metrics['MAE_C']:.3f}°C "
        f"RMSE={prop_metrics['RMSE_C']:.3f}°C "
        f"95%|e|={prop_metrics['P95_abs_error_C']:.3f}°C "
        f"R2={prop_metrics['R2']:.4f}"
    )

    # ---- save prediction metrics ----
    pred_results = [
        summarize_prediction_method("self_only", T_meas_future, T_pred_self_future),
        summarize_prediction_method("sakamoto_like", T_meas_future, T_pred_saka_future),
        summarize_prediction_method("proposed_kalman", T_meas_future, T_pred_prop_future),
    ]
    pred_df = pd.DataFrame(pred_results)
    pred_metrics_csv = f"{args.out}_prediction_metrics.csv"
    pred_df.to_csv(pred_metrics_csv, index=False)
    print(f"[saved] {pred_metrics_csv}")

    # ---- margins ----
    q_fixed = float(np.quantile(e_self, args.p))
    margin_fixed = np.full_like(t_plot, q_fixed, dtype=float)

    err_std = (
        e_self_series.shift(1)
        .rolling(window=err_window, min_periods=3)
        .std()
        .fillna(0.0)
        .to_numpy()
    )
    margin_sakamoto = np.maximum(0.0, 2.0 * err_std)

    margin_proposed = np.maximum(0.0, args.alpha * sigma_prop + 0.5)

    T_safe_fixed = args.tlimit - margin_fixed
    T_safe_sakamoto = args.tlimit - margin_sakamoto
    T_safe_proposed = args.tlimit - margin_proposed

    ctrl_fixed = T_pred_self_future > T_safe_fixed
    ctrl_sakamoto = T_pred_saka_future > T_safe_sakamoto
    ctrl_proposed = T_pred_prop_future > T_safe_proposed

    violate_actual = T_meas_future > args.tlimit

    margin_results = [
        summarize_method("fixed", ctrl_fixed, margin_fixed, violate_actual, dt),
        summarize_method("sakamoto", ctrl_sakamoto, margin_sakamoto, violate_actual, dt),
        summarize_method("proposed_kalman", ctrl_proposed, margin_proposed, violate_actual, dt),
    ]
    margin_df = pd.DataFrame(margin_results)
    margin_metrics_csv = f"{args.out}_margin_metrics.csv"
    margin_df.to_csv(margin_metrics_csv, index=False)
    print(f"[saved] {margin_metrics_csv}")

    # ---- detailed comparison csv ----
    comp_df = pd.DataFrame({
        "time_s": t_plot,
        "T_meas_future": T_meas_future,
        "T_pred_self_only": T_pred_self_future,
        "T_pred_sakamoto_like": T_pred_saka_future,
        "T_pred_proposed_kalman": T_pred_prop_future,
        "neighbor_temp": zg[:-m],
        "neighbor_temp_centered": zg_centered[:-m],
        "T_est_filtered_now": T_est[:-m],
        "H_est_filtered_now": H_filt_now,
        "sigma_T_now": sigma_now[:-m],
        "sigma_T_future": sigma_prop,
        "qH_future_mean": qH_future_mean,
        "error_self_only": e_self,
        "error_sakamoto_like": e_saka,
        "error_proposed_kalman": e_prop,
        "past_mean_err_self_only": past_mean_err,
        "margin_fixed": margin_fixed,
        "margin_sakamoto": margin_sakamoto,
        "margin_proposed_kalman": margin_proposed,
        "T_safe_fixed": T_safe_fixed,
        "T_safe_sakamoto": T_safe_sakamoto,
        "T_safe_proposed_kalman": T_safe_proposed,
        "ctrl_fixed": ctrl_fixed.astype(int),
        "ctrl_sakamoto": ctrl_sakamoto.astype(int),
        "ctrl_proposed_kalman": ctrl_proposed.astype(int),
        "violate_actual": violate_actual.astype(int),
    })
    comp_csv = f"{args.out}_comparison.csv"
    comp_df.to_csv(comp_csv, index=False)
    print(f"[saved] {comp_csv}")
        # ---- save prediction time series for post-processing ----
    pred_ts_df = pd.DataFrame({
        "time_s": t_plot,
        "measured_temp": T_meas_future,
        "self_only_pred": T_pred_self_future,
        "sakamoto_pred": T_pred_saka_future,
        "proposed_kalman_pred": T_pred_prop_future,
    })
    pred_ts_csv = f"{args.out}_prediction_timeseries.csv"
    pred_ts_df.to_csv(pred_ts_csv, index=False)
    print(f"[saved] {pred_ts_csv}")

    # ---- state estimation csv ----
    state_df = pd.DataFrame({
        "time_s": time_rel,
        "T_meas": Tg,
        "u": ug,
        "neighbor_temp": zg,
        "neighbor_temp_centered": zg_centered,
        "T_est_filtered": T_est,
        "H_est_filtered": H_est,
        "sigma_T_filtered": sigma_now,
        "qH_used": qH_hist,
        "K_T": kf["K_hist"][:, 0],
        "K_H": kf["K_hist"][:, 1],
        "P11_T": P_filt[:, 0, 0],
        "P22_H": P_filt[:, 1, 1],
    })
    state_csv = f"{args.out}_state_estimation.csv"
    state_df.to_csv(state_csv, index=False)
    print(f"[saved] {state_csv}")

    # ---- plot 1: measured vs predictions ----
    plt.figure(figsize=(9, 5))
    plt.plot(t_plot, T_meas_future, label="Measured temp", linewidth=2.2)
    plt.plot(t_plot, T_pred_self_future, "--", label="Self-only", linewidth=1.8)
    plt.plot(t_plot, T_pred_saka_future, "--", label="Sakamoto-like", linewidth=1.8)
    plt.plot(t_plot, T_pred_prop_future, "--", label="Proposed (Kalman)", linewidth=2.0)
    plt.xlabel("Time [s]")
    plt.ylabel("Temperature [°C]")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_meas_vs_pred_all.png", dpi=200)

    # ---- plot 2: error comparison ----
    plt.figure(figsize=(9, 5))
    plt.plot(t_plot, e_self, label="Self-only error")
    plt.plot(t_plot, e_saka, label="Sakamoto-like error")
    plt.plot(t_plot, e_prop, label="Proposed (Kalman) error")
    plt.axhline(0.0, color="k", linestyle="--", linewidth=1.0)
    plt.xlabel("Time [s]")
    plt.ylabel("Prediction error [°C]")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_error_compare.png", dpi=200)

    # ---- plot 3: error histogram ----
    plt.figure(figsize=(8, 4.5))
    plt.hist(e_self, bins=35, alpha=0.6, label="Self-only")
    plt.hist(e_saka, bins=35, alpha=0.6, label="Sakamoto-like")
    plt.hist(e_prop, bins=35, alpha=0.6, label="Proposed (Kalman)")
    plt.xlabel("Prediction error [°C]")
    plt.ylabel("Count")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_error_hist_compare.png", dpi=200)

    # ---- plot 4: margin comparison ----
    plt.figure(figsize=(10, 5))
    plt.plot(t_plot, margin_fixed, label="Fixed margin")
    plt.plot(t_plot, margin_sakamoto, label="Sakamoto-like margin")
    plt.plot(t_plot, margin_proposed, label="Proposed (Kalman) margin")
    plt.xlabel("Time [s]")
    plt.ylabel("Margin [°C]")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_margin_compare.png", dpi=200)

    # ---- plot 5: state estimation ----
    plt.figure(figsize=(10, 5))
    plt.plot(time_rel, Tg, label="Measured temp")
    plt.plot(time_rel, T_est, label="Filtered temp estimate")
    plt.plot(time_rel, H_est, label="Estimated external heat effect")
    plt.xlabel("Time [s]")
    plt.ylabel("Value")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_state_estimation.png", dpi=200)

    # ---- plot 6: uncertainty ----
    plt.figure(figsize=(10, 4.5))
    plt.plot(time_rel, sigma_now, label="Filtered sigma_T")
    plt.xlabel("Time [s]")
    plt.ylabel("Std dev [°C]")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_uncertainty.png", dpi=200)

    # ---- plot 7: adaptive qH ----
    plt.figure(figsize=(10, 4.5))
    plt.plot(time_rel, qH_hist, label="Adaptive qH")
    plt.xlabel("Time [s]")
    plt.ylabel("qH")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_adaptive_qh.png", dpi=200)

    print("[done]")


if __name__ == "__main__":
    main()