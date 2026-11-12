"""ログの読み込みと等間隔化。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def load_node_log(csv_path, host: str | None = None) -> pd.DataFrame:
    """収集ログ(ts, temp, cpu_percent, ...)を読み、時刻順に並べる。

    host を指定すると、その host の行だけを使う(8台分が1ファイルのログ用)。
    """
    df = pd.read_csv(csv_path, low_memory=False)
    if host is not None and "host" in df.columns:
        df = df[df["host"] == host].copy()
    for col in ("ts", "temp", "cpu_percent"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["ts", "temp", "cpu_percent"])
    df = df.sort_values("ts").reset_index(drop=True)
    if len(df) < 10:
        raise ValueError(f"not enough samples in {csv_path} (host={host})")
    return df


@dataclass
class Series:
    """等間隔化した対象ノードと隣接ノードの時系列。

    t:   時刻 [s](先頭を 0)
    T:   対象ノードの温度 [℃]
    u:   対象ノードの CPU 使用率 [0, 1]
    nbr: 隣接ノードの温度 [℃]
    dt:  刻み [s]
    """

    t: np.ndarray
    T: np.ndarray
    u: np.ndarray
    nbr: np.ndarray
    dt: float

    def __len__(self) -> int:
        return len(self.t)

    def slice(self, start: int, stop: int) -> "Series":
        s = slice(start, stop)
        return Series(self.t[s], self.T[s], self.u[s], self.nbr[s], self.dt)


def align(target: pd.DataFrame, neighbor: pd.DataFrame, dt: float | None = None) -> Series:
    """対象と隣接のログを共通の等間隔時刻に線形補間でそろえる。

    dt を省略すると、両ログのサンプル間隔の中央値を使う。
    """
    t1 = target["ts"].to_numpy(float)
    t2 = neighbor["ts"].to_numpy(float)
    if dt is None:
        diffs = np.concatenate([np.diff(t1), np.diff(t2)])
        dt = float(np.median(diffs[diffs > 0]))
    start, end = max(t1[0], t2[0]), min(t1[-1], t2[-1])
    if end <= start:
        raise ValueError("target and neighbor logs do not overlap")
    tg = np.arange(start, end + 1e-9, dt)
    T = np.interp(tg, t1, target["temp"].to_numpy(float))
    u = np.interp(tg, t1, target["cpu_percent"].to_numpy(float) / 100.0).clip(0.0, 1.0)
    nbr = np.interp(tg, t2, neighbor["temp"].to_numpy(float))
    return Series(tg - tg[0], T, u, nbr, float(dt))
