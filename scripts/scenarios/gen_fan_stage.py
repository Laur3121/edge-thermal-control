#!/usr/bin/env python3
"""ファンの段階を下げたときの比較のシナリオ(2026-11-23 夜中に実行)。

条件:しきい値 75/70℃ で ON は段階 4(11/14 と同じ)/ しきい値で ON は段階 2 / 常時 ON で段階 1
負荷パターン・休み(ファン OFF)・3 台同時は 11/14 の比較実験と同じ。3 巡、順番はラテン方格(最初の巡だけ乱数)。
使い方:python scripts/scenarios/gen_fan_stage.py > scripts/scenarios/fan_stage.json
"""

import json
import random

from gen_compare import PATTERN, REST_S, ROLES, ROUNDS

SEED = 20261123
CONDITIONS = {"thr_s4": ("threshold", 4), "thr_s2": ("threshold", 2), "alw_s1": (1, 1)}


def main():
    rng = random.Random(SEED)
    first = list(CONDITIONS)
    rng.shuffle(first)
    phases = [{"name": "p0_baseline", "duration_s": 300, "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES},
               "fan_stage": {r: 4 for r in ROLES}}]
    order = []
    for k in range(1, ROUNDS + 1):
        names = first[k - 1:] + first[:k - 1]
        order.append(names)
        for cond in names:
            fan, stage = CONDITIONS[cond]
            for i, (cores, dur) in enumerate(PATTERN):
                ph = {"name": f"r{k}_{cond}_s{i + 1}", "duration_s": dur, "load": {r: cores for r in ROLES}}
                if i == 0:
                    ph["fan_stage"] = {r: stage for r in ROLES}
                    ph["fan"] = {r: fan for r in ROLES}
                phases.append(ph)
            phases.append({"name": f"r{k}_{cond}_rest", "duration_s": REST_S, "load": {r: 0 for r in ROLES},
                           "fan": {r: 0 for r in ROLES}, "fan_stage": {r: 4 for r in ROLES}})
    sc = {"name": "fan_stage",
          "description": f"ファンの段階の比較(seed={SEED})。条件 {CONDITIONS}。順番はラテン方格:{order}。負荷パターン={PATTERN}",
          "settle": {"window_s": 120, "max_slope_c_per_min": 0.2, "timeout_s": 1800},
          "control": {"tlimit": 80.0, "delta_s": 30.0, "alpha": 2.0, "delta_margin": 0.5, "hysteresis": 1.0,
                      "min_on_s": 30.0, "t_on": 75.0, "t_off": 70.0},
          "phases": phases}
    print(json.dumps(sc, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
