#!/usr/bin/env python3
import argparse
import numpy as np
import pandas as pd

try:
    from sklearn.metrics import r2_score
except ImportError:
    r2_score = None


def calc_metrics(y_true, y_pred):
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


def evaluate_window(df, label, t_start=None, t_end=None):
    if t_start is None and t_end is None:
        sub = df.copy()
    else:
        sub = df[(df["time_s"] >= t_start) & (df["time_s"] <= t_end)].copy()

    if len(sub) < 5:
        raise ValueError(f"window '{label}' has too few samples: {len(sub)}")

    y_true = sub["T_meas_future"].to_numpy()

    methods = {
        "self_only": "T_pred_self_only",
        "sakamoto_like": "T_pred_sakamoto_like",
        "proposed": "T_pred_proposed",
    }

    rows = []
    for method_name, col in methods.items():
        y_pred = sub[col].to_numpy()
        metrics = calc_metrics(y_true, y_pred)
        row = {
            "window": label,
            "t_start_s": sub["time_s"].iloc[0],
            "t_end_s": sub["time_s"].iloc[-1],
            "n_samples": len(sub),
            "method": method_name,
        }
        row.update(metrics)
        rows.append(row)

    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="model_fit_comparison.csv")
    ap.add_argument("--out", default="event_eval", help="output prefix")
    ap.add_argument("--on_start", type=float, default=300.0, help="neighbor load ON time [s]")
    ap.add_argument("--on_end", type=float, default=450.0, help="evaluation end for ON event [s]")
    ap.add_argument("--off_start", type=float, default=900.0, help="neighbor load OFF time [s]")
    ap.add_argument("--off_end", type=float, default=1050.0, help="evaluation end for OFF event [s]")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)

    required = {
        "time_s",
        "T_meas_future",
        "T_pred_self_only",
        "T_pred_sakamoto_like",
        "T_pred_proposed",
    }
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        raise SystemExit(f"missing required columns: {missing}")

    results = []

    # 全区間
    results.append(evaluate_window(df, "full"))

    # 負荷投入区間
    results.append(evaluate_window(df, "event_on", args.on_start, args.on_end))

    # 負荷解除区間
    results.append(evaluate_window(df, "event_off", args.off_start, args.off_end))

    res_df = pd.concat(results, ignore_index=True)

    out_csv = f"{args.out}_metrics_by_window.csv"
    res_df.to_csv(out_csv, index=False)

    print(res_df.to_string(index=False))
    print(f"\n[saved] {out_csv}")

    # 見やすい要約表も保存
    pivot_cols = ["MAE_C", "RMSE_C", "P95_abs_error_C", "within_1C_ratio", "within_2C_ratio", "R2"]
    summary_tables = []

    for metric in pivot_cols:
        pivot = res_df.pivot(index="window", columns="method", values=metric)
        pivot.insert(0, "metric", metric)
        summary_tables.append(pivot.reset_index())

    summary_df = pd.concat(summary_tables, ignore_index=True)
    out_summary_csv = f"{args.out}_summary_table.csv"
    summary_df.to_csv(out_summary_csv, index=False)
    print(f"[saved] {out_summary_csv}")


if __name__ == "__main__":
    main()