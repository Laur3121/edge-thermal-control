#!/usr/bin/env python3
import argparse
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def load_csv(csv_path):
    df = pd.read_csv(csv_path)

    required = {
        "time_s",
        "T_meas_future",
        "T_pred_self_only",
        "T_pred_sakamoto_like",
        "T_pred_proposed",
        "error_self_only",
        "error_sakamoto_like",
        "error_proposed",
    }
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        raise SystemExit(f"missing required columns: {missing}")

    return df


def plot_full_prediction(df, out_prefix):
    plt.figure(figsize=(9, 5))
    plt.plot(df["time_s"], df["T_meas_future"], label="Measured", linewidth=2.6)
    plt.plot(df["time_s"], df["T_pred_self_only"], "--", label="Self-only", linewidth=1.8)
    plt.plot(df["time_s"], df["T_pred_sakamoto_like"], "--", label="Sakamoto-like", linewidth=1.8)
    plt.plot(df["time_s"], df["T_pred_proposed"], "--", label="Proposed", linewidth=2.0)

    plt.axvline(300, linestyle="--", linewidth=1.2, label="Disturbance ON")
    plt.axvline(900, linestyle="--", linewidth=1.2, label="Disturbance OFF")

    plt.xlabel("Time [s]")
    plt.ylabel("Temperature [°C]")
    plt.title("Measured and predicted temperature over the full interval")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{out_prefix}_full_prediction.png", dpi=220)
    plt.close()


def plot_event_on_zoom(df, out_prefix, on_start, on_end):
    sub = df[(df["time_s"] >= on_start) & (df["time_s"] <= on_end)].copy()
    if len(sub) < 3:
        raise ValueError("too few samples in event_on zoom window")

    plt.figure(figsize=(8, 4.5))
    plt.plot(sub["time_s"], sub["T_meas_future"], label="Measured", linewidth=2.8)
    plt.plot(sub["time_s"], sub["T_pred_self_only"], "--", label="Self-only", linewidth=2.0)
    plt.plot(sub["time_s"], sub["T_pred_sakamoto_like"], "--", label="Sakamoto-like", linewidth=2.0)
    plt.plot(sub["time_s"], sub["T_pred_proposed"], "--", label="Proposed", linewidth=2.2)

    plt.axvline(on_start, linestyle="--", linewidth=1.3, label="Disturbance ON")

    plt.xlabel("Time [s]")
    plt.ylabel("Temperature [°C]")
    plt.title("Prediction around disturbance input")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{out_prefix}_event_on_zoom.png", dpi=220)
    plt.close()


def plot_event_on_abs_error(df, out_prefix, on_start, on_end):
    sub = df[(df["time_s"] >= on_start) & (df["time_s"] <= on_end)].copy()
    if len(sub) < 3:
        raise ValueError("too few samples in event_on abs-error window")

    plt.figure(figsize=(8, 4.5))
    plt.plot(sub["time_s"], np.abs(sub["error_self_only"]), label="|Self-only error|", linewidth=2.0)
    plt.plot(sub["time_s"], np.abs(sub["error_sakamoto_like"]), label="|Sakamoto-like error|", linewidth=2.0)
    plt.plot(sub["time_s"], np.abs(sub["error_proposed"]), label="|Proposed error|", linewidth=2.2)

    plt.axvline(on_start, linestyle="--", linewidth=1.3, label="Disturbance ON")

    plt.xlabel("Time [s]")
    plt.ylabel("Absolute error [°C]")
    plt.title("Absolute prediction error after disturbance")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"{out_prefix}_event_on_abs_error.png", dpi=220)
    plt.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="comparison csv from predict_rc.py")
    ap.add_argument("--out", default="paperfig", help="output file prefix")
    ap.add_argument("--on_start", type=float, default=300.0, help="disturbance ON time [s]")
    ap.add_argument("--on_end", type=float, default=450.0, help="zoom end time [s]")
    args = ap.parse_args()

    df = load_csv(args.csv)

    plot_full_prediction(df, args.out)
    plot_event_on_zoom(df, args.out, args.on_start, args.on_end)
    plot_event_on_abs_error(df, args.out, args.on_start, args.on_end)

    print(f"[saved] {args.out}_full_prediction.png")
    print(f"[saved] {args.out}_event_on_zoom.png")
    print(f"[saved] {args.out}_event_on_abs_error.png")


if __name__ == "__main__":
    main()