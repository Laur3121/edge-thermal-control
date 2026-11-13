#!/usr/bin/env python3
"""SwitchBot 温湿度計の値を SwitchBot Web API(v1.1)から定期的に取得して CSV に残す(収集用 PC で実行)。

認証情報はリポジトリ直下の .env(git に入らない)から読む:
  SWITCHBOT_TOKEN=...
  SWITCHBOT_SECRET=...
温湿度計は Hub 経由で「クラウドサービス」を ON にしておくこと。

保存先:<out>/raw/ambient.csv(ts, device_id, name, temperature[℃], humidity[%])。追記のみ。
API の上限は 1日 10,000 回。既定の 60 秒間隔・2台なら 1日 2,880 回。

例:
  python scripts/ambient_logger.py --list                       # 登録済みの温湿度計を表示
  python scripts/ambient_logger.py --out experiments/20261114_step_identify
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import re
import signal
import threading
import time
import urllib.request
import uuid
from pathlib import Path

API = "https://api.switch-bot.com/v1.1"
METER_TYPES = {"Meter", "MeterPlus", "Meter Plus (JP)", "WoIOSensor", "Hub 2", "MeterPro", "MeterPro(CO2)"}
FIELDS = ["ts", "device_id", "name", "temperature", "humidity"]


def load_env(path: Path) -> dict[str, str]:
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def auth_headers(token: str, secret: str, t_ms: int | None = None, nonce: str | None = None) -> dict:
    """SwitchBot API v1.1 の署名ヘッダ。sign = base64(HMAC-SHA256(secret, token + t + nonce))。"""
    t = str(t_ms if t_ms is not None else int(time.time() * 1000))
    nonce = nonce or str(uuid.uuid4())
    sign = base64.b64encode(hmac.new(secret.encode(), (token + t + nonce).encode(),
                                     hashlib.sha256).digest()).decode()
    return {"Authorization": token, "sign": sign, "t": t, "nonce": nonce,
            "Content-Type": "application/json; charset=utf8"}


def get(path: str, token: str, secret: str) -> dict:
    req = urllib.request.Request(API + path, headers=auth_headers(token, secret))
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.loads(r.read())
    if body.get("statusCode") != 100:
        raise RuntimeError(f"SwitchBot API error: {body}")
    return body["body"]


def list_meters(token: str, secret: str) -> list[dict]:
    devs = get("/devices", token, secret).get("deviceList", [])
    return [d for d in devs if d.get("deviceType") in METER_TYPES]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="実験ディレクトリ")
    ap.add_argument("--interval", type=float, default=60.0, help="取得間隔 [s]")
    ap.add_argument("--env", default=str(Path(__file__).resolve().parents[1] / ".env"))
    ap.add_argument("--list", action="store_true", help="温湿度計の一覧を表示して終わる")
    ap.add_argument("--name-filter", default="防水温湿度計 [0-9]|ハブ",
                    help="記録する機器名の正規表現(既定:防水温湿度計 1〜3 とハブ。自宅用などは除く)")
    args = ap.parse_args()

    env = {**load_env(Path(args.env)), **os.environ}
    token, secret = env.get("SWITCHBOT_TOKEN"), env.get("SWITCHBOT_SECRET")
    if not token or not secret:
        raise SystemExit(f"SWITCHBOT_TOKEN / SWITCHBOT_SECRET が {args.env} にない")

    meters = list_meters(token, secret)
    if not args.list:
        meters = [d for d in meters if re.search(args.name_filter, d.get("deviceName", ""))]
    if args.list or not args.out:
        for d in meters:
            print(d["deviceId"], d.get("deviceName"), d.get("deviceType"), "hub=" + str(d.get("hubDeviceId")))
        if not meters:
            print("温湿度計が見つからない(クラウドサービスが OFF か、Hub に紐づいていない)")
        return

    raw = Path(args.out) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    path = raw / "ambient.csv"
    new = not path.exists()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    with open(path, "a", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=FIELDS)
        if new:
            w.writeheader()
        print(f"logging {len(meters)} meters to {path}")
        while not stop.is_set():
            for d in meters:
                try:
                    st = get(f"/devices/{d['deviceId']}/status", token, secret)
                    w.writerow({"ts": round(time.time(), 1), "device_id": d["deviceId"],
                                "name": d.get("deviceName"), "temperature": st.get("temperature"),
                                "humidity": st.get("humidity")})
                    fp.flush()
                except Exception as e:  # 一時的な通信エラーで止めない
                    print(f"[{time.strftime('%H:%M:%S')}] {d.get('deviceName')}: {e}")
            stop.wait(args.interval)


if __name__ == "__main__":
    main()
