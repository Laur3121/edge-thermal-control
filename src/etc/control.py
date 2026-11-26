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

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .kalman import NoiseParams, ThermalKF
from .model import ThermalParams

MODES = ("proposed", "self_fixed", "threshold", "proposed_ms", "proposed_hr")
# proposed_hr(11/26 追加):ファンの余力を見る。次のどちらかなら「余力なし」として ON にし、止めない。
#   (1) モデル:今の負荷・H のままファンを回し続けたときの定常温度 T_on = (b u + c H + e + d)/(1 − a) + 室温 が Tsafe − hr_margin を超える
#   (2) 実測:ファンを hr_on_s 秒以上回しているのに、温度が Tsafe − hr_margin より高い(モデルが囲いの温まりを拾いきれないため)
# 余力があるときは proposed と同じ
# proposed_ms(11/26 追加):ファンの段階 1〜4 ごとに「その段階で回したら Δ 秒先は何℃か」を予測し、
# Tsafe を下回る一番弱い段階を選ぶ。段階 s の効きは e × stage_eff[s](stage_eff[4] = 1、同定した相対値)


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
    hr_margin: float = 2.0  # proposed_hr:ファン ON の定常温度がこれだけ Tsafe に近づいたら余力なしとみなす [℃]
    hr_on_s: float = 60.0  # proposed_hr:ファンをこの秒数回しても下がらなければ余力なしとみなす
    fan_delay_s: float = 0.0  # ファンの指令が効くまでの遅れ L [s](11/26 追加。実験で指令をわざと遅らせる)
    # L > 0 のとき、予測を使う方式は先読みを Δ + L にし、すでに出した指令(L 秒のうちに効くもの)を予測に入れ、
    # 先読みの間の予測の最大値で判断する(11/22 のシミュレーション sim_slow_cooling.py の rule "off" と同じ)


@dataclass
class Decision:
    fan: int
    pred: float = float("nan")  # Δ 秒先・ファン OFF のときの予測温度 [℃](絶対温度)
    sigma: float = float("nan")
    margin: float = float("nan")
    tsafe: float = float("nan")
    reason: str = ""
    stage: int | None = None  # proposed_ms のとき選んだ段階(0 = OFF)


