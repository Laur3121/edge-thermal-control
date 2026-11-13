#!/usr/bin/env python3
import argparse
import json
import time

import paho.mqtt.client as mqtt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--targets", nargs="+", required=True, help="hostnames e.g. raspi1 raspi2")
    ap.add_argument("--action", choices=["start", "stop"], default="start")
    ap.add_argument("--task", default="matrix")
    ap.add_argument("--duration-sec", type=int, default=600)
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--intensity", type=int, default=1)
    ap.add_argument("--max-temp-c", type=float, default=80.0)
    args = ap.parse_args()

    job_id = f"job-{time.strftime('%Y%m%d-%H%M%S')}"
    payload = {
        "action": args.action,
        "job_id": job_id,
    }
    if args.action == "start":
        payload.update({
            "task": args.task,
            "duration_sec": args.duration_sec,
            "size": args.size,
            "intensity": args.intensity,
            "max_temp_c": args.max_temp_c,
        })

    c = mqtt.Client(client_id="controller", clean_session=True)
    c.connect(args.broker, args.port, keepalive=30)

    for host in args.targets:
        topic = f"cluster/{host}/cmd"
        c.publish(topic, json.dumps(payload), qos=1, retain=False)
        print(f"sent to {topic}: {payload}")

    c.disconnect()


if __name__ == "__main__":
    main()
