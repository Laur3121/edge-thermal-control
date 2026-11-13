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


def predict_k_steps_with_neighbor(T0, u_seq, z_seq, a, b, c, d):
    Tk = float(T0)
    for uk, zk in zip(u_seq, z_seq):
        Tk = a * Tk + b * uk + c * zk + d
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
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    # ---- load ----
    df_t = load_and_clean(args.target_csv, args.target_node)
    df_n = load_and_clean(args.neighbor_csv, args.neighbor_node)

    # target
    t1 = df_t["ts"].to_numpy(dtype=float)
    T1 = df_t["temp"].to_numpy(dtype=float)
    u1 = (df_t["cpu_percent"].to_numpy(dtype=float) / 100.0).clip(0.0, 1.0)

    # neighbor input: use temperature
    t2 = df_n["ts"].to_numpy(dtype=float)
    z2 = df_n["temp"].to_numpy(dtype=float)

    # ---- resample to common time base ----
    tg, Tg, ug, zg, dt = make_common_uniform_timeseries(t1, T1, u1, t2, z2, dt=args.dt)
    time_rel = tg - tg[0]

    m = int(round(args.delta / dt))
    if m <= 0:
        raise SystemExit("delta too small")
    if m >= len(Tg) - 2:
        raise SystemExit("delta too large")

    # ---- fit models ----
    a0, b0, d0 = fit_model_self_only(Tg, ug)
    a1, b1, c1, d1 = fit_model_with_neighbor(Tg, ug, zg)

    if 0 < a0 < 1:
        tau0 = -dt / np.log(a0)
    else:
        tau0 = np.nan

    if 0 < a1 < 1:
        tau1 = -dt / np.log(a1)
    else:
        tau1 = np.nan

    print(f"[fit] dt={dt:.3f}s delta={args.delta:.3f}s steps={m}")
    print(f"[self-only] a={a0:.6f} b={b0:.6f} d={d0:.6f} tau≈{tau0:.2f}s")
    print(f"[proposed ] a={a1:.6f} b={b1:.6f} c={c1:.6f} d={d1:.6f} tau≈{tau1:.2f}s")

    # ---- delta-ahead prediction ----
    T_pred_self = np.full_like(Tg, np.nan, dtype=float)
    T_pred_prop = np.full_like(Tg, np.nan, dtype=float)

    for k in range(len(Tg) - m):
        T_pred_self[k] = predict_k_steps_self_only(Tg[k], ug[k:k + m], a0, b0, d0)
        T_pred_prop[k] = predict_k_steps_with_neighbor(Tg[k], ug[k:k + m], zg[k:k + m], a1, b1, c1, d1)

    t_plot = time_rel[:-m]
    T_meas_future = Tg[m:]
    T_pred_self_future = T_pred_self[:-m]
    T_pred_prop_future = T_pred_prop[:-m]
    z_future = zg[:-m]

    # ---- errors ----
    base_metrics, e_self = calc_metrics(T_meas_future, T_pred_self_future)
    prop_metrics, e_prop = calc_metrics(T_meas_future, T_pred_prop_future)

    # ---- Sakamoto-like correction using past error of self-only model ----
    # use only past information: rolling mean of previous errors
    err_window = max(3, int(round(args.err_window_s / dt)))
    e_self_series = pd.Series(e_self)
    past_mean_err = (
        e_self_series.shift(1)
        .rolling(window=err_window, min_periods=3)
        .mean()
        .fillna(0.0)
        .to_numpy()
    )

    T_pred_saka_future = T_pred_self_future + args.k_sakamoto * past_mean_err
    saka_metrics, e_saka = calc_metrics(T_meas_future, T_pred_saka_future)

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
        "[proposed ] "
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
        summarize_prediction_method("proposed", T_meas_future, T_pred_prop_future),
    ]
    pred_df = pd.DataFrame(pred_results)
    pred_metrics_csv = f"{args.out}_prediction_metrics.csv"
    pred_df.to_csv(pred_metrics_csv, index=False)
    print(f"[saved] {pred_metrics_csv}")

    # ---- margin comparison (optional secondary analysis) ----
    # Fixed margin: quantile of self-only error
    q_fixed = float(np.quantile(e_self, args.p))
    margin_fixed = np.full_like(t_plot, q_fixed, dtype=float)

    # Sakamoto-like margin: rolling std of past self-only error
    err_std = (
        e_self_series.shift(1)
        .rolling(window=err_window, min_periods=3)
        .std()
        .fillna(0.0)
        .to_numpy()
    )
    margin_sakamoto = np.maximum(0.0, 2.0 * err_std)

    # Proposed margin: rolling std of neighbor temperature
    z_series = pd.Series(z_future)
    z_std = (
        z_series.shift(1)
        .rolling(window=err_window, min_periods=3)
        .std()
        .fillna(0.0)
        .to_numpy()
    )
    decay = 0.95  # ←追加
    z_std_smoothed = z_std.copy()
    for i in range(1, len(z_std)):
        z_std_smoothed[i] = max(z_std[i], decay * z_std_smoothed[i-1])

    margin_proposed = np.maximum(0.0, args.alpha * z_std_smoothed)

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
        summarize_method("proposed", ctrl_proposed, margin_proposed, violate_actual, dt),
    ]
    margin_df = pd.DataFrame(margin_results)
    margin_metrics_csv = f"{args.out}_margin_metrics.csv"
    margin_df.to_csv(margin_metrics_csv, index=False)
    print(f"[saved] {margin_metrics_csv}")

    # ---- save detailed comparison csv ----
    comp_df = pd.DataFrame({
        "time_s": t_plot,
        "T_meas_future": T_meas_future,
        "T_pred_self_only": T_pred_self_future,
        "T_pred_sakamoto_like": T_pred_saka_future,
        "T_pred_proposed": T_pred_prop_future,
        "neighbor_temp": z_future,
        "error_self_only": e_self,
        "error_sakamoto_like": e_saka,
        "error_proposed": e_prop,
        "past_mean_err_self_only": past_mean_err,
        "margin_fixed": margin_fixed,
        "margin_sakamoto": margin_sakamoto,
        "margin_proposed": margin_proposed,
        "T_safe_fixed": T_safe_fixed,
        "T_safe_sakamoto": T_safe_sakamoto,
        "T_safe_proposed": T_safe_proposed,
        "ctrl_fixed": ctrl_fixed.astype(int),
        "ctrl_sakamoto": ctrl_sakamoto.astype(int),
        "ctrl_proposed": ctrl_proposed.astype(int),
        "violate_actual": violate_actual.astype(int),
    })
    comp_csv = f"{args.out}_comparison.csv"
    comp_df.to_csv(comp_csv, index=False)
    print(f"[saved] {comp_csv}")

    # ---- plot 1: measured vs predictions ----
    plt.figure(figsize=(9, 5))
    plt.plot(t_plot, T_meas_future, label="Measured temp", linewidth=2.2)
    plt.plot(t_plot, T_pred_self_future, "--", label="Self-only", linewidth=1.8)
    plt.plot(t_plot, T_pred_saka_future, "--", label="Sakamoto-like", linewidth=1.8)
    plt.plot(t_plot, T_pred_prop_future, "--", label="Proposed", linewidth=2.0)
    plt.xlabel("Time [s]")
    plt.ylabel("Temperature [°C]")
    plt.title("Measured vs Predicted Temperature")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_meas_vs_pred_all.png", dpi=200)

    # ---- plot 2: error comparison ----
    plt.figure(figsize=(9, 5))
    plt.plot(t_plot, e_self, label="Self-only error")
    plt.plot(t_plot, e_saka, label="Sakamoto-like error")
    plt.plot(t_plot, e_prop, label="Proposed error")
    plt.axhline(0.0, color="k", linestyle="--", linewidth=1.0)
    plt.xlabel("Time [s]")
    plt.ylabel("Prediction error [°C]")
    plt.title("Prediction Error Comparison")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_error_compare.png", dpi=200)

    # ---- plot 3: histogram ----
    plt.figure(figsize=(8, 4.5))
    plt.hist(e_self, bins=35, alpha=0.6, label="Self-only")
    plt.hist(e_saka, bins=35, alpha=0.6, label="Sakamoto-like")
    plt.hist(e_prop, bins=35, alpha=0.6, label="Proposed")
    plt.xlabel("Prediction error [°C]")
    plt.ylabel("Count")
    plt.title(f"Error distribution (Δ={args.delta:.0f}s)")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_error_hist_compare.png", dpi=200)

    # ---- plot 4: margin comparison ----
    plt.figure(figsize=(10, 5))
    plt.plot(t_plot, margin_fixed, label="Fixed margin")
    plt.plot(t_plot, margin_sakamoto, label="Sakamoto-like margin")
    plt.plot(t_plot, margin_proposed, label="Proposed margin")
    plt.xlabel("Time [s]")
    plt.ylabel("Margin [°C]")
    plt.title("Margin Comparison")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_margin_compare.png", dpi=200)

    # ---- plot 5: neighbor temp ----
    plt.figure(figsize=(10, 4))
    plt.plot(t_plot, z_future, label="Neighbor temperature")
    plt.xlabel("Time [s]")
    plt.ylabel("Temperature [°C]")
    plt.title("Neighbor Node Temperature")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_neighbor_temp.png", dpi=200)

    print("[done]")


if __name__ == "__main__":
    main()