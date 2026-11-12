"""既知のパラメータで作った合成データで、同定と KF の正しさを確かめる。

python -m pytest tests/ で実行。
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etc.kalman import NoiseParams, run_kf  # noqa: E402
from etc.metrics import prediction_metrics  # noqa: E402
from etc.model import ThermalParams, fit_self_only, fit_with_H  # noqa: E402

TRUE = ThermalParams(a=0.93, b=2.0, c=0.03, d=3.2, rho=0.92, z_base=50.0, dt=5.0)
NOISE = NoiseParams(R=0.05, qT=0.02, qH0=0.01, beta=0.0)


def simulate(p, n, N=4000, seed=0):
    """負荷と隣接温度をステップ状に切り替えながら真のモデルを回す。"""
    rng = np.random.default_rng(seed)
    u = np.repeat(rng.choice([0.0, 0.5, 1.0], size=N // 80 + 1), 80)[:N]
    nbr = 50.0 + np.repeat(rng.choice([0.0, 10.0, 25.0], size=N // 120 + 1), 120)[:N]
    T = np.empty(N)
    H = np.empty(N)
    T[0] = (p.b * u[0] + p.d) / (1 - p.a)
    H[0] = 0.0
    for k in range(N - 1):
        z = nbr[k] - p.z_base
        T[k + 1] = p.a * T[k] + p.b * u[k] + p.c * H[k] + p.d + rng.normal(0, np.sqrt(n.qT))
        H[k + 1] = p.rho * H[k] + (1 - p.rho) * z + rng.normal(0, np.sqrt(n.qH0))
    y = T + rng.normal(0, np.sqrt(n.R), N)
    return y, u, nbr, T


def test_identification_recovers_params():
    # 観測ノイズが小さいデータで同定(観測ノイズがあると a は少し小さめに出る:errors-in-variables)
    y, u, nbr, _ = simulate(TRUE, NoiseParams(R=1e-4, qT=0.02, qH0=0.01))
    p, _ = fit_with_H(y, u, nbr, dt=5.0, z_base=50.0)
    assert abs(p.a - TRUE.a) < 0.02
    assert abs(p.b - TRUE.b) < 0.3
    assert abs(p.c - TRUE.c) < 0.015
    assert abs(p.rho - TRUE.rho) < 0.04
    assert p.check() == []


def test_self_only_b_positive():
    y, u, _, _ = simulate(TRUE, NOISE)
    p, _ = fit_self_only(y, u, dt=5.0)
    assert p.b > 0 and 0 < p.a < 1


def test_kf_sigma_is_calibrated():
    """真のパラメータで KF を回すと、m ステップ先の誤差の標準偏差が予測 σ と合う。"""
    # 入力は一定にする(predict_ahead は「今の入力が続く」と仮定するため)
    N = 4000
    u = np.full(N, 0.5)
    nbr = np.full(N, 60.0)
    y, u, nbr, T = simulate_const(TRUE, NOISE, u, nbr, seed=2)
    m = 6
    out = run_kf(TRUE, NOISE, y, u, nbr, m)
    k = np.arange(200, len(y) - m)
    e = T[k + m] - out["pred"][k]  # 真の温度との誤差
    ratio = e.std() / out["sigma"][k].mean()
    assert 0.85 < ratio < 1.15, ratio


def simulate_const(p, n, u, nbr, seed):
    rng = np.random.default_rng(seed)
    N = len(u)
    T = np.empty(N)
    H = np.empty(N)
    T[0], H[0] = (p.b * u[0] + p.d + p.c * (nbr[0] - p.z_base)) / (1 - p.a), nbr[0] - p.z_base
    for k in range(N - 1):
        z = nbr[k] - p.z_base
        T[k + 1] = p.a * T[k] + p.b * u[k] + p.c * H[k] + p.d + rng.normal(0, np.sqrt(n.qT))
        H[k + 1] = p.rho * H[k] + (1 - p.rho) * z + rng.normal(0, np.sqrt(n.qH0))
    y = T + rng.normal(0, np.sqrt(n.R), N)
    return y, u, nbr, T


def test_kf_beats_open_loop_when_H_matters():
    """隣接温度が変わるデータでは、H ありの KF の方が H なし(c=0)より予測誤差が小さい。"""
    p = ThermalParams(a=0.93, b=2.0, c=0.1, d=3.2, rho=0.92, z_base=50.0, dt=5.0)
    y, u, nbr, _ = simulate(p, NOISE, seed=3)
    m = 6
    with_H = run_kf(p, NOISE, y, u, nbr, m)
    no_H_p = ThermalParams(a=p.a, b=p.b, c=0.0, d=p.d, rho=p.rho, z_base=p.z_base, dt=p.dt)
    no_H = run_kf(no_H_p, NOISE, y, u, nbr, m)
    r1 = prediction_metrics(y, with_H["pred"], m)["RMSE"]
    r0 = prediction_metrics(y, no_H["pred"], m)["RMSE"]
    assert r1 < r0
