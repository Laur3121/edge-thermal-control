"""比較手法(Self-only 予測、坂本型の補正とマージン、固定マージン)。

どの手法も、時刻 k の予測には時刻 k までの情報だけを使う(未来の入力や未確定の誤差は使わない)。
"""

from __future__ import annotations

import numpy as np

from .model import ThermalParams


def predict_arx(p: ThermalParams, T, u, m: int, nbr=None):
    """ARX モデルで m ステップ先を予測する。未来の u(と隣接温度)は現在の値が続くと仮定。

    p.c != 0 かつ nbr を与えた場合は H を決定的に回す(KF を使わない「H 入り ARX」)。
    """
    T, u = np.asarray(T, float), np.asarray(u, float)
    N = len(T)
    use_H = nbr is not None and p.c != 0.0
    if use_H:
        z = np.asarray(nbr, float) - p.z_base
        H = np.zeros(N)
        for k in range(N - 1):
            H[k + 1] = p.rho * H[k] + (1 - p.rho) * z[k]
    pred = np.empty(N)
    for k in range(N):
        Tk = T[k]
        Hk = H[k] if use_H else 0.0
        for _ in range(m):
            Tk_next = p.a * Tk + p.b * u[k] + p.d + (p.c * Hk if use_H else 0.0)
            if use_H:
                Hk = p.rho * Hk + (1 - p.rho) * z[k]
            Tk = Tk_next
        pred[k] = Tk
    return pred


def realized_errors(T, pred, m: int):
    """e[k] = T[k+m] - pred[k]。e[k] が分かるのは時刻 k+m。末尾 m 個は NaN。"""
    T = np.asarray(T, float)
    e = np.full(len(T), np.nan)
    e[: len(T) - m] = T[m:] - pred[: len(T) - m]
    return e


def sakamoto_like(T, pred_self, m: int, window: int, k_margin: float = 2.0):
    """坂本型:過去の予測誤差の平均で予測を補正し、標準偏差の k 倍をマージンにする。

    時刻 k で使える誤差は e[j](j <= k - m)だけ。そのうち直近 window 個を使う。
    誤差が2個未満の区間は補正 0・マージン NaN。
    """
    e = realized_errors(T, pred_self, m)
    N = len(T)
    pred = np.array(pred_self, float)
    margin = np.full(N, np.nan)
    for k in range(N):
        hi = k - m + 1  # e[0..k-m] が確定済み
        lo = max(0, hi - window)
        past = e[lo:hi] if hi > 0 else np.empty(0)
        past = past[~np.isnan(past)]
        if len(past) >= 2:
            pred[k] = pred_self[k] + past.mean()
            margin[k] = k_margin * past.std(ddof=1)
    return pred, margin


def fixed_margin_from(errors, q: float) -> float:
    """同定用データの予測誤差 e = 実測 − 予測 の上側 q 分位点を固定マージンにする。

    q = 0.977 は「正規分布の 2σ を上に超える確率 2.3%」と同じ安全度にそろえるため。
    """
    e = np.asarray(errors, float)
    return float(np.quantile(e[~np.isnan(e)], q))
