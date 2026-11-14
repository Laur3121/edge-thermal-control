#!/usr/bin/env python3
"""シナリオ(JSON)どおりに負荷とファンを切り替えて実験を自動で回す(収集用 PC で実行)。

流れ:collector を起動 → 全ノードの温度が落ち着くまで待つ → 段階(phase)を順に実行 → 全部止める。
切り替えた時刻は <out>/events.csv に記録する。シナリオは <out>/config.json にコピーする。

例:
  python scripts/run_experiment.py --scenario scripts/scenarios/step_identify.json \
      --nodes A=raspi1 B=raspi2 C=raspi5 --broker localhost \
      --out experiments/20261114_step_identify

シナリオの形(役割名 A/B/C で書き、--nodes で実際のホスト名に対応させる):
{
  "name": "...", "description": "...",
  "settle": {"window_s": 120, "max_slope_c_per_min": 0.2, "timeout_s": 1800},
  "phases": [
    {"name": "baseline", "duration_s": 300, "load": {"A": 0}, "fan": {"A": 0, "B": 0, "C": 0}},
    {"name": "heat", "max_s": 900, "until": {"role": "A", "temp_ge": 75}, "load": {"A": 2}},
    {"repeat": 3, "phases": [ ...入れ子の段階... ]}
  ]
}
load / fan に書かなかった役割は前の段階の値を引き継ぐ。最初はすべて負荷 0・ファン 0。

閉ループ制御:fan に 0/1 の代わりに方式名("proposed" / "self_fixed" / "threshold"、src/etc/control.py)を書くと、
その段階から制御器が 5 秒ごとにファンを決める(段階に入るたびに制御器を作り直す)。--control-params の同定値を使う。
制御器の設定はシナリオの "control": {...}(ControlConfig の項目)。判断の記録は <out>/control.csv。
"""

from __future__ import annotations

import argparse
import csv
import json
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

HEARTBEAT_S = 2.0  # ファン指令を送り直す間隔(node_agent の指令途絶タイムアウトより短く)
CONTROL_FIELDS = ["ts", "phase", "role", "host", "mode", "n", "T", "u", "f", "T_amb", "pred", "sigma",
                  "margin", "tsafe", "fan", "reason"]


# ---------- 純粋関数(テスト対象) ----------

def expand_phases(phases: list[dict]) -> list[dict]:
    """{"repeat": n, "phases": [...]} を展開し、名前に回数を付ける。"""
    out = []
    for ph in phases:
        if "repeat" in ph:
            for i in range(ph["repeat"]):
                for sub in expand_phases(ph["phases"]):
                    out.append({**sub, "name": f"{sub['name']}#{i + 1}"})
        else:
            if "duration_s" not in ph and "max_s" not in ph:
                raise ValueError(f"phase {ph.get('name')} に duration_s か max_s が必要")
            out.append(dict(ph))
    return out


def parse_nodes(items: list[str]) -> dict[str, str]:
    """["A=raspi1", ...] → {"A": "raspi1", ...}"""
    out = {}
    for it in items:
        role, _, host = it.partition("=")
        if not role or not host:
            raise ValueError(f"--nodes の書き方が違う: {it}(例 A=raspi1)")
        out[role] = host
    return out


def check_roles(phases: list[dict], roles: set[str]) -> None:
    for ph in phases:
        used = set(ph.get("load", {})) | set(ph.get("fan", {}))
        if "until" in ph:
            used.add(ph["until"]["role"])
        missing = used - roles
        if missing:
            raise ValueError(f"phase {ph['name']} の役割 {missing} が --nodes にない")


def is_settled(samples, window_s: float, max_slope_c_per_min: float) -> bool:
    """samples = [(t, temp), ...]。直近 window_s 秒の温度の傾き(最小二乗)が小さければ True。"""
    if not samples:
        return False
    t_end = samples[-1][0]
    win = [(t, y) for t, y in samples if t >= t_end - window_s]
    if len(win) < 5 or win[-1][0] - win[0][0] < 0.9 * window_s:
        return False
    n = len(win)
    mt = sum(t for t, _ in win) / n
    my = sum(y for _, y in win) / n
    sxx = sum((t - mt) ** 2 for t, _ in win)
    if sxx == 0:
        return False
    slope = sum((t - mt) * (y - my) for t, y in win) / sxx  # ℃/s
    return abs(slope) * 60 <= max_slope_c_per_min


