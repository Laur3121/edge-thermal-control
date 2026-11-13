#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import math
import os
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Tuple

import numpy as np


# =========================
# Utility
# =========================

def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def ssh_run(host: str, user: str, remote_cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    target = f"{user}@{host}" if user else host
    result = subprocess.run(
        [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5",
            target,
            remote_cmd,
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"SSH failed: target={target}, cmd={remote_cmd}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
    return result


def ssh_output(host: str, user: str, remote_cmd: str) -> str:
    return ssh_run(host, user, remote_cmd, check=True).stdout.strip()


# =========================
# Remote sensors / load
# =========================

def get_pi_temp_c(host: str, user: str) -> float:
    out = ssh_output(host, user, "vcgencmd measure_temp")
    # temp=54.8'C
    value = out.replace("temp=", "").replace("'C", "").strip()
    return float(value)


def start_stress(host: str, user: str, cpu_workers: int, cpu_load: int, pidfile: str) -> None:
    cmd = (
        f"bash -lc '"
        f"if [ -f {pidfile} ] && kill -0 $(cat {pidfile}) 2>/dev/null; then exit 0; fi; "
        f"nohup stress-ng --cpu {cpu_workers} --cpu-load {cpu_load} >/dev/null 2>&1 & "
        f"echo $! > {pidfile}"
        f"'"
    )
    ssh_run(host, user, cmd, check=True)


def stop_stress(host: str, user: str, pidfile: str) -> None:
    cmd = (
        f"bash -lc '"
        f"if [ -f {pidfile} ]; then "
        f"PID=$(cat {pidfile}); "
        f"kill $PID 2>/dev/null || true; "
        f"rm -f {pidfile}; "
        f"fi"
        f"'"
    )
    ssh_run(host, user, cmd, check=False)


# =========================
# Models
# =========================

@dataclass
class ScalarModelParams:
    a: float
    b: float
    c: float
    d: float


class ScalarPredictor:
    """
    fixed / sakamoto 用
    T_{t+1} = a T_t + b u_t + c z_t + d
    """
    def __init__(self, params: ScalarModelParams):
        self.params = params

    def predict_one_step(self, T: float, u: float, z: float) -> float:
        p = self.params
        return p.a * T + p.b * u + p.c * z + p.d

    def predict_horizon(self, T0: float, u: float, z: float, steps: int) -> float:
        T = T0
        for _ in range(steps):
            T = self.predict_one_step(T, u, z)
        return T


class KalmanThermalPredictor:
    """
    proposed 用
    x_t = [T_t, H_t]^T
    x_{t+1} = A x_t + B u_t + w_t
    y_t     = C x_t + v_t
    """
    def __init__(
        self,
        a: float,
        b: float,
        c: float,
        qT: float,
        qH: float,
        r: float,
        init_T: float,
        init_H: float = 0.0,
        init_PT: float = 1.0,
        init_PH: float = 1.0,
    ):
        self.A = np.array([[a, c],
                           [0.0, 1.0]], dtype=float)
        self.B = np.array([[b],
                           [0.0]], dtype=float)
        self.C = np.array([[1.0, 0.0]], dtype=float)
        self.Q = np.diag([qT, qH]).astype(float)
        self.R = np.array([[r]], dtype=float)

        self.x = np.array([[init_T],
                           [init_H]], dtype=float)
        self.P = np.diag([init_PT, init_PH]).astype(float)

    def predict(self, u: float) -> None:
        uvec = np.array([[u]], dtype=float)
        self.x = self.A @ self.x + self.B @ uvec
        self.P = self.A @ self.P @ self.A.T + self.Q

    def update(self, y: float) -> None:
        yvec = np.array([[y]], dtype=float)
        S = self.C @ self.P @ self.C.T + self.R
        K = self.P @ self.C.T @ np.linalg.inv(S)
        self.x = self.x + K @ (yvec - self.C @ self.x)
        I = np.eye(self.P.shape[0])
        self.P = (I - K @ self.C) @ self.P

    def predict_horizon(self, u: float, steps: int) -> Tuple[float, float]:
        x = self.x.copy()
        P = self.P.copy()
        uvec = np.array([[u]], dtype=float)

        for _ in range(steps):
            x = self.A @ x + self.B @ uvec
            P = self.A @ P @ self.A.T + self.Q

        return float(x[0, 0]), float(P[0, 0])


# =========================
# Margins
# =========================

class FixedMargin:
    def __init__(self, fixed_margin: float):
        self.fixed_margin = fixed_margin

    def margin(self) -> float:
        return self.fixed_margin


class SakamotoMargin:
    """
    温度版ベースライン:
    e_t = T_obs - T_pred
    sigma_t = std(error window)
    M_t = beta(sigma_t) * sigma_t
    """
    def __init__(self, window: int, fallback_margin: float, min_margin: float, max_margin: float):
        self.errors: Deque[float] = deque(maxlen=window)
        self.fallback_margin = fallback_margin
        self.min_margin = min_margin
        self.max_margin = max_margin

    def update_error(self, error: float) -> None:
        self.errors.append(error)

    def margin(self) -> float:
        if len(self.errors) < 2:
            return self.fallback_margin

        arr = np.array(self.errors, dtype=float)
        sigma = float(np.std(arr, ddof=1))

        if sigma < 1.0:
            beta = 4.0
        elif sigma <= 10.0:
            beta = 77.0 / 18.0 - 5.0 / 18.0 * sigma
        else:
            beta = 1.5

        m = beta * sigma
        return min(self.max_margin, max(self.min_margin, m))


class ProposedMargin:
    """
    M_t = alpha * sqrt(P_T)
    """
    def __init__(self, alpha: float, min_margin: float, max_margin: float):
        self.alpha = alpha
        self.min_margin = min_margin
        self.max_margin = max_margin

    def margin(self, P_T: float) -> float:
        m = self.alpha * math.sqrt(max(P_T, 0.0))
        return min(self.max_margin, max(self.min_margin, m))


# =========================
# Stats
# =========================

@dataclass
class Stats:
    method: str
    control_count: int = 0
    resume_count: int = 0
    margin_sum: float = 0.0
    margin_samples: int = 0
    max_margin: float = 0.0
    violate_count: int = 0
    violate_time_s: float = 0.0

    @property
    def mean_margin(self) -> float:
        return self.margin_sum / self.margin_samples if self.margin_samples else 0.0

    def update_margin(self, margin: float) -> None:
        self.margin_sum += margin
        self.margin_samples += 1
        self.max_margin = max(self.max_margin, margin)


# =========================
# Main
# =========================

def main() -> int:
    parser = argparse.ArgumentParser(description="Master-node thermal controller")

    parser.add_argument("--method", choices=["fixed", "sakamoto", "proposed"], required=True)

    parser.add_argument("--raspi1-host", required=True)
    parser.add_argument("--raspi1-user", default="ubuntu")
    parser.add_argument("--raspi2-host", required=True)
    parser.add_argument("--raspi2-user", default="ubuntu")

    parser.add_argument("--duration", type=float, default=600.0)
    parser.add_argument("--sample-period", type=float, default=1.0)
    parser.add_argument("--horizon", type=float, default=30.0)
    parser.add_argument("--tlimit", type=float, default=80.0)
    parser.add_argument("--tlow", type=float, default=72.0)

    parser.add_argument("--cpu-workers", type=int, default=4)
    parser.add_argument("--cpu-load", type=int, default=50)
    parser.add_argument("--u-base", type=float, default=50.0)
    parser.add_argument("--pidfile", default="/tmp/stress_master_control.pid")

    parser.add_argument("--a", type=float, default=0.91)
    parser.add_argument("--b", type=float, default=-1.65)
    parser.add_argument("--c", type=float, default=0.026)
    parser.add_argument("--d", type=float, default=6.28)

    parser.add_argument("--fixed-margin", type=float, default=1.995)

    parser.add_argument("--error-window", type=int, default=30)
    parser.add_argument("--min-margin", type=float, default=0.0)
    parser.add_argument("--max-margin", type=float, default=10.0)

    parser.add_argument("--qT", type=float, default=0.05)
    parser.add_argument("--qH", type=float, default=0.02)
    parser.add_argument("--r", type=float, default=0.25)
    parser.add_argument("--alpha", type=float, default=2.0)
    parser.add_argument("--init-H", type=float, default=0.0)
    parser.add_argument("--init-PT", type=float, default=1.0)
    parser.add_argument("--init-PH", type=float, default=1.0)

    parser.add_argument("--csv-log", default="control_log.csv")
    parser.add_argument("--summary-csv", default="control_summary.csv")

    args = parser.parse_args()

    ensure_parent_dir(args.csv_log)
    ensure_parent_dir(args.summary_csv)

    T1_init = get_pi_temp_c(args.raspi1_host, args.raspi1_user)
    T2_init = get_pi_temp_c(args.raspi2_host, args.raspi2_user)

    scalar_predictor = ScalarPredictor(
        ScalarModelParams(a=args.a, b=args.b, c=args.c, d=args.d)
    )

    kf = KalmanThermalPredictor(
        a=args.a, b=args.b, c=args.c,
        qT=args.qT, qH=args.qH, r=args.r,
        init_T=T1_init, init_H=args.init_H,
        init_PT=args.init_PT, init_PH=args.init_PH,
    )

    fixed_margin_calc = FixedMargin(args.fixed_margin)
    sakamoto_margin_calc = SakamotoMargin(
        window=args.error-window if False else args.error_window,
        fallback_margin=args.fixed_margin,
        min_margin=args.min_margin,
        max_margin=args.max_margin,
    )
    proposed_margin_calc = ProposedMargin(
        alpha=args.alpha,
        min_margin=args.min_margin,
        max_margin=args.max_margin,
    )

    stats = Stats(method=args.method)
    running = False
    prev_violate = False

    steps = max(1, int(round(args.horizon / args.sample_period)))

    log_exists = os.path.exists(args.csv_log)
    with open(args.csv_log, "a", newline="") as f_log:
        writer = csv.writer(f_log)
        if not log_exists:
            writer.writerow([
                "timestamp",
                "elapsed_s",
                "temp1_c",
                "temp2_c",
                "u_t",
                "pred_c",
                "margin_c",
                "pred_plus_margin_c",
                "running",
                "event",
                "method",
            ])

        start_time = time.time()

        try:
            start_stress(args.raspi1_host, args.raspi1_user, args.cpu_workers, args.cpu_load, args.pidfile)
            running = True
            print(f"[start] method={args.method}")

            while True:
                now = time.time()
                elapsed = now - start_time
                if elapsed > args.duration:
                    break

                T1 = get_pi_temp_c(args.raspi1_host, args.raspi1_user)
                T2 = get_pi_temp_c(args.raspi2_host, args.raspi2_user)
                u_t = args.u_base if running else 0.0
                event = "NONE"

                if args.method in ("fixed", "sakamoto"):
                    pred = scalar_predictor.predict_horizon(T1, u_t, T2, steps)
                    one_step_pred = scalar_predictor.predict_one_step(T1, u_t, T2)
                    err = T1 - one_step_pred

                    if args.method == "fixed":
                        margin = fixed_margin_calc.margin()
                    else:
                        sakamoto_margin_calc.update_error(err)
                        margin = sakamoto_margin_calc.margin()
                else:
                    kf.predict(u_t)
                    kf.update(T1)
                    pred, P_T = kf.predict_horizon(u_t, steps)
                    margin = proposed_margin_calc.margin(P_T)

                pred_plus_margin = pred + margin
                stats.update_margin(margin)

                if running and (pred_plus_margin >= args.tlimit):
                    stop_stress(args.raspi1_host, args.raspi1_user, args.pidfile)
                    running = False
                    stats.control_count += 1
                    event = "STOP"

                elif (not running) and (T1 <= args.tlow):
                    start_stress(args.raspi1_host, args.raspi1_user, args.cpu_workers, args.cpu_load, args.pidfile)
                    running = True
                    stats.resume_count += 1
                    event = "RESUME"

                is_violate = T1 >= args.tlimit
                if is_violate:
                    stats.violate_time_s += args.sample_period
                if is_violate and not prev_violate:
                    stats.violate_count += 1
                prev_violate = is_violate

                print(
                    f"[loop] t={elapsed:.1f}s "
                    f"T1={T1:.2f} T2={T2:.2f} u={u_t:.1f} "
                    f"pred={pred:.2f} margin={margin:.2f} "
                    f"pred+margin={pred_plus_margin:.2f} "
                    f"running={running} event={event}"
                )

                writer.writerow([
                    f"{now:.3f}",
                    f"{elapsed:.3f}",
                    f"{T1:.3f}",
                    f"{T2:.3f}",
                    f"{u_t:.3f}",
                    f"{pred:.3f}",
                    f"{margin:.3f}",
                    f"{pred_plus_margin:.3f}",
                    int(running),
                    event,
                    args.method,
                ])
                f_log.flush()

                time.sleep(args.sample_period)

        except KeyboardInterrupt:
            print("\n[info] interrupted by user")
        finally:
            stop_stress(args.raspi1_host, args.raspi1_user, args.pidfile)

    summary_exists = os.path.exists(args.summary_csv)
    with open(args.summary_csv, "a", newline="") as f_sum:
        fieldnames = [
            "method",
            "control_count",
            "resume_count",
            "mean_margin",
            "max_margin",
            "violate_count",
            "violate_time_s",
        ]
        writer = csv.DictWriter(f_sum, fieldnames=fieldnames)
        if not summary_exists:
            writer.writeheader()

        writer.writerow({
            "method": stats.method,
            "control_count": stats.control_count,
            "resume_count": stats.resume_count,
            "mean_margin": f"{stats.mean_margin:.6f}",
            "max_margin": f"{stats.max_margin:.6f}",
            "violate_count": stats.violate_count,
            "violate_time_s": f"{stats.violate_time_s:.3f}",
        })

    print("\n=== summary ===")
    print(f"method         : {stats.method}")
    print(f"control_count  : {stats.control_count}")
    print(f"resume_count   : {stats.resume_count}")
    print(f"mean_margin    : {stats.mean_margin:.6f}")
    print(f"max_margin     : {stats.max_margin:.6f}")
    print(f"violate_count  : {stats.violate_count}")
    print(f"violate_time_s : {stats.violate_time_s:.3f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())