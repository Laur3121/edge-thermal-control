"""ファン制御則の確認(合成モデル上の閉ループ)。"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etc.control import ControlConfig, FanController, simulate  # noqa: E402
from etc.kalman import NoiseParams  # noqa: E402
from etc.model import ThermalParams  # noqa: E402

# 11/13 の同定値(案B、dt=5 秒、室温からの上昇分)
P = ThermalParams(a=0.927, b=1.915, d=2.719, e=-1.407, dt=5.0)
N = NoiseParams(R=0.068, qT=0.3, qH0=0.0, beta=0.0)
T_AMB = 20.0
# ファン OFF の定常:u=1 で θ = (1.915+2.719)/0.073 ≈ 63 → 83℃(80℃ を超える)
U = np.r_[np.full(60, 0.25), np.full(240, 1.0), np.full(120, 0.0), np.full(240, 0.75)]


def run(mode, **kw):
    ctrl = FanController(mode, P, N, ControlConfig(**kw), fixed_margin=5.0)
    return simulate(ctrl, P, U, T_AMB, T0=50.0, noise_sd=0.3, seed=1)


def test_no_fan_exceeds_limit():
    # 前提の確認:ファンなしだと 80℃ を超える負荷パターン
    T = T_AMB
    th = 30.0
    for u in U:
        th = P.a * th + P.b * u + P.d
        T = max(T, th + T_AMB)
    assert T > 80


def test_predictive_modes_stay_below_limit_and_fan_not_always_on():
    for mode in ("proposed", "self_fixed", "threshold"):
        T, f, _ = run(mode)
        assert T.max() < 80.0, (mode, T.max())
        assert 0.05 < f.mean() < 0.95, (mode, f.mean())


def test_min_on_time_respected():
    T, f, _ = run("proposed", min_on_s=60.0)
    # ON になったら少なくとも 60 秒(12 ステップ)続く
    starts = np.where(np.diff(np.r_[0, f]) == 1)[0]
    ends = np.where(np.diff(np.r_[f, 0]) == -1)[0]
    assert all(e - s + 1 >= 12 for s, e in zip(starts, ends))


def test_proposed_margin_is_alpha_sigma_plus_delta():
    ctrl = FanController("proposed", P, N, ControlConfig())
    for k in range(20):
        d = ctrl.step(5.0 * k, 60.0, 0.5, 0, T_AMB)
    assert np.isclose(d.margin, 2.0 * d.sigma + 0.5)
    assert np.isclose(d.tsafe, 80.0 - d.margin)


def test_delay_zero_is_unchanged_and_delay_runs():
    # fan_delay_s = 0 は今までと同じ判断(hist なし)。遅れありでも予測の方式は 80℃ を守る(11/26 追加)
    a = FanController("proposed", P, N, ControlConfig())
    assert a.hist is None and a.m == 6
    ctrl = FanController("proposed", P, N, ControlConfig(fan_delay_s=60.0))
    assert ctrl.Ld == 12 and ctrl.m == 18
    T, f, c = simulate(ctrl, P, U, T_AMB, T0=50.0, noise_sd=0.3, seed=1, delay_steps=12)
    assert T.max() < 80.0, T.max()


def test_risk_mode_runs_and_is_more_careful_at_low_load():
    """proposed_risk(11/28 追加):遅れありで 80℃ を守る。同じ温度なら、負荷が低い(上がる余地がある)ときの方が
    超える確率を高く見積もる。負荷が最大なら今の負荷が続く場合だけ。"""
    ctrl = FanController("proposed_risk", P, N, ControlConfig(fan_delay_s=60.0, risk_eps=0.01, risk_p=0.3))
    T, f, c = simulate(ctrl, P, U, T_AMB, T0=50.0, noise_sd=0.3, seed=1, delay_steps=12)
    assert T.max() < 80.0, T.max()
    a = FanController("proposed_risk", P, N, ControlConfig(fan_delay_s=60.0, risk_p=0.3))
    a.step(0.0, 70.0, 0.25, 0.0, T_AMB)
    th = 70.0 - T_AMB
    pred, sig = a._predict_off(th, 0.25, P.z_base)
    p_low = a._risk(pred, sig, 0.25, P.z_base, 80.0 - T_AMB)
    pred1, sig1 = a._predict_off(th, 1.0, P.z_base)
    p_max = a._risk(pred1, sig1, 1.0, P.z_base, 80.0 - T_AMB)
    from math import erf, sqrt
    assert abs(p_max - 0.5 * (1 + erf((pred1 - (80.0 - T_AMB)) / sig1 / sqrt(2)))) < 1e-9
    b = FanController("proposed_risk", P, N, ControlConfig(fan_delay_s=60.0, risk_p=0.0))
    b.step(0.0, 70.0, 0.25, 0.0, T_AMB)
    assert p_low > b._risk(pred, sig, 0.25, P.z_base, 80.0 - T_AMB)
