#!/usr/bin/env python3
"""閉ループ実験の図と指標。

- 図:役割ごとに、実測温度・Δ 秒先予測(ファン OFF のとき)・Tsafe・ファン状態・負荷
- 指標(段階名の先頭 "r<巡>_<条件>_" ごとにまとめる。試運転のように該当しなければ実験全体で 1 つ):
  最高温度、80℃ 超過の秒数、スロットリング(get_throttled の下位ビットが立った秒数)、強制 ON の秒数、
  ファン稼働率(ON の秒数 / 区間の秒数)、ON にした回数

出力:<run>/results/control_timeseries.png、control_metrics.csv
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def segments(ev: pd.DataFrame):
    """(条件のラベル, 開始, 終了) の一覧。休み(_rest)と baseline は除く。"""
    st = ev[ev.event == "phase_start"][["phase", "ts"]].to_numpy()
    end = float(ev[ev.event == "end"].ts.iloc[0]) if (ev.event == "end").any() else float(ev.ts.max())
    groups = {}
    for i, (name, ts) in enumerate(st):
        te = float(st[i + 1][1]) if i + 1 < len(st) else end
        mt = re.match(r"(r\d+_[a-z]+)_s\d+$", name)
        if mt:
            g = groups.setdefault(mt.group(1), [float(ts), te])
            g[1] = te
    if not groups:  # 試運転など
        groups["all"] = [float(st[0][1]), end]
    return [(k, v[0], v[1]) for k, v in groups.items()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--tlimit", type=float, default=80.0)
    args = ap.parse_args()
    d = Path(args.run_dir)
    tel = pd.read_csv(d / "raw" / "telemetry.csv")
    ev = pd.read_csv(d / "events.csv")
    ctl = pd.read_csv(d / "control.csv") if (d / "control.csv").exists() else pd.DataFrame()
    nodes = json.loads((d / "config.json").read_text())["nodes"]
    out = d / "results"
    out.mkdir(exist_ok=True)
    tel["thr_now"] = tel.throttled.astype(str).apply(lambda s: int(s, 16) & 0xF if s.startswith("0x") else 0)

    rows = []
    for label, ts, te in segments(ev):
        cond = label.split("_", 1)[1] if "_" in label else label
        rnd = label.split("_", 1)[0] if "_" in label else ""
        for role, host in nodes.items():
            g = tel[(tel.host == host) & (tel.ts >= ts) & (tel.ts < te)].sort_values("ts")
            if g.empty:
                continue
            dts = np.diff(np.r_[g.ts.to_numpy(), te]).clip(0, 5)  # 各サンプルが代表する秒数
            fan = g.fan.to_numpy()
            rows.append({"round": rnd, "condition": cond, "role": role, "host": host,
                         "duration_s": te - ts, "T_start": g.temp.iloc[0], "T_max": g.temp.max(),
                         "over_limit_s": float(dts[g.temp.to_numpy() > args.tlimit].sum()),
                         "throttle_s": float(dts[g.thr_now.to_numpy() > 0].sum()),
                         "clock_min_MHz": g["clock"].min() / 1e6,
                         "failsafe_s": float(dts[g.failsafe.to_numpy() > 0].sum()),
                         "fan_on_ratio": float((dts * fan).sum() / dts.sum()),
                         "fan_on_count": int(np.sum(np.diff(np.r_[0, fan]) == 1))})
    mt = pd.DataFrame(rows)
    mt.to_csv(out / "control_metrics.csv", index=False, float_format="%.3f")
    if len(mt):
        summ = mt.groupby("condition")[["T_max", "over_limit_s", "throttle_s", "failsafe_s",
                                         "fan_on_ratio", "fan_on_count"]].agg(["mean", "max"])
        summ.to_csv(out / "control_summary.csv", float_format="%.3f")
        print(mt.to_string(index=False, float_format="%.2f"))

    # 図
    t0 = float(ev.ts.min())
    fig, axes = plt.subplots(len(nodes), 1, figsize=(10, 2.6 * len(nodes)), sharex=True, squeeze=False)
    for ax, (role, host) in zip(axes[:, 0], nodes.items()):
        g = tel[tel.host == host]
        tm = (g.ts - t0) / 60
        ax.plot(tm, g.temp, "k-", lw=0.8, label="Measured")
        if len(ctl):
            c = ctl[ctl.role == role]
            tc = (c.ts - t0) / 60
            ax.plot(tc + 0.5, c.pred, "C0-", lw=0.8, label="Predicted 30 s ahead (fan off)")
            ax.plot(tc, c.tsafe, "C1--", lw=0.8, label="Tsafe (threshold: T_on)")
        ax.axhline(args.tlimit, color="r", lw=0.8, label=f"Tlimit = {args.tlimit:.0f} °C")
        ax.set_ylabel(f"{role} ({host})\nTemperature [°C]")
        ax2 = ax.twinx()
        ax2.fill_between(tm, 0, g.fan, step="post", color="C2", alpha=0.25, lw=0)
        ax2.plot(tm, g.load / 4, color="0.5", lw=0.8)
        ax2.set_ylim(0, 4)
        ax2.set_yticks([0, 1])
        ax2.set_ylabel("Fan (green) /\nload ÷ 4 (gray)", fontsize=8)
    axes[0, 0].legend(fontsize=7, loc="lower right", ncol=2)
    axes[-1, 0].set_xlabel("Time from start [min]")
    for label, ts, te in segments(ev):
        for ax in axes[:, 0]:
            ax.axvspan((ts - t0) / 60, (te - t0) / 60, color="0.9", zorder=-1)
        axes[0, 0].text((ts - t0) / 60, axes[0, 0].get_ylim()[1], label, fontsize=6, va="bottom")
    fig.tight_layout()
    fig.savefig(out / "control_timeseries.png", dpi=150)


if __name__ == "__main__":
    main()