@dataclass
class FanController:
    mode: str
    p: ThermalParams
    noise: NoiseParams
    cfg: ControlConfig = field(default_factory=ControlConfig)
    fixed_margin: float = float("nan")  # self_fixed 用
    stage_eff: tuple = (0.0, 0.25, 0.5, 0.75, 1.0)  # proposed_ms 用:段階 0〜4 の相対的な効き

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"mode は {MODES} のどれか: {self.mode}")
        self.Ld = int(round(self.cfg.fan_delay_s / self.p.dt))
        self.m = int(round((self.cfg.delta_s + self.cfg.fan_delay_s) / self.p.dt))
        if self.Ld > 0 and self.mode in ("proposed_ms", "proposed_hr"):
            raise ValueError("fan_delay_s > 0 は proposed・self_fixed・threshold だけ")
        self.hist = deque([0] * self.Ld, maxlen=self.Ld) if self.Ld > 0 else None  # 直近 Ld 回の指令(古い順)
        self.kf: ThermalKF | None = None
        self.prev: tuple[float, float, float] | None = None  # 前のステップの (u, f, 隣の温度 − 室温)
        self.fan = 0
        self.stage = 0
        self.on_since: float | None = None
        self.changed_at: float | None = None

    def _predict_off(self, theta: float, u: float, nbr: float) -> tuple[float, float]:
        """Δ 秒先の θ の予測(ファン OFF・負荷と隣の温度は今の値が続く)と σ。"""
        if self.Ld > 0:
            # 遅れあり:0 ステップ目は OFF とみなし(遅れ 0 と同じ近似)、1〜Ld ステップ目はすでに出した指令が効く。
            # その先(今の指令から後)は OFF。先読みの間の最大値を返す
            fs = [0.0] + [float(v) for v in self.hist] + [0.0] * (self.m - 1 - self.Ld)
            fs = fs[:self.m]
            if self.mode == "proposed":
                means, sigma = self.kf.predict_path(fs, u, nbr)
                return float(means.max()), sigma
            p, x, mx = self.p, theta, -np.inf
            for f in fs:
                x = p.a * x + p.b * u + p.d + p.e * f
                mx = max(mx, x)
            return float(mx), float("nan")
        if self.mode in ("proposed", "proposed_ms", "proposed_hr"):
            return self.kf.predict_ahead(self.m, u, nbr=nbr, f=0.0)
        p, x = self.p, theta
        for _ in range(self.m):
            x = p.a * x + p.b * u + p.d
        return x, float("nan")

    def step(self, t: float, T: float, u: float, f: float, T_amb: float,
             T_nbr: float | None = None) -> Decision:
        """t:時刻 [s]、T:直近 dt 秒の平均温度 [℃]、u:平均 CPU 使用率 [0,1]、f:平均ファン状態 [0,1]、T_amb:室温 [℃]。
        T_nbr:隣のノードの平均温度 [℃](H の入力。None なら z_base = 隣の影響なし。2026-11-25 追加)。"""
        c = self.cfg
        theta = T - T_amb
        nbr = self.p.z_base if T_nbr is None else T_nbr - T_amb
        # KF は毎回更新しておく(方式によらず。ログ用にも使える)
        if self.kf is None:
            self.kf = ThermalKF(self.p, self.noise, T0=theta)
        else:
            u0, f0, n0 = self.prev
            self.kf.step(theta, u0, n0, f0)
        # proposed_ms は段階ごとに効きが違うので、KF に入れるファンの入力は「今の段階の相対的な効き」
        self.prev = (u, self.stage_eff[self.stage] if self.mode == "proposed_ms" else f, nbr)

        if self.mode == "proposed_ms":
            return self._step_ms(t, T, u, nbr, T_amb)

        min_on_ok = self.on_since is None or t - self.on_since >= c.min_on_s
        if self.mode == "threshold":
            d = Decision(self.fan, tsafe=c.t_on)
            if self.fan == 0 and T >= c.t_on:
                d.fan, d.reason = 1, f"T {T:.1f} >= {c.t_on}"
            elif self.fan == 1 and min_on_ok and T <= c.t_off:
                d.fan, d.reason = 0, f"T {T:.1f} <= {c.t_off}"
        else:
            pred_th, sigma = self._predict_off(theta, u, nbr)
            if self.mode in ("proposed", "proposed_hr"):
                M = c.alpha * sigma + c.delta_margin
            else:
                M = self.fixed_margin
            pred = pred_th + T_amb
            tsafe = c.tlimit - M
            d = Decision(self.fan, pred=pred, sigma=sigma, margin=M, tsafe=tsafe)
            no_headroom = False
            if self.mode == "proposed_hr":
                p, H = self.p, float(self.kf.x[1])
                T_on = (p.b * u + p.c * H + p.e + p.d) / (1 - p.a) + T_amb  # ファンを回し続けたときの定常温度
                on_for = t - self.on_since if (self.fan == 1 and self.on_since is not None) else 0.0
                by_model = T_on > tsafe - c.hr_margin
                by_meas = on_for >= c.hr_on_s and T > tsafe - c.hr_margin
                no_headroom = by_model or by_meas
            if no_headroom:
                if self.fan == 0:
                    d.fan, d.reason = 1, f"余力なし(モデル) T_on {T_on:.1f} > {tsafe - c.hr_margin:.1f}"
                elif by_meas and not by_model:
                    d.reason = f"余力なし(実測) T {T:.1f} > {tsafe - c.hr_margin:.1f}、ON {on_for:.0f} 秒"
            elif self.fan == 0 and pred > tsafe:
                d.fan, d.reason = 1, f"pred {pred:.1f} > Tsafe {tsafe:.1f}"
            elif self.fan == 1 and min_on_ok and pred < tsafe - c.hysteresis:
                d.fan, d.reason = 0, f"pred {pred:.1f} < Tsafe-h {tsafe - c.hysteresis:.1f}"
        if d.fan != self.fan:
            self.on_since = t if d.fan == 1 else None
            self.fan = d.fan
        if self.hist is not None:
            self.hist.append(d.fan)
        return d


    def _step_ms(self, t: float, T: float, u: float, nbr: float, T_amb: float) -> Decision:
        """段階を選ぶ。上げるのはすぐ、下げるのは最小保持時間が過ぎ、下げた段階でも Tsafe − h を下回るときだけ。"""
        c = self.cfg
        _, sigma = self.kf.predict_ahead(self.m, u, nbr=nbr, f=0.0)
        M = c.alpha * sigma + c.delta_margin
        tsafe = c.tlimit - M
        preds = [self.kf.predict_ahead(self.m, u, nbr=nbr, f=self.stage_eff[s])[0] + T_amb for s in range(5)]
        need = next((s for s in range(5) if preds[s] <= tsafe), 4)  # Tsafe 以下に収まる一番弱い段階
        hold_ok = self.changed_at is None or t - self.changed_at >= c.min_on_s
        new = self.stage
        reason = ""
        if need > self.stage:
            new, reason = need, f"pred(s{self.stage}) {preds[self.stage]:.1f} > Tsafe {tsafe:.1f} → s{need}"
        elif need < self.stage and hold_ok:
            lower = next((s for s in range(self.stage) if preds[s] <= tsafe - c.hysteresis), self.stage)
            if lower < self.stage:
                new, reason = lower, f"pred(s{lower}) {preds[lower]:.1f} < Tsafe-h {tsafe - c.hysteresis:.1f} → s{lower}"
        if new != self.stage:
            self.stage, self.changed_at = new, t
        self.fan = int(self.stage > 0)
        return Decision(self.fan, pred=preds[0], sigma=sigma, margin=M, tsafe=tsafe, reason=reason, stage=self.stage)


