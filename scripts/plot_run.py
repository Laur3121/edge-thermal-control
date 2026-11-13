#!/usr/bin/env python3
"""1回の実験(experiments/<dir>)の時系列を図にし、段階ごとの温度の要約を出す。

出力:<dir>/results/timeseries.png、<dir>/results/phase_summary.csv
段階ごとの要約:各ノードの開始時温度・終了時温度・最高温度・平均 CPU 使用率・ファン ON 割合。
開始時・終了時の温度は、量子化(約0.5℃刻み)の影響を減らすため、境界の前後 window 秒の平均。

例:python scripts/plot_run.py experiments/20261113_openair_interference
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


def load_run(d: Path):
    tel = pd.read_csv(d / "raw" / "telemetry.csv")
    ev = pd.read_csv(d / "events.csv")
    cfg = json.loads((d / "config.json").read_text())
    roles = {h: r for r, h in cfg["nodes"].items()}
    return tel, ev, roles


def phases(ev: pd.DataFrame) -> list[tuple[str, float, float]]:
    st = ev[ev.event == "phase_start"][["phase", "ts"]].to_numpy()
    en = ev[ev.event.isin(["phase_end", "aborted"])][["phase", "ts"]].to_numpy()
    ends = {p: t for p, t in en}
    return [(p, t, ends.get(p, t)) for p, t in st]


def summarize(tel, ev, roles, window: float = 30.0) -> pd.DataFrame:
    rows = []
    for name, t0, t1 in phases(ev):
        for host, g in tel.groupby("host"):
            seg = g[(g.ts >= t0) & (g.ts < t1)]
            if seg.empty:
                continue
            start = g[(g.ts >= t0 - window) & (g.ts < t0)].temp.mean()
            end = g[(g.ts >= t1 - window) & (g.ts < t1)].temp.mean()
            rows.append({"phase": name, "host": host, "role": roles.get(host, ""),
                         "duration_s": round(t1 - t0), "T_start": start, "T_end": end,
                         "dT": end - start, "T_max": seg.temp.max(), "cpu_mean": seg.cpu.mean(),
                         "fan_on_ratio": seg.fan.mean(), "throttled_any": (seg.throttled != "0x0").any()})
    return pd.DataFrame(rows)


def plot(tel, ev, roles, path: Path, title: str):
    t_ref = ev.ts.min()
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1.3, 1]})
    for host, g in tel.groupby("host"):
        lab = f"{roles.get(host, '?')} ({host})"
        t = (g.ts - t_ref) / 60
        axes[0].plot(t, g.temp.rolling(5, center=True, min_periods=1).mean(), lw=1.2, label=lab)
        axes[1].plot(t, g.cpu, lw=0.8, label=lab)
        axes[2].step(t, g.fan + 0.02 * list(roles).index(host) if host in roles else g.fan, lw=1, label=lab)
    for i, (name, t0, t1) in enumerate(phases(ev)):
        for ax in axes:
            ax.axvspan((t0 - t_ref) / 60, (t1 - t_ref) / 60, color="0.92" if i % 2 else "white", lw=0)
        axes[0].text((t0 - t_ref) / 60, 1.01, name, transform=axes[0].get_xaxis_transform(), fontsize=7)
    axes[0].set_ylabel("CPU temperature [°C]\n(5 s moving avg.)")
    axes[0].legend(fontsize=8)
    axes[0].set_title(title, fontsize=9, pad=14)
    axes[1].set_ylabel("CPU usage [%]")
    axes[2].set_ylabel("Fan [on/off]")
    axes[2].set_yticks([0, 1])
    axes[2].set_xlabel("Time from start [min]")
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    args = ap.parse_args()
    d = Path(args.run_dir)
    tel, ev, roles = load_run(d)
    out = d / "results"
    out.mkdir(exist_ok=True)
    s = summarize(tel, ev, roles)
    s.to_csv(out / "phase_summary.csv", index=False, float_format="%.2f")
    plot(tel, ev, roles, out / "timeseries.png", d.name)
    print(s.drop(columns=["throttled_any"]).to_string(index=False, float_format="%.2f"))


if __name__ == "__main__":
    main()
