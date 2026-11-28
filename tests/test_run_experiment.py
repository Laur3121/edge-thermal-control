"""run_experiment のシナリオ展開と「温度が落ち着いた」判定のテスト。"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_experiment as rx  # noqa: E402


def test_expand_repeat_names():
    ph = rx.expand_phases([
        {"name": "a", "duration_s": 10},
        {"repeat": 2, "phases": [{"name": "on", "duration_s": 5}, {"name": "off", "max_s": 5}]},
    ])
    assert [p["name"] for p in ph] == ["a", "on#1", "off#1", "on#2", "off#2"]


def test_phase_needs_length():
    with pytest.raises(ValueError):
        rx.expand_phases([{"name": "x"}])


def test_parse_nodes_and_roles():
    nodes = rx.parse_nodes(["A=raspi1", "B=raspi2"])
    assert nodes == {"A": "raspi1", "B": "raspi2"}
    with pytest.raises(ValueError):
        rx.check_roles([{"name": "p", "duration_s": 1, "load": {"C": 1}}], set(nodes))


def test_is_settled():
    flat = [(t, 50.0 + (0.5 if t % 7 == 0 else 0.0)) for t in range(0, 200)]
    rising = [(t, 50.0 + t / 60.0) for t in range(0, 200)]  # 1℃/分
    assert rx.is_settled(flat, 120, 0.2)
    assert not rx.is_settled(rising, 120, 0.2)
    assert not rx.is_settled(flat[:60], 120, 0.2)  # 窓の長さに足りない


def test_bundled_scenarios_are_valid():
    for path in (ROOT / "scripts" / "scenarios").glob("*.json"):
        sc = json.loads(path.read_text())
        rx.check_roles(rx.expand_phases(sc["phases"]), {"A", "B", "C"})


def test_split_mode_overrides():
    """方式名の後ろの設定(11/27 追加)。"""
    sys.path.insert(0, str(ROOT / "src"))
    from etc.control import ControlConfig
    base, cfg = rx.split_mode("threshold@t_on=65,t_off=60", ControlConfig())
    assert base == "threshold" and cfg.t_on == 65 and cfg.t_off == 60 and cfg.alpha == 2.0
    base, cfg = rx.split_mode("proposed", ControlConfig(alpha=3))
    assert base == "proposed" and cfg.alpha == 3
    with pytest.raises(ValueError):
        rx.split_mode("proposed@nosuch=1", ControlConfig())


def test_gen_cond_value():
    sys.path.insert(0, str(ROOT / "scripts" / "scenarios"))
    import gen_box_control as g
    assert g.cond_value("th65") == "threshold@t_on=65,t_off=60"
    assert g.cond_value("pa1p5") == "proposed@alpha=1.5"
    assert g.cond_value("pd3") == "proposed@delta_margin=3"
    assert g.cond_value("pr0p5") == "proposed_risk@risk_eps=0.005,risk_p=0.2"
    assert g.cond_value("threshold") == "threshold"


def test_use_h_zero_uses_self_model():
    """use_h = 0 なら proposed でも H なしのモデル(11/27 追加、実験 B)。"""
    sys.path.insert(0, str(ROOT / "src"))
    from etc.control import ControlConfig, controller_from_dict
    node = json.loads((ROOT / "scripts" / "control_params_open.json").read_text())["nodes"]["raspi1"]
    assert controller_from_dict("proposed", node, ControlConfig()).p.c > 0
    base, cfg = rx.split_mode("proposed@use_h=0", ControlConfig())
    c = controller_from_dict(base, node, cfg)
    assert c.p.c == 0 and c.p.a == node["self"]["a"]
