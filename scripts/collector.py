#!/usr/bin/env python3
"""収集用 PC で動かす:全ノードのテレメトリを MQTT で受け取り、実験ディレクトリに CSV で保存する。

保存先:<out>/raw/telemetry.csv(1行 = 1ノードの1秒分。recv_ts は PC 側の受信時刻)
生ログは追記のみで、上書きしない(同じファイルがあれば別名にする)。

例:
  python scripts/collector.py --broker localhost --out experiments/20261114_step_identify
"""

from __future__ import annotations

import argparse
import csv
import json
import signal
import threading
import time
from pathlib import Path

FIELDS = ["recv_ts", "ts", "host", "temp", "cpu", "cpu0", "cpu1", "cpu2", "cpu3", "clock",
          "throttled", "fan", "fan_pwm", "fan_cmd", "failsafe", "load1", "load", "poe_ma"]


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    stem, i = p.stem, 1
    while (p.with_name(f"{stem}_{i}{p.suffix}")).exists():
        i += 1
    return p.with_name(f"{stem}_{i}{p.suffix}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--topic-prefix", default="etc")
    ap.add_argument("--out", required=True, help="実験ディレクトリ")
    args = ap.parse_args()

    import paho.mqtt.client as mqtt

    raw = Path(args.out) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    path = unique_path(raw / "telemetry.csv")
    fp = open(path, "w", newline="")
    w = csv.DictWriter(fp, fieldnames=FIELDS, extrasaction="ignore")
    w.writeheader()
    lock = threading.Lock()
    last_seen: dict[str, float] = {}

    def on_message(client, userdata, msg):
        try:
            row = json.loads(msg.payload)
        except json.JSONDecodeError:
            return
        row["recv_ts"] = round(time.time(), 3)
        with lock:
            w.writerow(row)
            fp.flush()
            last_seen[row.get("host", "?")] = row["recv_ts"]

    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="etc-collector")
    except AttributeError:
        c = mqtt.Client(client_id="etc-collector")
    c.on_connect = lambda client, *a: client.subscribe(f"{args.topic_prefix}/+/telemetry", qos=0)
    c.on_message = on_message
    c.connect(args.broker, args.port, keepalive=30)
    c.loop_start()

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    print(f"logging to {path}")
    while not stop.wait(10):
        now = time.time()
        status = " ".join(f"{h}:{now - t:.0f}s" for h, t in sorted(last_seen.items()))
        print(f"[{time.strftime('%H:%M:%S')}] last seen  {status or '(none)'}")
    c.loop_stop()
    fp.close()


if __name__ == "__main__":
    main()
