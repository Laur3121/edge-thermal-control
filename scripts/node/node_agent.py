#!/usr/bin/env python3
"""各 Raspberry Pi で動かす計測・ファン駆動エージェント(1ファイルで完結。RasPi に scp して使う)。

1秒ごとに次を測って MQTT に送り、手元の CSV にも残す:
  ts        UNIX 秒(NTP/chrony で同期しておくこと)
  temp      CPU 温度 [℃](/sys/class/thermal/thermal_zone0/temp)
  cpu       CPU 使用率 [%]。前回の計測からの平均(/proc/stat の差分)。瞬時値ではない
  cpu0..3   コアごとの使用率 [%](同上)
  clock     ARM クロック [Hz](vcgencmd measure_clock arm。スロットリングで下がる)
  throttled vcgencmd get_throttled の値(16進文字列。0x0 なら問題なし)
  fan       ファンの状態(0/1)
  fan_pwm   ファンの実際の PWM 値(0〜255、PoE+ HAT のとき。読めなければ空)
  poe_ma    PoE+ HAT の電流 [mA](hwmon rpi_poe の curr1_input。USB-C 給電なら 0)
  fan_cmd   最後に受けた指令(0/1、指令なしは -1)
  failsafe  強制 ON 中なら 1
  load1     1分平均ロードアベレージ
  load      動かしている stress-ng の CPU ワーカー数(0 = 負荷なし)

負荷:etc/<host>/load/set に整数 N を送ると `stress-ng --cpu N` を起動する(0 で停止。前の負荷は止めてから切り替え)。
実験スクリプト(scripts/run_experiment.py)が負荷とファンを時刻どおりに切り替えるのに使う。

ファン:MQTT の etc/<host>/fan/set に "0"/"1" を送ると切り替わる。
  --fan-mode poe(既定):Raspberry Pi PoE+ HAT のファン。Linux の冷却デバイス(type=pwm-fan)の cur_state を書く。
      OS の自動制御(thermal_zone0 の step_wise。40℃ から回り始める)を止めるため、起動時に policy を user_space にし、
      終了時に元に戻す。**root 権限が必要**(sudo で起動するか systemd サービスにする。install_node.sh 参照)
  --fan-mode gpio:公式ケースファン(制御線を GPIO14)。--fan-mode none:ファンを触らない
安全のため、温度が --failsafe-temp 以上、または --cmd-timeout 秒以上指令がないとき(指令を1回でも受けた後)は強制 ON。

使い方(RasPi 上):
  sudo apt install python3-paho-mqtt python3-gpiozero   # 未導入なら
  python3 node_agent.py --broker 192.168.x.x --log-dir ~/etc_logs
  python3 node_agent.py --no-mqtt --fan-mode none       # 計測だけ試す(root 不要)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

FIELDS = ["ts", "host", "temp", "cpu", "cpu0", "cpu1", "cpu2", "cpu3", "clock",
          "throttled", "fan", "fan_pwm", "fan_cmd", "failsafe", "load1", "load", "poe_ma"]


# ---------- 計測(純粋関数はテストできるように分けてある) ----------

def parse_proc_stat(text: str) -> dict[str, tuple[int, int]]:
    """/proc/stat の cpu 行を {名前: (busy, total)} にする。idle と iowait を非稼働とみなす。"""
    out = {}
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        vals = [int(v) for v in parts[1:9]]  # user nice system idle iowait irq softirq steal
        idle = vals[3] + vals[4]
        total = sum(vals)
        out[parts[0]] = (total - idle, total)
    return out


def cpu_usage(prev: dict, cur: dict) -> dict[str, float]:
    """2回分の parse_proc_stat から、その間の平均使用率 [%] を返す。"""
    usage = {}
    for name, (busy, total) in cur.items():
        if name not in prev:
            continue
        db, dt = busy - prev[name][0], total - prev[name][1]
        usage[name] = 100.0 * db / dt if dt > 0 else 0.0
    return usage


def parse_clock(text: str) -> int | None:
    """'frequency(48)=1500398464' → 1500398464"""
    try:
        return int(text.strip().split("=")[1])
    except (IndexError, ValueError):
        return None


def parse_throttled(text: str) -> str | None:
    """'throttled=0x50000' → '0x50000'"""
    try:
        return text.strip().split("=")[1]
    except IndexError:
        return None


def read_temp() -> float:
    return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0


def vcgencmd(*args: str) -> str:
    try:
        return subprocess.run(["vcgencmd", *args], capture_output=True, text=True, timeout=1).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def find_hwmon(name: str, root: str = "/sys/class/hwmon") -> Path | None:
    for d in sorted(Path(root).glob("hwmon*")):
        try:
            if (d / "name").read_text().strip() == name:
                return d
        except OSError:
            pass
    return None


def read_int(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


# ---------- ファン ----------

class Fan:
    """ファンなし(--fan-mode none)。状態だけ覚える。"""

    def __init__(self):
        self.state = 0

    def set(self, on: bool) -> None:
        self.state = int(on)

    def pwm(self) -> int | None:
        return None

    def close(self) -> None:
        self.set(False)


class GpioFan(Fan):
    """公式ケースファン(制御線を GPIO に直結)。"""

    def __init__(self, pin: int):
        super().__init__()
        from gpiozero import OutputDevice  # RasPi 上でだけ必要
        self.dev = OutputDevice(pin, active_high=True, initial_value=False)

    def set(self, on: bool) -> None:
        super().set(on)
        self.dev.value = self.state


class PoeFan(Fan):
    """PoE+ HAT のファン。冷却デバイス(type=pwm-fan)の cur_state を直接書く。

    OS の自動制御と取り合わないよう、thermal_zone0 の policy を user_space にする(終了時に元に戻す)。
    """

    def __init__(self, on_state: int | None = None, thermal_root: str = "/sys/class/thermal",
                 hwmon_root: str = "/sys/class/hwmon"):
        super().__init__()
        root = Path(thermal_root)
        self.cdev = next((d for d in sorted(root.glob("cooling_device*"))
                          if (d / "type").read_text().strip() == "pwm-fan"), None)
        if self.cdev is None:
            raise RuntimeError("pwm-fan の冷却デバイスが見つからない(PoE+ HAT が認識されていない?)")
        self.max_state = int((self.cdev / "max_state").read_text())
        self.on_state = self.max_state if on_state is None else min(on_state, self.max_state)
        self.policy_file = root / "thermal_zone0" / "policy"
        self.orig_policy = self.policy_file.read_text().strip()
        self.policy_file.write_text("user_space")
        hw = find_hwmon("pwmfan", hwmon_root)
        self.pwm_file = hw / "pwm1" if hw else None
        self._write(0)

    def _write(self, st: int) -> None:
        (self.cdev / "cur_state").write_text(str(st))

    def set(self, on: bool) -> None:
        if int(on) != self.state:
            self._write(self.on_state if on else 0)
        super().set(on)

    def pwm(self) -> int | None:
        return read_int(self.pwm_file)

    def close(self) -> None:
        try:
            self._write(0)
        finally:
            self.policy_file.write_text(self.orig_policy)  # OS の自動制御に戻す
            self.state = 0


def make_fan(args) -> Fan:
    if args.no_fan or args.fan_mode == "none":
        return Fan()
    if args.fan_mode == "gpio":
        return GpioFan(args.fan_pin)
    return PoeFan(on_state=args.fan_on_state)


# ---------- 負荷 ----------

class Load:
    """stress-ng を1つだけ動かす。"""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.workers = 0

    def set(self, workers: int) -> None:
        if workers == self.workers and (workers == 0 or self.proc is not None):
            return
        self.stop()
        if workers > 0:
            self.proc = subprocess.Popen(["stress-ng", "--cpu", str(workers), "--quiet"],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.workers = workers

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        self.workers = 0


# ---------- 本体 ----------

class Agent:
    def __init__(self, args):
        self.args = args
        self.host = args.host or socket.gethostname()
        self.fan = make_fan(args)
        self.poe_file = (lambda d: d / "curr1_input" if d else None)(find_hwmon("rpi_poe"))
        self.fan_cmd = -1
        self.load = Load()
        self.load_cmd: int | None = None
        self.last_cmd_time: float | None = None
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.mqtt = None
        self.topic_tel = f"{args.topic_prefix}/{self.host}/telemetry"
        self.topic_cmd = f"{args.topic_prefix}/{self.host}/fan/set"
        self.topic_load = f"{args.topic_prefix}/{self.host}/load/set"

    def connect(self):
        import paho.mqtt.client as mqtt  # RasPi 上でだけ必要
        try:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"agent-{self.host}")
        except AttributeError:  # paho-mqtt 1.x
            c = mqtt.Client(client_id=f"agent-{self.host}")
        c.on_connect = lambda client, *a: client.subscribe([(self.topic_cmd, 1), (self.topic_load, 1)])
        c.on_message = self.on_cmd
        c.connect_async(self.args.broker, self.args.port, keepalive=30)
        c.loop_start()
        self.mqtt = c

    def on_cmd(self, client, userdata, msg):
        payload = msg.payload.decode(errors="ignore").strip()
        if msg.topic == self.topic_load:
            if payload.isdigit():
                with self.lock:
                    self.load_cmd = int(payload)
            return
        if payload not in ("0", "1"):
            return
        with self.lock:
            self.fan_cmd = int(payload)
            self.last_cmd_time = time.time()

    def decide_fan(self, temp: float, now: float) -> tuple[bool, int]:
        """(ファン ON か, 強制 ON 中か)。"""
        with self.lock:
            cmd, last = self.fan_cmd, self.last_cmd_time
        if temp >= self.args.failsafe_temp:
            return True, 1
        if last is not None and now - last > self.args.cmd_timeout:
            return True, 1
        return cmd == 1, 0

    def run(self):
        """計測ループ。例外で止まっても負荷を止め、ファンを OS の自動制御に戻す。"""
        try:
            self._loop()
        finally:
            self.load.stop()
            self.fan.close()

    def _loop(self):
        a = self.args
        log_dir = Path(a.log_dir).expanduser()
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"{self.host}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        if not a.no_mqtt:
            self.connect()
        prev = parse_proc_stat(Path("/proc/stat").read_text())
        next_t = time.time() + a.interval
        with open(path, "w", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=FIELDS)
            w.writeheader()
            print(f"logging to {path}", file=sys.stderr)
            while not self.stop.is_set():
                time.sleep(max(0.0, next_t - time.time()))
                next_t += a.interval
                now = time.time()
                cur = parse_proc_stat(Path("/proc/stat").read_text())
                use, prev = cpu_usage(prev, cur), cur
                temp = read_temp()
                on, failsafe = self.decide_fan(temp, now)
                self.fan.set(on)
                with self.lock:
                    load_cmd = self.load_cmd
                if load_cmd is not None:
                    self.load.set(load_cmd)
                row = {
                    "ts": round(now, 3), "host": self.host, "temp": temp,
                    "cpu": round(use.get("cpu", float("nan")), 2),
                    **{f"cpu{i}": round(use.get(f"cpu{i}", float("nan")), 2) for i in range(4)},
                    "clock": parse_clock(vcgencmd("measure_clock", "arm")),
                    "throttled": parse_throttled(vcgencmd("get_throttled")),
                    "fan": self.fan.state, "fan_pwm": self.fan.pwm(), "fan_cmd": self.fan_cmd,
                    "failsafe": failsafe, "load1": os.getloadavg()[0], "load": self.load.workers,
                    "poe_ma": read_int(self.poe_file),
                }
                w.writerow(row)
                fp.flush()
                if self.mqtt is not None:
                    self.mqtt.publish(self.topic_tel, json.dumps(row), qos=0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--topic-prefix", default="etc")
    ap.add_argument("--host", default=None, help="ノード名(省略時はホスト名)")
    ap.add_argument("--interval", type=float, default=1.0, help="計測周期 [s]")
    ap.add_argument("--log-dir", default="~/etc_logs")
    ap.add_argument("--fan-mode", choices=["poe", "gpio", "none"], default="poe")
    ap.add_argument("--fan-on-state", type=int, default=None, help="PoE+ HAT の ON 時の段階(既定は最大)")
    ap.add_argument("--fan-pin", type=int, default=14, help="--fan-mode gpio のときのピン")
    ap.add_argument("--failsafe-temp", type=float, default=82.0)
    ap.add_argument("--cmd-timeout", type=float, default=10.0, help="指令が途絶えたら強制 ON にするまでの秒数")
    ap.add_argument("--no-fan", action="store_true", help="--fan-mode none と同じ(互換用)")
    ap.add_argument("--no-mqtt", action="store_true", help="MQTT を使わず CSV にだけ書く")
    args = ap.parse_args()
    agent = Agent(args)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: agent.stop.set())
    agent.run()


if __name__ == "__main__":
    main()
