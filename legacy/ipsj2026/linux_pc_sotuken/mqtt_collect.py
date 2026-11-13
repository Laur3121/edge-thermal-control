import json, csv
from paho.mqtt.client import Client
from paho.mqtt.enums import CallbackAPIVersion

BROKER = "localhost"
TOPIC = "cluster/+/metrics"

out = open("output/metrics_log_stress2.csv", "a", newline="")
w = csv.writer(out)
if out.tell() == 0:
    w.writerow(["ts","iso","host","temp","cpu_percent","mem_percent","loadavg_1m","loadavg_5m","loadavg_15m"])

def pick_load(d):
    # 新形式: loadavg_1m / 5m / 15m
    if "loadavg_1m" in d:
        return (
            d.get("loadavg_1m", ""),
            d.get("loadavg_5m", ""),
            d.get("loadavg_15m", ""),
        )
    # 旧形式: loadavg（単一）
    if "loadavg" in d:
        return (d.get("loadavg", ""), "", "")
    return ("", "", "")

def on_message(client, userdata, msg):
    try:
        d = json.loads(msg.payload.decode())

        ts = d.get("time", "")
        iso = d.get("iso", "")
        host = d.get("host", "")
        temp = d.get("temp", "")
        cpu = d.get("cpu_percent", "")
        mem = d.get("mem_percent", "")

        la1, la5, la15 = pick_load(d)

        w.writerow([ts, iso, host, temp, cpu, mem, la1, la5, la15])
        out.flush()

        # 表示も一応
        print(msg.topic, {"host": host, "temp": temp, "cpu": cpu, "mem": mem, "la1": la1})
    except Exception as e:
        print("parse error:", e, msg.payload)

c = Client(CallbackAPIVersion.VERSION1)
c.on_message = on_message
c.connect(BROKER, 1883, 60)
c.subscribe(TOPIC)
c.loop_forever()
