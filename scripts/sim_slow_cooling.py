#!/usr/bin/env python3
"""冷却の効きの遅さを変えたシミュレーション(ノード A)。

条件は結果を見る前に決め、experiments/20261122_sim_slow_cooling/README.md に書いた(2026-11-22)。
sim_tradeoff.py(11/14)と同じ実機役・制御器・ノイズ・負荷に、ファンの効きの遅れを足す。

遅れ:
  dead:むだ時間 L 秒。指令が L 秒後に効き始める
  lag :1 次遅れ τ_f 秒。冷却の効きが時定数 τ_f で立ち上がる・下がる
制御器は遅れを知っている:
  先読み Δ = 30 + L(または 30 + τ_f)、判断には先読みの間の予測温度の最大値を使う
  予測は「今の指令から先は OFF」。すでに出した指令と冷却の残りは含める
  (遅れ 0 のときは control.py の FanController と同じ判断になるように、
   今の区間の冷却も OFF とみなす近似をそのまま使う)
  カルマンフィルタと ARX の入力には、実際に効いている冷却の量を使う
c = 0(干渉なし)なので、提案手法のカルマンフィルタは温度だけの 1 次元になる。

出力:experiments/20261122_sim_slow_cooling/ に results.csv、summary.csv、図
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from sim_tradeoff import DT, SEED, T_AMB, load_patterns  # noqa: E402

OUT = ROOT / "experiments" / "20261122_sim_slow_cooling"
TLIMIT, HYST, MIN_ON_STEPS, DELTA0 = 80.0, 1.0, 6, 30.0
DELAYS = [("dead", L) for L in (0, 15, 30, 60, 90, 120)] + [("lag", t) for t in (0, 30, 60, 120, 240)]
SWEEPS = {"threshold": np.arange(40, 80, 1.0),
          "self_fixed": np.arange(0, 20.01, 0.5),
          "proposed": np.arange(0, 12.01, 0.25)}
DELTA_MARGIN = 0.5


def load_models():
    plant = json.loads((ROOT / "experiments/20261113_step_identify/results/identify.json").read_text())["caseB"]
    cp = json.loads((ROOT / "scripts/control_params.json").read_text())["nodes"]["raspi1"]
    return plant, cp


def simulate(plant, cp, u_seq, kind, delay_s, mode, val, fixed_fan=None, rule="off"):
    """1 本の閉ループ。mode:threshold / self_fixed / proposed、val:その方式の設定値。

    rule(予測を使う方式の判断):
      off :事前に決めた判断。「今の指令から先、先読みの間ずっと OFF にしたら」(先読み 30 + 遅れ)
      next:事後の追加(11/22、off の結果を見てから追加)。「今は OFF、次の区間から ON にしたら」
            それでも Tsafe を超えるなら今 ON にする(ぎりぎりまで待つ判断)。先読みは 30 + 3 × 遅れ
    """
    rng = np.random.default_rng(SEED)
    qT, R = cp["qT"], cp["R"]
    pa, pb, pe, pd_ = plant["a"], plant["b"], plant["e"], plant["d"]
    s = cp["self"]
    a, b, e, d = s["a"], s["b"], s["e"], s["d"]
    Ld = int(round(delay_s / DT)) if kind == "dead" else 0
    lam = 1.0 if (kind == "dead" or delay_s == 0) else 1 - np.exp(-DT / delay_s)
    m = int(round((DELTA0 + (3 * delay_s if rule == "next" else delay_s)) / DT))
    j = np.arange(1, m + 1)
    pw = a ** j                                  # a^j
    sj = (1 - a ** j) / (1 - a)                  # Σ_{i<j} a^i
    K = np.tril(a ** np.clip(j[:, None] - 1 - np.arange(m)[None, :], 0, None)) * (np.arange(m)[None, :] < j[:, None])

    theta = pd_ / (1 - pa)
    n = len(u_seq)
    dec = np.zeros(n, dtype=int)                 # 各ステップの指令
    eff = 0.0                                    # 今の区間に効いている冷却の量
    g = 0.0                                      # 1 次遅れの状態
    fan_now, on_k = 0, None
    x_hat, P, prev = None, None, None
    Tlog, Elog, Clog = np.empty(n), np.empty(n), np.empty(n)
    for k in range(n):
        u = u_seq[k]
        y = theta + T_AMB + rng.normal(0, np.sqrt(R))
        th_meas = y - T_AMB
        # 推定(提案)
        if x_hat is None:
            x_hat, P = th_meas, R
        else:
            u0, e0 = prev
            x_hat = a * x_hat + b * u0 + d + e * e0
            P = a * a * P + qT
            Kg = P / (P + R)
            x_hat += Kg * (th_meas - x_hat)
            P *= 1 - Kg
        prev = (u, eff)

        if fixed_fan is not None:
            nxt = fixed_fan
        else:
            min_ok = on_k is None or k - on_k >= MIN_ON_STEPS
            if mode == "threshold":
                T = y
                nxt = fan_now
                if fan_now == 0 and T >= val:
                    nxt = 1
                elif fan_now == 1 and min_ok and T <= val - 5:
                    nxt = 0
            else:
                # 先読みの間の冷却(今の指令から先は OFF)
                effv = np.zeros(m)
                # 区間 k(今の区間)は「OFF とみなす」近似(遅れ 0 の FanController と同じ扱い)
                effv = np.zeros(m)
                if kind == "dead":
                    # 区間 k+jj に効くのは指令 dec[k+jj-1-Ld]。jj = 1..Ld はすでに出した指令
                    if Ld > 0:
                        jj = np.arange(1, min(Ld, m - 1) + 1)
                        idx = k + jj - 1 - Ld
                        effv[jj] = np.where(idx >= 0, dec[np.clip(idx, 0, None)], 0)
                    if rule == "next":
                        effv[Ld + 2:] = 1.0          # 指令 k は OFF、k+1 以降は ON
                else:
                    gg = g
                    for jj in range(1, m):
                        cmd = 0.0 if (jj == 1 or rule == "off") else 1.0
                        gg = gg + lam * (cmd - gg)
                        effv[jj] = gg
                x0 = x_hat if mode == "proposed" else th_meas
                traj = pw * x0 + sj * (b * u + d) + e * (K @ effv)
                jmax = int(traj.argmax()) if rule == "next" else m - 1
                pred = traj.max() + T_AMB
                if mode == "proposed":
                    jm = jmax + 1
                    sigma = np.sqrt(a ** (2 * jm) * P + qT * (1 - a ** (2 * jm)) / (1 - a ** 2))
                    M = val * sigma + DELTA_MARGIN
                else:
                    M = val
                tsafe = TLIMIT - M
                nxt = fan_now
                if fan_now == 0 and pred > tsafe:
                    nxt = 1
                elif fan_now == 1 and min_ok and pred < tsafe - HYST:
                    nxt = 0
        if nxt != fan_now:
            on_k = k if nxt == 1 else None
            fan_now = nxt
        dec[k] = nxt
        Tlog[k], Elog[k], Clog[k] = theta + T_AMB, eff, dec[k - 1] if k > 0 else 0
        theta = pa * theta + pb * u + pe * eff + pd_ + rng.normal(0, np.sqrt(qT))
        # 次の区間に効く冷却
        if kind == "dead":
            src = k - Ld
            eff = float(dec[src]) if src >= 0 else 0.0
        else:
            g = g + lam * (dec[k] - g)
            eff = g
    # 稼働率は「ファンを回した指令の割合」(電力・寿命に効くのは指令側)
    return {"T_max": float(Tlog.max()), "over80_s": float((Tlog > 80).sum() * DT),
            "fan_ratio": float(Clog.mean()), "fan_on_count": int(np.sum(np.diff(np.r_[0, Clog]) == 1))}


def run_condition(args):
    kind, delay, rule = args
    plant, cp = load_models()
    pats = load_patterns()
    rows = []
    for pname, u in pats.items():
        for mode, grid in SWEEPS.items():
            for val in grid:
                r = simulate(plant, cp, u, kind, delay, mode, float(val), rule=rule)
                rows.append({"rule": rule, "kind": kind, "delay_s": delay, "pattern": pname, "mode": mode, "value": float(val), **r})
        for name, ff in (("nofan", 0), ("always", 1)):
            r = simulate(plant, cp, u, kind, delay, name, np.nan, fixed_fan=ff)
            rows.append({"rule": rule, "kind": kind, "delay_s": delay, "pattern": pname, "mode": name, "value": np.nan, **r})
    return rows


def summarize(df):
    ok = df[(df.over80_s == 0) & df["mode"].isin(SWEEPS)]
    idx = ok.groupby(["rule", "kind", "delay_s", "pattern", "mode"]).fan_ratio.idxmin()
    best = ok.loc[idx, ["rule", "kind", "delay_s", "pattern", "mode", "value", "fan_ratio", "T_max"]]
    piv = best.pivot_table(index=["rule", "kind", "delay_s", "pattern"], columns="mode", values="fan_ratio")
    piv = piv.reindex(columns=list(SWEEPS))
    keys = ["rule", "kind", "delay_s", "pattern"]
    full = df[keys].drop_duplicates().set_index(keys)
    piv = full.join(piv)
    pred_best = piv[["self_fixed", "proposed"]].min(axis=1)
    piv["gain_pt"] = (piv["threshold"] - pred_best) * 100
    piv["pred_effective"] = piv["threshold"].isna() & pred_best.notna() | (piv["gain_pt"] >= 5)
    return best, piv.reset_index()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor() as ex:
        rows = [r for part in ex.map(run_condition, [(k, d, r) for r in ("off", "next") for k, d in DELAYS]) for r in part]
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "results.csv", index=False, float_format="%.4f")
    best, piv = summarize(df)
    best.to_csv(OUT / "best_settings.csv", index=False, float_format="%.4f")
    piv.to_csv(OUT / "summary.csv", index=False, float_format="%.4f")
    with pd.option_context("display.width", 200, "display.max_rows", 200):
        print(piv.to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
