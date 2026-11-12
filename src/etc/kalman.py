"""外部熱影響 H を状態に持つカルマンフィルタと、Δ秒先予測・動的マージン。

x_t = [T_t, H_t]^T
x_{t+1} = A x_t + [b u_t + d + e f_t, (1-rho) z_t]^T + w_t,   A = [[a, c], [0, rho]]
y_t = [1 0] x_t + v_t
Q_t = diag(qT, qH(t)),  qH(t) = qH0 + beta |z_t - z_{t-1}|

c = 0 にすると H は T に効かなくなり、「H なし KF」(Self-only の KF 版)になる。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .model import ThermalParams

C = np.array([1.0, 0.0])


@dataclass
class NoiseParams:
    R: float  # 観測ノイズの分散 [℃^2]
    qT: float  # T のプロセスノイズの分散 [℃^2]
    qH0: float  # H のプロセスノイズの分散(基本)
    beta: float = 0.0  # 適応プロセスノイズの係数(0 で固定 Q)


class ThermalKF:
    """1ステップずつ回すカルマンフィルタ。実機の制御ループでもそのまま使う。"""

    def __init__(self, p: ThermalParams, n: NoiseParams, T0: float, H0: float = 0.0,
                 P0=None):
        self.p, self.n = p, n
        self.A = np.array([[p.a, p.c], [0.0, p.rho]])
        self.x = np.array([T0, H0], dtype=float)
        self.P = np.diag([n.R, 1.0]) if P0 is None else np.asarray(P0, float)
        self.z_prev: float | None = None

    def _drive(self, u: float, z: float, f: float) -> np.ndarray:
        p = self.p
        return np.array([p.b * u + p.d + p.e * f, (1 - p.rho) * z])

    def _Q(self, dz: float) -> np.ndarray:
        n = self.n
        return np.diag([n.qT, n.qH0 + n.beta * abs(dz)])

    def step(self, y: float, u: float, nbr: float, f: float = 0.0) -> None:
        """時刻 t の入力 (u_t, nbr_t, f_t) で予測し、時刻 t+1 の観測 y_{t+1} で更新する。"""
        z = nbr - self.p.z_base
        dz = 0.0 if self.z_prev is None else z - self.z_prev
        self.z_prev = z
        # 予測
        self.x = self.A @ self.x + self._drive(u, z, f)
        self.P = self.A @ self.P @ self.A.T + self._Q(dz)
        # 更新
        S = C @ self.P @ C + self.n.R
        K = self.P @ C / S
        self.x = self.x + K * (y - C @ self.x)
        self.P = self.P - np.outer(K, C @ self.P)

    def predict_ahead(self, m: int, u: float, nbr: float, f: float = 0.0):
        """現在の推定から m ステップ先の温度の平均と標準偏差 σ を返す。

        未来の入力は分からないので、現在の u・隣接温度・ファン状態がそのまま続くと仮定する。
        未来の dz は 0 とみなす(Q = diag(qT, qH0))。
        """
        z = nbr - self.p.z_base
        x, P = self.x.copy(), self.P.copy()
        drive, Q = self._drive(u, z, f), self._Q(0.0)
        for _ in range(m):
            x = self.A @ x + drive
            P = self.A @ P @ self.A.T + Q
        return float(x[0]), float(np.sqrt(P[0, 0]))


def run_kf(p: ThermalParams, n: NoiseParams, T, u, nbr, m: int, f=None):
    """系列全体に KF を回し、各時刻 k での m ステップ先予測を返す。

    戻り値:dict(T_hat=フィルタ推定, H_hat, pred=k+m の予測, sigma=予測の σ, P_TT)。
    pred[k] は時刻 k までの情報だけで計算した T_{k+m} の予測。
    """
    T, u, nbr = (np.asarray(v, float) for v in (T, u, nbr))
    f = np.zeros_like(T) if f is None else np.asarray(f, float)
    N = len(T)
    kf = ThermalKF(p, n, T0=T[0])
    out = {k: np.full(N, np.nan) for k in ("T_hat", "H_hat", "pred", "sigma", "P_TT")}
    for k in range(N):
        if k > 0:
            kf.step(T[k], u[k - 1], nbr[k - 1], f[k - 1])
        out["T_hat"][k], out["H_hat"][k] = kf.x
        out["P_TT"][k] = kf.P[0, 0]
        out["pred"][k], out["sigma"][k] = kf.predict_ahead(m, u[k], nbr[k], f[k])
    return out


def dynamic_margin(sigma, alpha: float, delta: float):
    """M = α σ + δ。"""
    return alpha * np.asarray(sigma) + delta