def controller_from_dict(mode: str, node_params: dict, cfg: ControlConfig) -> FanController:
    """control_params.json の 1 ノード分から作る。
    proposed で node_params に "withH"(c, rho, z_base を含む)があればそれを使う(H あり、2026-11-25 追加)。
    """
    s = node_params["self"]
    if mode in ("proposed", "proposed_ms", "proposed_hr") and "withH" in node_params:
        h = node_params["withH"]
        p = ThermalParams(a=h["a"], b=h["b"], d=h["d"], e=h["e"], c=h["c"], rho=h["rho"], z_base=h["z_base"],
                          dt=h["dt"])
        n = NoiseParams(R=node_params["R"], qT=node_params["qT_H"], qH0=node_params.get("qH0", 0.008),
                        beta=node_params.get("beta", 2.0))
        eff = tuple(node_params.get("stage_eff", (0.0, 0.25, 0.5, 0.75, 1.0)))
        return FanController(mode, p, n, cfg, stage_eff=eff)
    p = ThermalParams(a=s["a"], b=s["b"], d=s["d"], e=s["e"], c=0.0, dt=s["dt"])
    n = NoiseParams(R=node_params["R"], qT=node_params["qT"], qH0=0.0, beta=0.0)
    return FanController(mode, p, n, cfg, fixed_margin=node_params.get("fixed_margin", float("nan")))


def simulate(ctrl: FanController, p_true: ThermalParams, u_seq, T_amb: float, T0: float,
             noise_sd: float = 0.0, seed: int = 0, delay_steps: int = 0):
    """真のモデル p_true の下で閉ループを回す(テスト・事前確認用)。戻り値は (T, fan(効いていた状態), cmd(指令))。
    delay_steps:指令が効くまでの遅れ [ステップ](11/26 追加)。判断は次の区間から効き、さらに delay_steps 遅れる。"""
    rng = np.random.default_rng(seed)
    theta, T_log, f_log, c_log = T0 - T_amb, [], [], []
    f_cur = 0  # このステップの間のファン状態(1 つ前の判断。実機でも判断は次の区間から効く)
    cmds = []
    for k, u in enumerate(u_seq):
        y = theta + T_amb + rng.normal(0, noise_sd)
        dec = ctrl.step(k * p_true.dt, y, u, f_cur, T_amb)
        T_log.append(theta + T_amb)
        f_log.append(f_cur)
        theta = p_true.a * theta + p_true.b * u + p_true.e * f_cur + p_true.d
        cmds.append(dec.fan)
        c_log.append(dec.fan)
        src = len(cmds) - 1 - delay_steps
        f_cur = cmds[src] if src >= 0 else 0
    return np.array(T_log), np.array(f_log), np.array(c_log)
