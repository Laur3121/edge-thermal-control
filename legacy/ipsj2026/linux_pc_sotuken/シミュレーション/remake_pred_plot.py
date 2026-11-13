#!/usr/bin/env python3
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


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


def fit_model_with_neighbor(T, u, z):
    T0 = T[:-1]
    T1 = T[1:]
    u0 = u[:-1]
    z0 = z[:-1]

    X = np.column_stack([T0, u0, z0, np.ones_like(T0)])
    theta, *_ = np.linalg.lstsq(X, T1, rcond=None)
    a, b, c, d = theta.tolist()
    return a, b, c, d


def predict_k_steps(T0, u_seq, z_seq, a, b, c, d):
    Tk = float(T0)
    for uk, zk in zip(u_seq, z_seq):
        Tk = a * Tk + b * uk + c * zk + d
    return Tk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target_csv", required=True, help="CSV for target node")
    ap.add_argument("--neighbor_csv", required=True, help="CSV for neighbor node")
    ap.add_argument("--target_node", default=None, help="optional host filter for target csv")
    ap.add_argument("--neighbor_node", default=None, help="optional host filter for neighbor csv")
    ap.add_argument("--delta", type=float, default=30.0, help="prediction horizon [s]")
    ap.add_argument("--dt", type=float, default=None, help="uniform resample interval [s]")
    ap.add_argument("--margin", type=float, default=2.546, help="safety margin [degC]")
    ap.add_argument("--tlimit", type=float, default=80.0, help="temperature limit [degC]")
    ap.add_argument("--out", default="pred_plot")
    args = ap.parse_args()

    df_t = load_and_clean(args.target_csv, args.target_node)
    df_n = load_and_clean(args.neighbor_csv, args.neighbor_node)

    t1 = df_t["ts"].to_numpy(dtype=float)
    T1 = df_t["temp"].to_numpy(dtype=float)
    u1 = (df_t["cpu_percent"].to_numpy(dtype=float) / 100.0).clip(0.0, 1.0)

    t2 = df_n["ts"].to_numpy(dtype=float)
    z2 = df_n["temp"].to_numpy(dtype=float)

    tg, Tg, ug, zg, dt = make_common_uniform_timeseries(t1, T1, u1, t2, z2, dt=args.dt)
    time_rel = tg - tg[0]

    m = int(round(args.delta / dt))
    if m <= 0:
        raise SystemExit("delta too small")
    if m >= len(Tg) - 2:
        raise SystemExit("delta too large")

    a, b, c, d = fit_model_with_neighbor(Tg, ug, zg)

    T_pred = np.full_like(Tg, np.nan, dtype=float)
    for k in range(len(Tg) - m):
        T_pred[k] = predict_k_steps(Tg[k], ug[k:k + m], zg[k:k + m], a, b, c, d)

    t_plot = time_rel[:-m]
    T_meas_future = Tg[m:]
    T_pred_future = T_pred[:-m]
    T_pred_margin = T_pred_future + args.margin

    e = T_meas_future - T_pred_future
    mae = float(np.mean(np.abs(e)))
    rmse = float(np.sqrt(np.mean(e ** 2)))
    bias = float(np.mean(e))

    print(f"a={a:.6f}, b={b:.6f}, c={c:.6f}, d={d:.6f}")
    print(f"MAE={mae:.3f} RMSE={rmse:.3f} Bias={bias:.3f}")

    # 実測 vs 予測
    plt.figure(figsize=(8, 4.8))
    plt.plot(t_plot, T_meas_future, label="Measured temperature", linewidth=2.2)
    plt.plot(t_plot, T_pred_future, label="Predicted temperature", linewidth=2.0)
    plt.plot(t_plot, T_pred_margin, label=f"Predicted + margin ({args.margin:.3f}°C)", linewidth=2.0)
    plt.axhline(args.tlimit, linewidth=1.5, label=f"Limit ({args.tlimit:.0f}°C)")
    plt.xlabel("Time [s]")
    plt.ylabel("Temperature [°C]")
    plt.title(f"Measured vs Predicted Temperature (Δ={args.delta:.0f}s)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_measured_vs_predicted.png", dpi=200)

    # 実測と予測の差だけを見たいとき用
    plt.figure(figsize=(8, 4.2))
    plt.plot(t_plot, e, linewidth=2.0)
    plt.axhline(0, linewidth=1.2)
    plt.axhline(args.margin, linewidth=1.2, linestyle="--", label=f"+margin ({args.margin:.3f})")
    plt.axhline(-args.margin, linewidth=1.2, linestyle="--", label=f"-margin ({args.margin:.3f})")
    plt.xlabel("Time [s]")
    plt.ylabel("Prediction error [°C]")
    plt.title("Prediction Error Over Time")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{args.out}_error_timeseries.png", dpi=200)

    print(f"saved: {args.out}_measured_vs_predicted.png")
    print(f"saved: {args.out}_error_timeseries.png")


if __name__ == "__main__":
    main()