# ---------- 実行 ----------

class Runner:
    def __init__(self, args, scenario: dict, nodes: dict[str, str]):
        self.args, self.sc, self.nodes = args, scenario, nodes
        self.out = Path(args.out)
        self.temps = {h: deque(maxlen=3600) for h in nodes.values()}
        self.rows = {h: deque(maxlen=120) for h in nodes.values()}  # (ts, temp, cpu, fan) 制御用
        self.load = {r: 0 for r in nodes}
        self.fan = {r: 0 for r in nodes}
        self.mode: dict[str, str | None] = {r: None for r in nodes}
        self.ctrl = {}
        self.phase = ""
        self.ctrl_params = (json.loads(Path(args.control_params).read_text())
                            if getattr(args, "control_params", None) else None)
        self._amb = (0.0, None)  # (読んだ時刻, 室温)
        self.ctl_fp = None
        self.ctl = None
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.mqtt = None
        self.ev_fp = None
        self.ev = None

    # MQTT
    def connect(self):
        import paho.mqtt.client as mqtt
        try:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="etc-runner")
        except AttributeError:
            c = mqtt.Client(client_id="etc-runner")
        prefix = self.args.topic_prefix
        c.on_connect = lambda client, *a: client.subscribe(f"{prefix}/+/telemetry")
        c.on_message = self.on_tel
        c.connect(self.args.broker, self.args.port, keepalive=30)
        c.loop_start()
        self.mqtt = c

    def on_tel(self, client, userdata, msg):
        try:
            row = json.loads(msg.payload)
        except json.JSONDecodeError:
            return
        h = row.get("host")
        if h in self.temps and row.get("temp") is not None:
            with self.lock:
                self.temps[h].append((float(row["ts"]), float(row["temp"])))
                try:
                    self.rows[h].append((float(row["ts"]), float(row["temp"]), float(row["cpu"]),
                                         float(row.get("fan") or 0)))
                except (KeyError, TypeError, ValueError):
                    pass

    def latest(self, role: str) -> float | None:
        with self.lock:
            q = self.temps[self.nodes[role]]
            return q[-1][1] if q else None

    def send(self, role: str, kind: str, value: int):
        self.mqtt.publish(f"{self.args.topic_prefix}/{self.nodes[role]}/{kind}/set", str(value), qos=1)

    def event(self, kind: str, phase: str = "", role: str = "", value="") -> None:
        now = time.time()
        host = self.nodes.get(role, "")
        self.ev.writerow({"ts": round(now, 3), "event": kind, "phase": phase,
                          "role": role, "host": host, "value": value})
        self.ev_fp.flush()
        print(f"[{time.strftime('%H:%M:%S')}] {kind} {phase} {role} {value}".rstrip())

    def apply(self, phase: dict):
        for role, v in phase.get("load", {}).items():
            self.load[role] = int(v)
            self.send(role, "load", int(v))
            self.event("load", phase["name"], role, int(v))
        for role, v in phase.get("fan", {}).items():
            if isinstance(v, str):  # 閉ループ制御。OFF から始める
                self.ctrl[role] = self.make_ctrl(role, v)
                self.mode[role] = v
                self.event("fan_mode", phase["name"], role, v)
                v = 0
            else:
                self.mode[role] = None
            self.fan[role] = int(v)
            self.send(role, "fan", int(v))
            self.event("fan", phase["name"], role, int(v))

    def make_ctrl(self, role: str, mode: str):
        from etc.control import ControlConfig, controller_from_dict
        if self.ctrl_params is None:
            raise SystemExit("閉ループ制御には --control-params が必要")
        cfg = ControlConfig(**self.sc.get("control", {}))
        return controller_from_dict(mode, self.ctrl_params["nodes"][self.nodes[role]], cfg)

    def ambient(self) -> float:
        """室温(ハブ)の最新値。ambient.csv を 30 秒ごとに読み直す。読めなければ前の値か --ambient-default。"""
        now = time.time()
        if now - self._amb[0] > 30:
            val = self._amb[1]
            path = self.out / "raw" / "ambient.csv"
            try:
                with open(path, newline="") as fp:
                    for r in csv.DictReader(fp):
                        if self.args.ambient_name in r["name"]:
                            val = float(r["temperature"])
            except (OSError, KeyError, ValueError):
                pass
            self._amb = (now, val)
        return self._amb[1] if self._amb[1] is not None else self.args.ambient_default

    def control_loop(self):
        """閉ループ制御の役割について、dt 秒ごとに直近 dt 秒の平均で判断する。"""
        if self.ctrl_params is None:
            return
        dt = float(self.ctrl_params["dt"])
        nxt = time.time() + dt
        while not self.stop.wait(max(0.0, nxt - time.time())):
            now = nxt
            nxt += dt
            for role, mode in list(self.mode.items()):
                if mode is None:
                    continue
                with self.lock:
                    win = [r for r in self.rows[self.nodes[role]] if now - dt <= r[0] < now]
                if not win:
                    continue
                T = sum(r[1] for r in win) / len(win)
                u = sum(r[2] for r in win) / len(win) / 100.0
                f = sum(r[3] for r in win) / len(win)
                Ta = self.ambient()
                d = self.ctrl[role].step(now, T, u, f, Ta)
                self.ctl.writerow({"ts": round(now, 3), "phase": self.phase, "role": role, "host": self.nodes[role],
                                   "mode": mode, "n": len(win), "T": round(T, 3), "u": round(u, 4),
                                   "f": round(f, 3), "T_amb": Ta, "pred": round(d.pred, 3),
                                   "sigma": round(d.sigma, 4), "margin": round(d.margin, 3),
                                   "tsafe": round(d.tsafe, 3), "fan": d.fan, "reason": d.reason})
                self.ctl_fp.flush()
                if d.fan != self.fan[role] and self.mode[role] == mode:
                    self.fan[role] = d.fan
                    self.send(role, "fan", d.fan)
                    self.event("fan", self.phase, role, d.fan)

    def heartbeat(self):
        while not self.stop.wait(HEARTBEAT_S):
            for role, v in self.fan.items():
                self.send(role, "fan", v)

    def wait_settled(self):
        st = self.sc.get("settle", {})
        window, slope = st.get("window_s", 120), st.get("max_slope_c_per_min", 0.2)
        timeout = st.get("timeout_s", 1800)
        self.event("settle_start")
        t0 = time.time()
        while not self.stop.is_set():
            with self.lock:
                ok = {h: is_settled(list(q), window, slope) for h, q in self.temps.items()}
            if all(ok.values()):
                temps = {r: self.latest(r) for r in self.nodes}
                self.event("settled", value=json.dumps(temps))
                return
            if time.time() - t0 > timeout:
                self.event("settle_timeout", value=json.dumps(ok))
                return
            time.sleep(5)

    def run_phase(self, ph: dict):
        self.phase = ph["name"]
        self.event("phase_start", ph["name"])
        self.apply(ph)
        t0 = time.time()
        limit = ph.get("duration_s", ph.get("max_s"))
        until = ph.get("until")
        while not self.stop.is_set():
            el = time.time() - t0
            if el >= limit:
                self.event("phase_end", ph["name"], value="time")
                return
            if until is not None:
                T = self.latest(until["role"])
                if T is not None and "temp_ge" in until and T >= until["temp_ge"]:
                    self.event("phase_end", ph["name"], until["role"], f"temp_ge {T}")
                    return
                if T is not None and "temp_le" in until and T <= until["temp_le"]:
                    self.event("phase_end", ph["name"], until["role"], f"temp_le {T}")
                    return
            time.sleep(1)
        self.event("aborted", ph["name"])

    def run(self, phases: list[dict]):
        self.out.mkdir(parents=True, exist_ok=True)
        cfg = self.out / "config.json"
        if cfg.exists():
            sys.exit(f"{cfg} が既にある。生ログを上書きしないよう、別の --out を指定する")
        cfg.write_text(json.dumps({"scenario": self.sc, "nodes": self.nodes,
                                   "args": vars(self.args)}, indent=2, ensure_ascii=False))
        readme = self.out / "README.md"
        if not readme.exists():
            readme.write_text(README_TEMPLATE.format(name=self.sc.get("name", ""),
                                                     desc=self.sc.get("description", ""),
                                                     nodes=", ".join(f"{r}={h}" for r, h in self.nodes.items())))
        self.ev_fp = open(self.out / "events.csv", "w", newline="")
        self.ev = csv.DictWriter(self.ev_fp, fieldnames=["ts", "event", "phase", "role", "host", "value"])
        self.ev.writeheader()
        if self.ctrl_params is not None:
            self.ctl_fp = open(self.out / "control.csv", "w", newline="")
            self.ctl = csv.DictWriter(self.ctl_fp, fieldnames=CONTROL_FIELDS)
            self.ctl.writeheader()

        ambient = None
        if self.args.ambient:
            ambient = subprocess.Popen([sys.executable, str(Path(__file__).with_name("ambient_logger.py")),
                                        "--out", str(self.out)])
        collector = None
        if not self.args.no_collector:
            collector = subprocess.Popen([sys.executable, str(Path(__file__).with_name("collector.py")),
                                          "--broker", self.args.broker, "--port", str(self.args.port),
                                          "--topic-prefix", self.args.topic_prefix, "--out", str(self.out)])
        self.connect()
        hb = threading.Thread(target=self.heartbeat, daemon=True)
        cl = threading.Thread(target=self.control_loop, daemon=True)
        try:
            self.event("start", value=self.sc.get("name", ""))
            self.apply({"name": "init", "load": {r: 0 for r in self.nodes}, "fan": {r: 0 for r in self.nodes}})
            hb.start()
            cl.start()
            if not self.args.no_settle:
                self.wait_settled()
            for ph in phases:
                if self.stop.is_set():
                    break
                self.run_phase(ph)
        finally:
            self.phase = "end"
            self.apply({"name": "end", "load": {r: 0 for r in self.nodes}, "fan": {r: 0 for r in self.nodes}})
            self.event("end")
            self.stop.set()
            time.sleep(1)
            self.mqtt.loop_stop()
            for p in (collector, ambient):
                if p is not None:
                    p.send_signal(signal.SIGINT)
                    p.wait(timeout=10)
            self.ev_fp.close()
            if self.ctl_fp is not None:
                self.ctl_fp.close()


