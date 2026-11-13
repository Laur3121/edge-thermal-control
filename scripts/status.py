#!/usr/bin/env python3
"""実行中(または直近)の実験の進捗を表示する(収集用 PC で実行)。

表示:今の段階・経過・残り時間の目安、各ノードの最新の温度・CPU・ファン・負荷、室温。
残り時間は「温度が落ち着くまでの待ち」と「until 付きの段階」を最大値で見積もる(実際はもっと早く終わることがある)。

例(Mac から):
  ssh laur@192.168.0.50 'cd ~/edge-thermal-control && ~/sotuken/venv/bin/python scripts/status.py'
  ssh -t laur@192.168.0.50 'cd ~/edge-thermal-control && ~/sotuken/venv/bin/python scripts/status.py --watch'
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiment import expand_phases  # noqa: E402


def latest_run(root: Path) -> Path | None:
    runs = [d for d in root.iterdir() if (d / "events.csv").exists()]
    return max(runs, key=lambda d: (d / "events.csv").stat().st_mtime) if runs else None


def tail_rows(path: Path, n: int = 400) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as fp:
        r = csv.DictReader(fp)
        return list(deque(r, maxlen=n))


def fmt_min(s: float) -> str:
    s = max(0, int(s))
    return f"{s // 60}分{s % 60:02d}秒"


def render(run: Path) -> str:
    cfg = json.loads((run / "config.json").read_text())
    phases = expand_phases(cfg["scenario"]["phases"])
    settle_max = cfg["scenario"].get("settle", {}).get("timeout_s", 1800)
    ev = list(csv.DictReader(open(run / "events.csv", newline="")))
    now = time.time()
    lines = [f"実験: {run.name}  ({cfg['scenario'].get('name', '')})"]

    started = {e["phase"]: float(e["ts"]) for e in ev if e["event"] == "phase_start"}
    finished = {e["phase"] for e in ev if e["event"] in ("phase_end", "aborted")}
    last = ev[-1]["event"] if ev else ""
    t0 = float(ev[0]["ts"]) if ev else now
    if last in ("end", "aborted"):
        lines.append(f"状態: 終了({time.strftime('%H:%M', time.localtime(float(ev[-1]['ts'])))})")
    elif not started:
        settle_t = next((float(e["ts"]) for e in ev if e["event"] == "settle_start"), now)
        rest = sum(p.get("duration_s", p.get("max_s", 0)) for p in phases)
        lines.append(f"状態: 温度が落ち着くのを待っている(経過 {fmt_min(now - settle_t)}、最大 {fmt_min(settle_max)})")
        lines.append(f"残り: 最大 {fmt_min(settle_max - (now - settle_t) + rest)}(待ちが早く終われば短くなる)")
    else:
        idx = max(i for i, p in enumerate(phases) if p["name"] in started)
        cur = phases[idx]
        el = now - started[cur["name"]]
        lim = cur.get("duration_s", cur.get("max_s", 0))
        rest = max(0, lim - el) + sum(p.get("duration_s", p.get("max_s", 0)) for p in phases[idx + 1:])
        until = f"(または {cur['until']} で終了)" if "until" in cur else ""
        lines.append(f"段階: {idx + 1}/{len(phases)}  {cur['name']}  経過 {fmt_min(el)} / {fmt_min(lim)}{until}")
        lines.append(f"残り: 最大 {fmt_min(rest)}  終了見込み {time.strftime('%H:%M', time.localtime(now + rest))} ごろまで"
                     f"  (全体の経過 {fmt_min(now - t0)})")
        done = sum(1 for p in phases if p["name"] in finished)
        bar = int(30 * done / len(phases))
        lines.append("[" + "#" * bar + "-" * (30 - bar) + f"] 完了 {done}/{len(phases)} 段階")

    roles = {h: r for r, h in cfg["nodes"].items()}
    latest = {}
    for row in tail_rows(run / "raw" / "telemetry.csv"):
        latest[row["host"]] = row
    lines.append("")
    lines.append(f"{'ノード':<14}{'温度':>8}{'CPU':>8}{'ファン':>6}{'負荷':>6}{'強制ON':>7}  更新")
    for host in sorted(latest, key=lambda h: roles.get(h, "Z")):
        r = latest[host]
        age = now - float(r["ts"])
        lines.append(f"{roles.get(host, '?') + ' ' + host:<14}{float(r['temp']):>7.1f}℃{float(r['cpu']):>7.1f}%"
                     f"{r['fan']:>6}{r.get('load', ''):>6}{r['failsafe']:>7}  {age:.0f}秒前")
    amb = {}
    for row in tail_rows(run / "raw" / "ambient.csv", 50):
        amb[row["name"].strip()] = row
    if amb:
        lines.append("室温: " + "  ".join(f"{n} {a['temperature']}℃" for n, a in sorted(amb.items())))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", nargs="?", help="実験ディレクトリ(省略時は experiments/ の中で最新のもの)")
    ap.add_argument("--watch", action="store_true", help="5秒ごとに更新し続ける(Ctrl-C で終了)")
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1] / "experiments"
    run = Path(args.run_dir) if args.run_dir else latest_run(root)
    if run is None:
        sys.exit("実験が見つからない")
    while True:
        out = render(run)
        if args.watch:
            os.system("clear")
        print(out)
        if not args.watch:
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
