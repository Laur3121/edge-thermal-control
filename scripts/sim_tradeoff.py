#!/usr/bin/env python3
"""案D:ファン稼働率と安全性の交換関係を、シミュレーションで方式ごとに描く(ノード A)。

公平にするための決めごと(結果を見る前に決めた、2026-11-14 夜):
- 実機役のモデル(plant)と制御器のモデルを別のデータで同定する。
  plant = 11/13 のステップ実験(案B、`experiments/20261113_step_identify/results/identify.json` の caseB)
  制御器 = 11/14 夜間データ(`scripts/control_params.json` の raspi1)
  同じモデルにすると予測が当たりすぎ、予測制御に有利になるため
- plant にはプロセスノイズ(11/14 の qT)と観測ノイズ(R)を入れる。乱数の seed は固定し、全方式で同じ乱数を使う
- 負荷パターン:①比較実験と同じパターン(20 分)②ランダム(区間 2〜10 分、0〜4 コア、seed 固定、各 3 時間)
- 室温 20℃、Tlimit 80℃。各方式で 1 つの設定値を動かして曲線にする
    threshold :T_on = 60〜79℃(T_off = T_on − 5)
    self_fixed:固定マージン 0〜8℃
    proposed  :α = 0〜5(δ = 0.5)
  ほかの設定(最小 ON 30 秒、ヒステリシス 1℃)は比較実験と同じ
- 指標:ファン稼働率、最高温度、80℃ 超過の秒数。結果は全点を載せる(有利な区間だけ切り取らない)

出力:experiments/20261114_sim_tradeoff/ に results.csv、図、README
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from etc.control import ControlConfig, controller_from_dict  # noqa: E402

DT = 5.0
T_AMB = 20.0
SEED = 20261114


def load_patterns():
    pats = {"compare": [(1, 120), (4, 360), (0, 180), (4, 300), (2, 120), (4, 120)]}
    rng = np.random.default_rng(SEED)
    for i in range(3):
        seq, total = [], 0
        while total < 3 * 3600:
            dur = int(rng.integers(2, 11)) * 60
            seq.append((int(rng.integers(0, 5)), dur))
            total += dur
        pats[f"random{i + 1}"] = seq
    return {k: np.concatenate([np.full(int(d / DT), c / 4) for c, d in v]) for k, v in pats.items()}


def simulate(plant, ctrl, u_seq, qT, R, rng_seed, fixed_fan=None):
    """plant を回し、5 秒ごとに制御器へ(ノイズ入りの)温度を渡す。fixed_fan を与えると制御器を使わない。"""
    rng = np.random.default_rng(rng_seed)
    a, b, e, d = plant["a"], plant["b"], plant["e"], plant["d"]
    theta = d / (1 - a)  # アイドル・ファン OFF の定常から始める
    f_cur, T, F = 0, [], []
    for k, u in enumerate(u_seq):
        y = theta + T_AMB + rng.normal(0, np.sqrt(R))
        if fixed_fan is None:
            dec = ctrl.step(k * DT, y, u, f_cur, T_AMB)
            nxt = dec.fan
        else:
            nxt = fixed_fan
        T.append(theta + T_AMB)
        F.append(f_cur)
        theta = a * theta + b * u + e * f_cur + d + rng.normal(0, np.sqrt(qT))
        f_cur = nxt
    T, F = np.array(T), np.array(F)
    return {"T_max": float(T.max()), "over80_s": float((T > 80).sum() * DT), "fan_ratio": float(F.mean()),
            "fan_on_count": int(np.sum(np.diff(np.r_[0, F]) == 1))}


def main():
    out = ROOT / "experiments" / "20261114_sim_tradeoff"
    out.mkdir(parents=True, exist_ok=True)
    plant = json.loads((ROOT / "experiments/20261113_step_identify/results/identify.json").read_text())["caseB"]
    cp = json.loads((ROOT / "scripts/control_params.json").read_text())["nodes"]["raspi1"]
    qT, R = cp["qT"], cp["R"]
    pats = load_patterns()
    rows = []
    sweeps = {"threshold": [("t_on", v) for v in np.arange(60, 80, 1.0)],
              "self_fixed": [("fixed_margin", v) for v in np.arange(0, 8.01, 0.5)],
              "proposed": [("alpha", v) for v in np.arange(0, 5.01, 0.25)]}
    for pname, u in pats.items():
        for mode, grid in sweeps.items():
            for key, val in grid:
                cfg = ControlConfig()
                if key == "t_on":
                    cfg.t_on, cfg.t_off = val, val - 5
                elif key == "alpha":
                    cfg.alpha = val
                ctrl = controller_from_dict(mode, cp, cfg)
                if key == "fixed_margin":
                    ctrl.fixed_margin = val
                r = simulate(plant, ctrl, u, qT, R, SEED)
                rows.append({"pattern": pname, "mode": mode, "param": key, "value": val, **r})
        for name, ff in (("nofan", 0), ("always", 1)):
            r = simulate(plant, None, u, qT, R, SEED, fixed_fan=ff)
            rows.append({"pattern": pname, "mode": name, "param": "", "value": np.nan, **r})
    df = pd.DataFrame(rows)
    df.to_csv(out / "results.csv", index=False, float_format="%.3f")

    fig, axes = plt.subplots(1, len(pats), figsize=(4 * len(pats), 3.6), sharey=True)
    styles = {"threshold": ("C3", "s", "Threshold (T_on 60–79 °C)"),
              "self_fixed": ("C1", "^", "Self-only + fixed margin (0–8 °C)"),
              "proposed": ("C0", "o", "Proposed (α 0–5)")}
    for ax, pname in zip(axes, pats):
        g = df[df.pattern == pname]
        for mode, (c, mk, lab) in styles.items():
            h = g[g["mode"] == mode].sort_values("fan_ratio")
            ax.plot(h.fan_ratio * 100, h.T_max, marker=mk, ms=3, lw=0.8, color=c, label=lab)
        for name, mk in (("nofan", "x"), ("always", "D")):
            h = g[g["mode"] == name]
            ax.plot(h.fan_ratio * 100, h.T_max, mk, color="k", label={"nofan": "No fan", "always": "Always on"}[name])
        ax.axhline(80, color="r", lw=0.8)
        ax.set_title(f"Load pattern: {pname}", fontsize=9)
        ax.set_xlabel("Fan duty ratio [%]")
    axes[0].set_ylabel("Max CPU temperature [°C]")
    axes[0].legend(fontsize=6.5)
    fig.suptitle("Simulation (node A): plant identified on 11/13, controller on 11/14", fontsize=9)
    fig.tight_layout()
    fig.savefig(out / "tradeoff.png", dpi=150)

    # 80℃ を超えない設定の中で、稼働率が最小のもの
    ok = df[(df.over80_s == 0) & df["mode"].isin(styles)]
    best = ok.loc[ok.groupby(["pattern", "mode"]).fan_ratio.idxmin()]
    print(best[["pattern", "mode", "value", "fan_ratio", "T_max", "fan_on_count"]].to_string(index=False, float_format="%.3f"))
    print(df[df["mode"].isin(["nofan", "always"])][["pattern", "mode", "fan_ratio", "T_max"]].to_string(index=False))


if __name__ == "__main__":
    main()
