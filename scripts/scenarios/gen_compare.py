#!/usr/bin/env python3
"""比較実験(閉ループ)のシナリオを作る。

- 条件:ファンなし(0)/ 常時 ON(1)/ しきい値 ON-OFF / Self-only 予測 + 固定マージン / 提案手法
- 3 台(A・B・C)に同じ条件・同じ負荷パターンを同時にかける(干渉はほぼないので、3 台をそれぞれ 1 回の試行として数える)
- 1 条件 = 負荷パターン 20 分 + 休み 12 分(負荷 0・ファン OFF。時定数 約 65〜100 秒の 7 倍以上で、開始時の温度がそろう)
- 3 巡。各巡の条件の順番はランダム(seed 固定)

使い方:python scripts/scenarios/gen_compare.py > scripts/scenarios/compare.json
"""

import json
import random

SEED = 20261114
CONDITIONS = {"nofan": 0, "always": 1, "threshold": "threshold", "selffixed": "self_fixed", "proposed": "proposed"}
# 負荷パターン(コア数、秒)。ファンなしだと A は 80℃ を超える(室温 20℃ で 4 コア定常 約 86℃)
PATTERN = [(1, 120), (4, 360), (0, 180), (4, 300), (2, 120), (4, 120)]
REST_S = 720
ROUNDS = 3
ROLES = ("A", "B", "C")


def main():
    rng = random.Random(SEED)
    phases = [{"name": "p0_baseline", "duration_s": 300, "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES}}]
    order = []
    for k in range(1, ROUNDS + 1):
        names = list(CONDITIONS)
        rng.shuffle(names)
        order.append(names)
        for cond in names:
            fan = CONDITIONS[cond]
            for i, (cores, dur) in enumerate(PATTERN):
                ph = {"name": f"r{k}_{cond}_s{i + 1}", "duration_s": dur, "load": {r: cores for r in ROLES}}
                if i == 0:
                    ph["fan"] = {r: fan for r in ROLES}
                phases.append(ph)
            phases.append({"name": f"r{k}_{cond}_rest", "duration_s": REST_S,
                           "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES}})
    total = sum(p["duration_s"] for p in phases)
    sc = {
        "name": "compare",
        "description": (f"比較実験(seed={SEED}、scripts/scenarios/gen_compare.py で生成)。5 条件 × {ROUNDS} 巡、"
                        f"各巡の順番はランダム:{order}。3 台に同じ条件・同じ負荷。"
                        f"負荷パターン(コア数, 秒)={PATTERN}、休み {REST_S} 秒。合計 約 {total / 3600:.1f} 時間"),
        "settle": {"window_s": 120, "max_slope_c_per_min": 0.2, "timeout_s": 1800},
        "control": {"tlimit": 80.0, "delta_s": 30.0, "alpha": 2.0, "delta_margin": 0.5, "hysteresis": 1.0,
                    "min_on_s": 30.0, "t_on": 75.0, "t_off": 70.0},
        "phases": phases,
    }
    print(json.dumps(sc, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
