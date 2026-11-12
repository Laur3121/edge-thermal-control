"""予測とマージンの評価指標。"""

from __future__ import annotations

import numpy as np


def prediction_metrics(T, pred, m: int, idx=None) -> dict:
    """pred[k](T[k+m] の予測)の誤差指標。idx で評価する k を絞れる。

    e = 実測 − 予測(正 = 予測が低すぎ = 危ない側)。
    """
    T, pred = np.asarray(T, float), np.asarray(pred, float)
    N = len(T)
    k = np.arange(N - m) if idx is None else np.asarray(idx)
    k = k[k < N - m]
    y, yh = T[k + m], pred[k]
    ok = ~np.isnan(yh)
    y, yh = y[ok], yh[ok]
    e = y - yh
    ss_tot = np.sum((y - y.mean()) ** 2)
    return {
        "n": int(len(e)),
        "bias": float(e.mean()),
        "MAE": float(np.abs(e).mean()),
        "RMSE": float(np.sqrt((e ** 2).mean())),
        "R2": float(1 - np.sum(e ** 2) / ss_tot) if ss_tot > 0 else float("nan"),
        "P97.7_err": float(np.quantile(e, 0.977)),
    }


def margin_metrics(T, pred, margin, m: int, tlimit: float, idx=None) -> dict:
    """マージンの指標(オフライン評価。ファンは実際には動かしていない前提)。

    exceed_rate:実測が「予測 + マージン」を上回った割合。α=2 で正しく較正されていれば約 2.3%。
    trigger_ratio:予測 > Tsafe(= Tlimit − M)となった割合(制御を発動する割合)。
    miss:実測 T[k+m] > Tlimit なのに、時刻 k で発動しなかった回数(見逃し)。
          IPSJ 版の miss_count は「同じ時刻」で比べていたので、Δ秒先の超過を予告できたかを数えていなかった。
    """
    T, pred = np.asarray(T, float), np.asarray(pred, float)
    margin = np.broadcast_to(np.asarray(margin, float), T.shape)
    N = len(T)
    k = np.arange(N - m) if idx is None else np.asarray(idx)
    k = k[k < N - m]
    y, yh, M = T[k + m], pred[k], margin[k]
    ok = ~(np.isnan(yh) | np.isnan(M))
    y, yh, M = y[ok], yh[ok], M[ok]
    trigger = yh > tlimit - M
    over = y > tlimit
    return {
        "n": int(len(y)),
        "mean_margin": float(M.mean()),
        "max_margin": float(M.max()),
        "min_margin": float(M.min()),
        "exceed_rate": float(np.mean(y > yh + M)),
        "trigger_ratio": float(trigger.mean()),
        "over_limit_count": int(over.sum()),
        "miss": int(np.sum(over & ~trigger)),
    }
