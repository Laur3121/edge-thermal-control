#!/usr/bin/env python3
"""段ボールの実験の見張り(収集用 PC で run_experiment.py と並べて動かす)。

箱の中の温度計(既定:防水温湿度計 1〜3)のどれかが上限を超えたら、run_experiment.py に SIGINT を送って止める。
止めると run_experiment.py は各ノードの etc-agent を止めるので、負荷が止まり、ファンは OS の自動制御に戻る。
記録:<exp>/box_watchdog.log(追記のみ)

  python scripts/box_watchdog.py --exp experiments/20261125_pattern_box --limit 50
"""

import argparse
import csv
import os
import re
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path


def latest_by_name(path: Path, pattern: str) -> dict[str, tuple[float, float]]:
    """ambient.csv から、名前が pattern に合う温度計ごとの最新の (ts, 温度)。"""
    out = {}
    if not path.exists():
        return out
    with open(path, newline="") as fp:
        for row in csv.DictReader(fp):
            if re.search(pattern, row.get("name") or "") and row.get("temperature"):
                out[row["name"]] = (float(row["ts"]), float(row["temperature"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True, help="実験フォルダ(raw/ambient.csv を読む)")
    ap.add_argument("--limit", type=float, default=50.0, help="箱の中の上限 [℃]")
    ap.add_argument("--inside", default="防水温湿度計 [123]", help="箱の中の温度計の名前(正規表現)")
    ap.add_argument("--interval", type=float, default=30.0)
    args = ap.parse_args()
    exp = Path(args.exp)
    log = open(exp / "box_watchdog.log", "a")

    def say(msg):
        line = f"{datetime.now():%F %T} {msg}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    say(f"start limit={args.limit} inside={args.inside!r}")
    while True:
        pids = subprocess.run(["pgrep", "-f", f"run_experiment.py.*--out {args.exp}"],
                              capture_output=True, text=True).stdout.split()
        if not pids:
            say("run_experiment.py が動いていないので終了")
            return
        temps = latest_by_name(exp / "raw" / "ambient.csv", args.inside)
        hot = {n: t for n, (_, t) in temps.items() if t > args.limit}
        if hot:
            say(f"上限超え {hot} → run_experiment.py(pid {pids})に SIGINT")
            for p in pids:
                os.kill(int(p), signal.SIGINT)
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
