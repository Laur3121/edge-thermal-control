"""ファンの ON/OFF 制御則(閉ループ)。制御用 PC で 5 秒ごとに呼ぶ。

どの方式も、入力は「直近 dt 秒の平均」(温度・CPU 使用率・ファン状態)と室温。
予測を使う方式は、温度を室温からの上昇分 θ = T − T_amb で扱う(同定と同じ)。

判断(予測を使う方式に共通):
  「この先 Δ 秒ファンを OFF にしておいたら」の予測温度 T̂ を、今の負荷が続くと仮定して計算する。
  OFF のとき:T̂ > Tsafe なら ON
  ON のとき :最小 ON 時間が過ぎ、かつ T̂ < Tsafe − h なら OFF(h はヒステリシス幅)
  Tsafe = Tlimit − M。M は方式による:
    proposed   :KF の σ から M = α σ + δ
    self_fixed :Self-only(ARX)予測 + 固定マージン(同定データの誤差の 97.7% 分位点)
しきい値方式(threshold):今の温度 ≥ T_on で ON、≤ T_off で OFF(最小 ON 時間あり)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .kalman import NoiseParams, ThermalKF
from .model import ThermalParams

MODES = ("proposed", "self_fixed", "threshold")


@dataclass
class ControlConfig:
    tlimit: float = 80.0
    delta_s: float = 30.0  # 予測の先読み Δ [s]
    alpha: float = 2.0
    delta_margin: float = 0.5  # δ [℃]
    hysteresis: float = 1.0  # h [℃]
    min_on_s: float = 30.0  # 最小 ON 時間 [s]
    t_on: float = 75.0  # threshold 方式
    t_off: float = 70.0


@dataclass
class Decision:
    fan: int
    pred: float = float("nan")  # Δ 秒先・ファン OFF のときの予測温度 [℃](絶対温度)
    sigma: float = float("nan")
    margin: float = float("nan")
    tsafe: float = float("nan")
    reason: str = ""


@dataclass
class FanController:
    mode: str
    p: ThermalParams
    noise: NoiseParams
    cfg: ControlConfig = field(default_factory=ControlConfig)
    fixed_margin: float = float("nan")  # self_fixed 用

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"mode は {MODES} のどれか: {self.mode}")
        self.m = int(round(self.cfg.delta_s / self.p.dt))
        self.kf: ThermalKF | None = None
        self.prev: tuple[float, float] | None = None  # 前のステップの (u, f)
        self.fan = 0
        self.on_since: float | None = None

    def _predict_off(self, theta: float, u: float) -> tuple[float, float]:
        """Δ 秒先の θ の予測(ファン OFF・負荷は今の値が続く)と σ。"""
        if self.mode == "proposed":
            return self.kf.predict_ahead(self.m, u, nbr=self.p.z_base, f=0.0)
        p, x = self.p, theta
        for _ in range(self.m):
            x = p.a * x + p.b * u + p.d
        return x, float("nan")

    def step(self, t: float, T: float, u: float, f: float, T_amb: float) -> Decision:
        """t:時刻 [s]、T:直近 dt 秒の平均温度 [℃]、u:平均 CPU 使用率 [0,1]、f:平均ファン状態 [0,1]、T_amb:室温 [℃]。"""
        c = self.cfg
        theta = T - T_amb
        # KF は毎回更新しておく(方式によらず。ログ用にも使える)
        if self.kf is None:
            self.kf = ThermalKF(self.p, self.noise, T0=theta)
        else:
            u0, f0 = self.prev
            self.kf.step(theta, u0, self.p.z_base, f0)
        self.prev = (u, f)

        min_on_ok = self.on_since is None or t - self.on_since >= c.min_on_s
        if self.mode == "threshold":
            d = Decision(self.fan, tsafe=c.t_on)
            if self.fan == 0 and T >= c.t_on:
                d.fan, d.reason = 1, f"T {T:.1f} >= {c.t_on}"
            elif self.fan == 1 and min_on_ok and T <= c.t_off:
                d.fan, d.reason = 0, f"T {T:.1f} <= {c.t_off}"
        else:
            pred_th, sigma = self._predict_off(theta, u)
            if self.mode == "proposed":
                M = c.alpha * sigma + c.delta_margin
            else:
                M = self.fixed_margin
            pred = pred_th + T_amb
            tsafe = c.tlimit - M
            d = Decision(self.fan, pred=pred, sigma=sigma, margin=M, tsafe=tsafe)
            if self.fan == 0 and pred > tsafe:
                d.fan, d.reason = 1, f"pred {pred:.1f} > Tsafe {tsafe:.1f}"
            elif self.fan == 1 and min_on_ok and pred < tsafe - c.hysteresis:
                d.fan, d.reason = 0, f"pred {pred:.1f} < Tsafe-h {tsafe - c.hysteresis:.1f}"
        if d.fan != self.fan:
            self.on_since = t if d.fan == 1 else None
            self.fan = d.fan
        return d


def controller_from_dict(mode: str, node_params: dict, cfg: ControlConfig) -> FanController:
    """control_params.json の 1 ノード分から作る。"""
    s = node_params["self"]
    p = ThermalParams(a=s["a"], b=s["b"], d=s["d"], e=s["e"], c=0.0, dt=s["dt"])
    n = NoiseParams(R=node_params["R"], qT=node_params["qT"], qH0=0.0, beta=0.0)
    return FanController(mode, p, n, cfg, fixed_margin=node_params.get("fixed_margin", float("nan")))


def simulate(ctrl: FanController, p_true: ThermalParams, u_seq, T_amb: float, T0: float,
             noise_sd: float = 0.0, seed: int = 0):
    """真のモデル p_true の下で閉ループを回す(テスト・事前確認用)。戻り値は (T, fan)。"""
    rng = np.random.default_rng(seed)
    theta, T_log, f_log = T0 - T_amb, [], []
    f_cur = 0  # このステップの間のファン状態(1 つ前の判断。実機でも判断は次の区間から効く)
    for k, u in enumerate(u_seq):
        y = theta + T_amb + rng.normal(0, noise_sd)
        dec = ctrl.step(k * p_true.dt, y, u, f_cur, T_amb)
        T_log.append(theta + T_amb)
        f_log.append(f_cur)
        theta = p_true.a * theta + p_true.b * u + p_true.e * f_cur + p_true.d
        f_cur = dec.fan
    return np.array(T_log), np.array(f_log)
