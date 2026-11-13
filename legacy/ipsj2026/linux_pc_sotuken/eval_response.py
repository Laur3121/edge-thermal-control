#!/usr/bin/env python3
import argparse
import numpy as np
import pandas as pd

try:
    from sklearn.metrics import r2_score
except ImportError:
    r2_score = None


METHOD_COLS = {
    "self_only": "T_pred_self_only",
    "sakamoto_like": "T_pred_sakamoto_like",
    "proposed": "T_pred_proposed",
}


def calc_basic_metrics(y_true, y_pred):
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
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
    }


def first_time_within_error(sub_df, pred_col, threshold_c=1.0):
    err = np.abs(sub_df["T_meas_future"].to_numpy() - sub_df[pred_col].to_numpy())
    times = sub_df["time_s"].to_numpy()
    idx = np.where(err <= threshold_c)[0]
    if len(idx) == 0:
        return np.nan
    return float(times[idx[0]] - times[0])


def evaluate_response_window(df, label, t_start, t_end, settle_threshold=1.0):
    sub = df[(df["time_s"] >= t_start) & (df["time_s"] <= t_end)].copy()
    if len(sub) < 5:
        raise ValueError(f"window '{label}' has too few samples: {len(sub)}")

    rows = []
    for method, col in METHOD_COLS.items():
        metrics = calc_basic_metrics(sub["T_meas_future"], sub[col])
        settle_time = first_time_within_error(sub, col, threshold_c=settle_threshold)

        row = {
            "window": label,
            "t_start_s": float(sub["time_s"].iloc[0]),
            "t_end_s": float(sub["time_s"].iloc[-1]),
            "n_samples": int(len(sub)),
            "method": method,
            "settle_time_to_1C_s": settle_time,
        }
        row.update(metrics)
        rows.append(row)

    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="model_fit_comparison.csv")
    ap.add_argument("--out", default="response_eval", help="output prefix")
    ap.add_argument("--on_start", type=float, default=300.0, help="disturbance ON start [s]")
    ap.add_argument("--early30_end", type=float, default=330.0, help="early response end (30 s) [s]")
    ap.add_argument("--early60_end", type=float, default=360.0, help="early response end (60 s) [s]")
    ap.add_argument("--settle_threshold", type=float, default=1.0, help="settling threshold [C]")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)

    required = {"time_s", "T_meas_future", *METHOD_COLS.values()}
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        raise SystemExit(f"missing required columns: {missing}")

    res_30 = evaluate_response_window(
        df, "event_on_30s", args.on_start, args.early30_end, args.settle_threshold
    )
    res_60 = evaluate_response_window(
        df, "event_on_60s", args.on_start, args.early60_end, args.settle_threshold
    )

    res_df = pd.concat([res_30, res_60], ignore_index=True)
    out_csv = f"{args.out}_response_metrics.csv"
    res_df.to_csv(out_csv, index=False)

    print(res_df.to_string(index=False))
    print(f"\n[saved] {out_csv}")

    # 見やすい簡易表
    metrics_to_show = ["MAE_C", "RMSE_C", "Max_abs_error_C", "within_1C_ratio", "settle_time_to_1C_s"]
    tables = []
    for metric in metrics_to_show:
        pivot = res_df.pivot(index="window", columns="method", values=metric)
        pivot.insert(0, "metric", metric)
        tables.append(pivot.reset_index())

    summary_df = pd.concat(tables, ignore_index=True)
    out_summary = f"{args.out}_response_summary.csv"
    summary_df.to_csv(out_summary, index=False)
    print(f"[saved] {out_summary}")


if __name__ == "__main__":
    main()