README_TEMPLATE = """# {name}

{desc}

自動生成した雛形。実験の前後に埋める。生ログ(raw/、events.csv)は編集しない。

## 条件

- 日時:
- ノード:{nodes}
- 配置・距離(写真のファイル名も):
- 筐体の状態(密閉 / 吸気口あり):
- 室温(開始時 / 終了時):
- CPU ガバナ:
- 他のノードの状態:

## メモ(気づいたこと、異常)

"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--nodes", nargs="+", required=True, help="役割=ホスト名(例 A=raspi1 B=raspi2 C=raspi5)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--topic-prefix", default="etc")
    ap.add_argument("--no-settle", action="store_true", help="開始前に温度が落ち着くのを待たない")
    ap.add_argument("--no-collector", action="store_true", help="collector を別に動かしている場合")
    ap.add_argument("--ambient", action="store_true",
                    help="SwitchBot 温湿度計の室温も記録する(scripts/ambient_logger.py。.env にトークンが必要)")
    ap.add_argument("--control-params", default=None,
                    help="閉ループ制御の同定値(scripts/fit_control_params.py の出力)。fan に方式名を書く段階で必須")
    ap.add_argument("--ambient-name", default="ハブ", help="制御に使う室温計の名前(部分一致)")
    ap.add_argument("--ambient-default", type=float, default=20.0, help="室温が読めないときの値 [℃]")
    ap.add_argument("--dry-run", action="store_true", help="段階の一覧と合計時間を表示するだけ")
    args = ap.parse_args()

    sc = json.loads(Path(args.scenario).read_text())
    nodes = parse_nodes(args.nodes)
    phases = expand_phases(sc["phases"])
    check_roles(phases, set(nodes))
    total = sum(p.get("duration_s", p.get("max_s", 0)) for p in phases)
    print(f"{sc.get('name')}: {len(phases)} phases, 最長 {total / 60:.0f} 分(待ち時間を除く)")
    if args.dry_run:
        for p in phases:
            lim = p.get("duration_s", p.get("max_s"))
            until = f" until {p['until']}" if "until" in p else ""
            print(f"  {p['name']:<24} {lim:>5}s{until}  load={p.get('load', {})} fan={p.get('fan', {})}")
        return
    r = Runner(args, sc, nodes)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: r.stop.set())
    r.run(phases)


if __name__ == "__main__":
    main()
