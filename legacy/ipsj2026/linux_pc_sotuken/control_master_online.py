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
from typing import Deque


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
            "-o", "StrictHostKeyChecking=accept-new",
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

def predict_k_steps_self_only(T0: float, u: float, a0: float, b0: float, d0: float, steps: int) -> float:
    Tk = float(T0)
    for _ in range(steps):
        Tk = a0 * Tk + b0 * u + d0
    return Tk


def predict_k_steps_with_neighbor(
    T0: float, u: float, z: float,
    a1: float, b1: float, c1: float, d1: float,
    steps: int
) -> float:
    Tk = float(T0)
    for _ in range(steps):
        Tk = a1 * Tk + b1 * u + c1 * z + d1
    return Tk


# =========================
# Rolling helpers
# =========================

class RollingWindow:
    def __init__(self, maxlen: int):
        self.data: Deque[float] = deque(maxlen=maxlen)

    def append(self, x: float) -> None:
        self.data.append(float(x))

    def mean(self) -> float:
        if len(self.data) == 0:
            return 0.0
        return sum(self.data) / len(self.data)

    def std(self) -> float:
        n = len(self.data)
        if n < 2:
            return 0.0
        mu = self.mean()
        var = sum((x - mu) ** 2 for x in self.data) / (n - 1)
        return math.sqrt(max(var, 0.0))

    def __len__(self) -> int:
        return len(self.data)


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
    parser = argparse.ArgumentParser(description="Online control aligned with predict_rc.py (raspi1 always ON, raspi2 only middle 10 min)")

    parser.add_argument("--method", choices=["fixed", "sakamoto", "proposed"], required=True)

    parser.add_argument("--raspi1-host", required=True)
    parser.add_argument("--raspi1-user", default="ubuntu")
    parser.add_argument("--raspi2-host", required=True)
    parser.add_argument("--raspi2-user", default="ubuntu")

    # 5,10,5
    parser.add_argument("--pre-idle", type=float, default=300.0, help="前半区間[s]")
    parser.add_argument("--control-duration", type=float, default=600.0, help="中央制御区間[s]")
    parser.add_argument("--post-idle", type=float, default=300.0, help="後半区間[s]")

    parser.add_argument("--sample-period", type=float, default=1.0)
    parser.add_argument("--horizon", type=float, default=30.0)
    parser.add_argument("--tlimit", type=float, default=80.0)
    parser.add_argument("--tlow", type=float, default=72.0)

    parser.add_argument("--cpu-workers", type=int, default=4)
    parser.add_argument("--cpu-load", type=int, default=50)
    parser.add_argument("--u-base", type=float, default=0.5, help="0〜1に正規化した負荷")
    parser.add_argument("--pidfile", default="/tmp/stress_master_control.pid")
    parser.add_argument("--neighbor-pidfile", default="/tmp/stress_neighbor_control.pid")

    # self-only coefficients
    parser.add_argument("--a0", type=float, required=True)
    parser.add_argument("--b0", type=float, required=True)
    parser.add_argument("--d0", type=float, required=True)

    # neighbor coefficients
    parser.add_argument("--a1", type=float, required=True)
    parser.add_argument("--b1", type=float, required=True)
    parser.add_argument("--c1", type=float, required=True)
    parser.add_argument("--d1", type=float, required=True)

    parser.add_argument("--fixed-margin", type=float, default=2.361)
    parser.add_argument("--k-sakamoto", type=float, default=1.0)
    parser.add_argument("--alpha", type=float, default=2.0)
    parser.add_argument("--err-window-s", type=float, default=60.0)
    parser.add_argument("--decay", type=float, default=0.95)

    parser.add_argument("--csv-log", default="control_log.csv")
    parser.add_argument("--summary-csv", default="control_summary.csv")

    args = parser.parse_args()

    ensure_parent_dir(args.csv_log)
    ensure_parent_dir(args.summary_csv)

    dt = args.sample_period
    steps = max(1, int(round(args.horizon / dt)))
    err_window = max(3, int(round(args.err_window_s / dt)))

    err_hist = RollingWindow(err_window)
    z_hist = RollingWindow(err_window)

    stats = Stats(method=args.method)
    running = False
    neighbor_running = False
    prev_violate = False
    z_std_smoothed = 0.0
    prev_phase = None

    log_exists = os.path.exists(args.csv_log)
    with open(args.csv_log, "a", newline="") as f_log:
        writer = csv.writer(f_log)
        if not log_exists:
            writer.writerow([
                "timestamp",
                "elapsed_s",
                "phase",
                "temp1_c",
                "temp2_c",
                "u_t",
                "pred_self_c",
                "pred_sakamoto_c",
                "pred_proposed_c",
                "pred_used_c",
                "margin_c",
                "pred_plus_margin_c",
                "running",
                "neighbor_running",
                "event",
                "method",
            ])

        start_time = time.time()
        pre_end = args.pre_idle
        control_end = args.pre_idle + args.control_duration
        total_end = args.pre_idle + args.control_duration + args.post_idle

        try:
            # 初期化
            stop_stress(args.raspi1_host, args.raspi1_user, args.pidfile)
            stop_stress(args.raspi2_host, args.raspi2_user, args.neighbor_pidfile)

            # raspi1 は最初から常時ON
            start_stress(args.raspi1_host, args.raspi1_user, args.cpu_workers, args.cpu_load, args.pidfile)
            running = True
            neighbor_running = False

            print(f"[start] method={args.method}")

            while True:
                now = time.time()
                elapsed = now - start_time
                if elapsed > total_end:
                    break

                if elapsed < pre_end:
                    phase = "pre"
                elif elapsed < control_end:
                    phase = "control"
                else:
                    phase = "post"

                # control開始時に履歴リセット
                if phase == "control" and prev_phase != "control":
                    z_hist = RollingWindow(err_window)
                    z_std_smoothed = 0.0

                # -------------------------
                # phase control
                # -------------------------
                if phase == "pre":
                    # raspi1 ON, raspi2 OFF
                    if not running:
                        start_stress(
                            args.raspi1_host, args.raspi1_user,
                            args.cpu_workers, args.cpu_load,
                            args.pidfile
                        )
                        running = True

                    if neighbor_running:
                        stop_stress(args.raspi2_host, args.raspi2_user, args.neighbor_pidfile)
                        neighbor_running = False

                elif phase == "control":
                    # raspi1 は制御対象、raspi2 ON
                    if not neighbor_running:
                        start_stress(
                            args.raspi2_host, args.raspi2_user,
                            args.cpu_workers, args.cpu_load,
                            args.neighbor_pidfile
                        )
                        neighbor_running = True

                else:  # post
                    # raspi1 ON, raspi2 OFF
                    if not running:
                        start_stress(
                            args.raspi1_host, args.raspi1_user,
                            args.cpu_workers, args.cpu_load,
                            args.pidfile
                        )
                        running = True

                    if neighbor_running:
                        stop_stress(args.raspi2_host, args.raspi2_user, args.neighbor_pidfile)
                        neighbor_running = False

                # 観測
                T1 = get_pi_temp_c(args.raspi1_host, args.raspi1_user)
                T2 = get_pi_temp_c(args.raspi2_host, args.raspi2_user)
                u_t = args.u_base if running else 0.0
                event = "NONE"

                # self-only prediction
                pred_self = predict_k_steps_self_only(T1, u_t, args.a0, args.b0, args.d0, steps)

                # 1-step error update for self-only
                pred_self_1step = predict_k_steps_self_only(T1, u_t, args.a0, args.b0, args.d0, 1)
                err_self = T1 - pred_self_1step
                err_hist.append(err_self)

                # sakamoto-like corrected prediction
                past_mean_err = err_hist.mean() if len(err_hist) >= 3 else 0.0
                pred_sakamoto = pred_self + args.k_sakamoto * past_mean_err

                # proposed prediction
                pred_proposed = predict_k_steps_with_neighbor(
                    T1, u_t, T2, args.a1, args.b1, args.c1, args.d1, steps
                )

                # margins
                margin_fixed = args.fixed_margin

                err_std = err_hist.std() if len(err_hist) >= 3 else 0.0
                margin_sakamoto = max(0.0, 2.0 * err_std)

                if phase == "control":
                    z_hist.append(T2)
                z_std = z_hist.std() if len(z_hist) >= 3 else 0.0
                z_std_smoothed = max(z_std, args.decay * z_std_smoothed)
                margin_proposed = max(0.0, args.alpha * z_std_smoothed)

                if args.method == "fixed":
                    pred_used = pred_self
                    margin = margin_fixed
                elif args.method == "sakamoto":
                    pred_used = pred_sakamoto
                    margin = margin_sakamoto
                else:
                    pred_used = pred_proposed
                    margin = margin_proposed

                pred_plus_margin = pred_used + margin

                # control / summary は中央10分だけ
                if phase == "control":
                    stats.update_margin(margin)

                    if running and (pred_plus_margin >= args.tlimit):
                        stop_stress(args.raspi1_host, args.raspi1_user, args.pidfile)
                        running = False
                        stats.control_count += 1
                        event = "STOP"

                    elif (not running) and (T1 <= args.tlow):
                        start_stress(
                            args.raspi1_host, args.raspi1_user,
                            args.cpu_workers, args.cpu_load,
                            args.pidfile
                        )
                        running = True
                        stats.resume_count += 1
                        event = "RESUME"

                # violation も中央10分だけ
                is_violate = (phase == "control") and (T1 > args.tlimit)
                if is_violate:
                    stats.violate_time_s += args.sample_period
                if is_violate and not prev_violate:
                    stats.violate_count += 1
                prev_violate = is_violate

                print(
                    f"[loop] phase={phase} t={elapsed:.1f}s "
                    f"T1={T1:.2f} T2={T2:.2f} u={u_t:.2f} "
                    f"pred_self={pred_self:.2f} pred_saka={pred_sakamoto:.2f} pred_prop={pred_proposed:.2f} "
                    f"pred_used={pred_used:.2f} margin={margin:.2f} "
                    f"pred+margin={pred_plus_margin:.2f} "
                    f"running={running} neighbor={neighbor_running} event={event}"
                )

                writer.writerow([
                    f"{now:.3f}",
                    f"{elapsed:.3f}",
                    phase,
                    f"{T1:.3f}",
                    f"{T2:.3f}",
                    f"{u_t:.3f}",
                    f"{pred_self:.3f}",
                    f"{pred_sakamoto:.3f}",
                    f"{pred_proposed:.3f}",
                    f"{pred_used:.3f}",
                    f"{margin:.3f}",
                    f"{pred_plus_margin:.3f}",
                    int(running),
                    int(neighbor_running),
                    event,
                    args.method,
                ])
                f_log.flush()

                prev_phase = phase
                time.sleep(args.sample_period)

        except KeyboardInterrupt:
            print("\n[info] interrupted by user")
        finally:
            stop_stress(args.raspi1_host, args.raspi1_user, args.pidfile)
            stop_stress(args.raspi2_host, args.raspi2_user, args.neighbor_pidfile)

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