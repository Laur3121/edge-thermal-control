"""node_agent の計測部分(RasPi がなくても確かめられる部分)のテスト。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "node"))

import node_agent as na  # noqa: E402

STAT0 = """cpu  100 0 100 800 0 0 0 0 0 0
cpu0 25 0 25 200 0 0 0 0 0 0
cpu1 25 0 25 200 0 0 0 0 0 0
intr 12345
"""
# 1秒後:cpu0 だけ 100 jiffies 全部稼働、cpu1 は全部アイドル
STAT1 = """cpu  200 0 100 900 0 0 0 0 0 0
cpu0 125 0 25 200 0 0 0 0 0 0
cpu1 25 0 25 300 0 0 0 0 0 0
"""


def test_cpu_usage_is_interval_average():
    u = na.cpu_usage(na.parse_proc_stat(STAT0), na.parse_proc_stat(STAT1))
    assert u["cpu0"] == 100.0
    assert u["cpu1"] == 0.0
    assert u["cpu"] == 50.0


def test_iowait_counts_as_idle():
    s0 = na.parse_proc_stat("cpu 0 0 0 0 0 0 0 0\n")
    s1 = na.parse_proc_stat("cpu 0 0 0 50 50 0 0 0\n")
    assert na.cpu_usage(s0, s1)["cpu"] == 0.0


def test_parse_vcgencmd():
    assert na.parse_clock("frequency(48)=1500398464\n") == 1500398464
    assert na.parse_clock("") is None
    assert na.parse_throttled("throttled=0x50000\n") == "0x50000"


class _Args:
    failsafe_temp = 82.0
    cmd_timeout = 10.0
    host = "test"
    fan_pin = 14
    no_fan = True
    topic_prefix = "etc"


def test_failsafe():
    a = na.Agent(_Args())
    # 指令を一度も受けていなければ OFF(タイムアウトは効かない)
    assert a.decide_fan(60.0, now=1000.0) == (False, 0)
    # 高温なら指令に関係なく ON
    assert a.decide_fan(82.0, now=1000.0) == (True, 1)
    # 指令 ON / OFF
    a.fan_cmd, a.last_cmd_time = 1, 1000.0
    assert a.decide_fan(60.0, now=1005.0) == (True, 0)
    a.fan_cmd = 0
    assert a.decide_fan(60.0, now=1005.0) == (False, 0)
    # 指令が途絶えたら ON
    assert a.decide_fan(60.0, now=1011.0) == (True, 1)


def _fake_sysfs(tmp_path):
    th = tmp_path / "thermal"
    (th / "thermal_zone0").mkdir(parents=True)
    (th / "thermal_zone0" / "policy").write_text("step_wise\n")
    cd = th / "cooling_device0"
    cd.mkdir()
    (cd / "type").write_text("pwm-fan\n")
    (cd / "max_state").write_text("4\n")
    (cd / "cur_state").write_text("2\n")
    hw = tmp_path / "hwmon" / "hwmon3"
    hw.mkdir(parents=True)
    (hw / "name").write_text("pwmfan\n")
    (hw / "pwm1").write_text("64\n")
    return th, tmp_path / "hwmon"


def test_poe_fan_takes_and_returns_control(tmp_path):
    th, hw = _fake_sysfs(tmp_path)
    f = na.PoeFan(thermal_root=str(th), hwmon_root=str(hw))
    # 起動時:OS の自動制御を止めて OFF
    assert (th / "thermal_zone0" / "policy").read_text() == "user_space"
    assert (th / "cooling_device0" / "cur_state").read_text() == "0"
    f.set(True)
    assert (th / "cooling_device0" / "cur_state").read_text() == "4"
    assert f.pwm() == 64
    f.set(False)
    assert (th / "cooling_device0" / "cur_state").read_text() == "0"
    # 終了時:元の policy に戻す
    f.close()
    assert (th / "thermal_zone0" / "policy").read_text() == "step_wise"


def test_poe_fan_on_state_is_clamped(tmp_path):
    th, hw = _fake_sysfs(tmp_path)
    f = na.PoeFan(on_state=9, thermal_root=str(th), hwmon_root=str(hw))
    f.set(True)
    assert (th / "cooling_device0" / "cur_state").read_text() == "4"
