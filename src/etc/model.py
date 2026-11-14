"""拡張熱モデルのパラメータとその同定。

T_{t+1} = a T_t + b u_t + c H_t + d + e f_t
H_{t+1} = rho H_t + (1 - rho) z_t,   z_t = T^nbr_t - z_base

物理的な意味は docs/parameters.md を参照(a = exp(-dt/tau)、b = (1-a) R k など)。
ファン項 e f_t は案B(加算項、2026-11-13 決定)。f を与えない同定では e = 0。
"""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass

import numpy as np


@dataclass
class ThermalParams:
    a: float
    b: float
    d: float
    c: float = 0.0  # 外部熱影響 H の結合強度(0 なら Self-only)
    rho: float = 0.9  # H の持続性 = exp(-dt / tau_H)
    z_base: float = 0.0  # 隣接温度の基準 [℃]
    e: float = 0.0  # ファン項(仮)
    dt: float = 1.0  # 同定に使った刻み [s]

    @property
    def tau(self) -> float:
        """自ノードの時定数 [s]。"""
        return -self.dt / np.log(self.a) if 0 < self.a < 1 else float("nan")

    @property
    def tau_H(self) -> float:
        """外部熱影響の時定数 [s]。"""
        return -self.dt / np.log(self.rho) if 0 < self.rho < 1 else float("nan")

    def check(self) -> list[str]:
        """物理的に不自然な値なら理由を返す(空なら問題なし)。"""
        issues = []
        if not 0 < self.a < 1:
            issues.append(f"a={self.a:.4f} は (0,1) の外(時定数が定義できない)")
        if self.b <= 0:
            issues.append(f"b={self.b:.4f} <= 0(負荷で温度が下がることになる)")
        if not 0 < self.rho < 1:
            issues.append(f"rho={self.rho:.4f} は (0,1) の外")
        if self.c < 0:
            issues.append(f"c={self.c:.4f} < 0(隣が熱いと冷えることになる)")
        return issues

    def to_dict(self) -> dict:
        return {**asdict(self), "tau": self.tau, "tau_H": self.tau_H}


def lowpass_H(z: np.ndarray, rho: float, H0: float = 0.0) -> np.ndarray:
    """H_{t+1} = rho H_t + (1-rho) z_t を雑音なしで回した H の系列(同定用)。"""
    H = np.empty_like(z, dtype=float)
    H[0] = H0
    for k in range(len(z) - 1):
        H[k + 1] = rho * H[k] + (1 - rho) * z[k]
    return H


def _lstsq(X: np.ndarray, y: np.ndarray):
    theta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ theta
    return theta, resid


def fit_self_only(T, u, dt: float, mask=None, f=None) -> tuple[ThermalParams, np.ndarray]:
    """T_{t+1} = a T_t + b u_t (+ e f_t) + d を最小二乗で同定する。

    mask(長さ len(T)-1 の bool)が True の遷移だけを使う。スロットリング中の区間を除くのに使う。
    f(ファン状態 0〜1)を与えるとファン項 e も同定する(案B)。
    戻り値は (パラメータ, 1ステップ残差)。
    """
    T, u = np.asarray(T, float), np.asarray(u, float)
    cols = [T[:-1], u[:-1]] + ([np.asarray(f, float)[:-1]] if f is not None else [])
    X = np.column_stack(cols + [np.ones(len(T) - 1)])
    y = T[1:]
    if mask is not None:
        X, y = X[mask], y[mask]
    theta, resid = _lstsq(X, y)
    if f is not None:
        a, b, e, d = theta
    else:
        (a, b, d), e = theta, 0.0
    return ThermalParams(a=a, b=b, d=d, e=e, dt=dt), resid


def fit_with_H(T, u, nbr, dt: float, z_base: float, rho: float | None = None,
               rho_grid=None, mask=None, f=None) -> tuple[ThermalParams, np.ndarray]:
    """H を含むモデルを同定する。

    H は観測できないので、rho を固定すれば z から決定的に計算できる(lowpass_H)。
    その H を説明変数にして a, b, c, d(f を与えれば e も)を最小二乗で求める。
    rho を与えなければ rho_grid の中から1ステップ残差が最小のものを選ぶ。
    """
    T, u, nbr = (np.asarray(v, float) for v in (T, u, nbr))
    fcol = [np.asarray(f, float)[:-1]] if f is not None else []
    z = nbr - z_base
    rhos = [rho] if rho is not None else list(rho_grid if rho_grid is not None
                                             else np.linspace(0.5, 0.995, 100))
    best = None
    for r in rhos:
        H = lowpass_H(z, r)
        X = np.column_stack([T[:-1], u[:-1], H[:-1]] + fcol + [np.ones(len(T) - 1)])
        y = T[1:]
        if mask is not None:
            X, y = X[mask], y[mask]
        theta, resid = _lstsq(X, y)
        sse = float(resid @ resid)
        if best is None or sse < best[0]:
            best = (sse, r, theta, resid)
    _, r, theta, resid = best
    if f is not None:
        a, b, c, e, d = theta
    else:
        (a, b, c, d), e = theta, 0.0
    return ThermalParams(a=a, b=b, c=c, d=d, e=e, rho=r, z_base=z_base, dt=dt), resid


def warn_if_unphysical(p: ThermalParams, label: str = "") -> None:
    for msg in p.check():
        warnings.warn(f"[{label}] {msg}", stacklevel=2)
