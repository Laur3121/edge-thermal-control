#!/usr/bin/env python3
"""囲いの中で「温度上昇を長く見る」+「ファン制御の比較」のシナリオ(2026-11-25 夜)。

11/25 の先生の指摘(温度上昇をもっと長く見せる/熱干渉 → 予測 → 稼働率の流れがない)に答える。
ラック(ポート側から見て):上段 r1 r2 r3 r4 / 下段 r5 r6 r7 r8。ファンは PoE+ HAT(段階 4)。

第 1 部 rise(温度上昇を長く見る):
  rise_pre   300 秒  全台アイドル、ファン OFF
  rise_load 2400 秒  下段 4 台に 4 コアの負荷、下段のファンは ON(OFF だと 83℃ で頭打ちになり測れないため)。
                     上段 4 台はアイドル・ファン OFF。上段の温度が 40 分の間に上がり続けるかを見る
  rise_rest  900 秒  全台アイドル、ファン OFF
第 2 部 ctrl(ファン制御の比較、--rise-only のときは作らない):
  8 台に同じ負荷パターン(11/14 の比較実験と同じ 20 分)を同時にかけ、8 台とも同じ方式でファンを決める。
  方式:常時 ON / しきい値(75℃ ON・70℃ OFF)/ 自ノードだけの予測 + 固定マージン / 提案(KF + H、動的マージン)
  休み 720 秒(負荷 0・ファン OFF)。2 巡、各巡の順番はランダム(seed 固定)

--no-fan r5 のように書くと、そのノードはファンを使わない(HAT が認識されないとき)。
そのノードには負荷をかけず、アイドルの熱源・測定点として置く。

使い方:
  python scripts/scenarios/gen_box_control.py [--no-fan r5] > scripts/scenarios/box_control.json
  python scripts/scenarios/gen_box_control.py --rise-only [--no-fan r5] > scripts/scenarios/rise_open.json
"""

import argparse
import json
import random

SEED = 20261125
ROLES = [f"r{i}" for i in range(1, 9)]
TOP, BOTTOM = ROLES[:4], ROLES[4:]
STAGE = 4
RISE_CORES, RISE_PRE, RISE_LOAD, RISE_REST = 4, 300, 2400, 900
CONDITIONS = {"always": 1, "threshold": "threshold", "selffixed": "self_fixed", "proposed": "proposed"}
PATTERN = [(1, 120), (4, 360), (0, 180), (4, 300), (2, 120), (4, 120)]  # 11/14 の比較実験と同じ
REST_S, ROUNDS = 720, 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fan", nargs="*", default=[])
    ap.add_argument("--rise-only", action="store_true")
    args = ap.parse_args()
    fan_roles = [r for r in ROLES if r not in args.no_fan]
    load_roles = fan_roles  # ファンを使えないノードには負荷をかけない

    def phase(name, dur, load, fan):
        return {"name": name, "duration_s": dur, "load": {r: load.get(r, 0) for r in ROLES},
                "fan": {r: fan.get(r, 0) for r in fan_roles}}

    phases = [{**phase("rise_pre", RISE_PRE, {}, {}), "fan_stage": {r: STAGE for r in fan_roles}},
              phase("rise_load", RISE_LOAD, {r: RISE_CORES for r in BOTTOM if r in load_roles},
                    {r: 1 for r in BOTTOM if r in fan_roles}),
              phase("rise_rest", RISE_REST, {}, {})]
    order = []
    if not args.rise_only:
        rng = random.Random(SEED)
        for k in range(1, ROUNDS + 1):
            names = list(CONDITIONS)
            rng.shuffle(names)
            order.append(names)
            for cond in names:
                for i, (cores, dur) in enumerate(PATTERN):
                    ph = {"name": f"c{k}_{cond}_s{i + 1}", "duration_s": dur,
                          "load": {r: (cores if r in load_roles else 0) for r in ROLES}}
                    if i == 0:
                        ph["fan"] = {r: CONDITIONS[cond] for r in fan_roles}
                    phases.append(ph)
                phases.append(phase(f"c{k}_{cond}_rest", REST_S, {}, {}))
    total = sum(p["duration_s"] for p in phases)
    sc = {"name": "rise_only" if args.rise_only else "box_control",
          "description": (f"温度上昇を長く見る(下段 {RISE_CORES} コア {RISE_LOAD} 秒、上段アイドル)"
                          + ("" if args.rise_only else
                             f" + ファン制御の比較 4 方式 × {ROUNDS} 巡(順番 {order}、seed={SEED})")
                          + f"。ファンなし:{args.no_fan or 'なし'}。合計 {total / 3600:.1f} 時間(落ち着き待ちを除く)"),
          "settle": {"window_s": 120, "max_slope_c_per_min": 0.2, "timeout_s": 1800},
          "control": {"tlimit": 80.0, "delta_s": 30.0, "alpha": 2.0, "delta_margin": 0.5, "hysteresis": 1.0,
                      "min_on_s": 30.0, "t_on": 75.0, "t_off": 70.0},
          "phases": phases}
    print(json.dumps(sc, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
