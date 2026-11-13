#!/usr/bin/env python3
"""検証用のランダム負荷・ファンのシナリオを作る(validate_random.json)。

目的:同定(20261113_step_identify)とは別の日・別のパターンのデータで、
KF の Δ秒先予測と σ が当たっているかを確かめる。全ノードに独立に負荷とファンを入れるので、
B・C の自己モデルの同定(前半)と検証(後半)にも使える。

- 各区間の長さは 2〜10 分からランダム。ノードごとに独立にファン(0/1)と負荷を決める
- ファン OFF のときは負荷 0〜2 コア(定常で約 77℃ 以下。80℃ を超えないように)
- ファン ON のときは負荷 0〜4 コア(同定データにない 3・4 コアも入れて、外挿を確かめる)
- 乱数の種を固定するので、同じシナリオを何度でも作り直せる

使い方:python scripts/scenarios/gen_validate_random.py > scripts/scenarios/validate_random.json
"""

import json
import random

SEED = 20261114
TOTAL_S = 5 * 3600
DURATIONS = [120, 180, 240, 300, 420, 600]
ROLES = ["A", "B", "C"]

rng = random.Random(SEED)
phases = [{"name": "p0_baseline", "duration_s": 300,
           "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES}}]
t = 0
i = 0
while t < TOTAL_S:
    i += 1
    dur = rng.choice(DURATIONS)
    fan = {r: rng.randint(0, 1) for r in ROLES}
    load = {r: rng.choice([0, 1, 2, 3, 4] if fan[r] else [0, 1, 2]) for r in ROLES}
    phases.append({"name": f"r{i:03d}", "duration_s": dur, "load": load, "fan": fan})
    t += dur
phases.append({"name": "p9_cool", "duration_s": 600,
               "load": {r: 0 for r in ROLES}, "fan": {r: 1 for r in ROLES}})

print(json.dumps({
    "name": "validate_random",
    "description": (f"検証用のランダム負荷・ファン(seed={SEED}、scripts/scenarios/gen_validate_random.py で生成)。"
                    "全ノードに独立に、区間 2〜10 分、ファン OFF なら負荷 0〜2 コア、ON なら 0〜4 コア。"
                    "82℃ 以上はノード側で強制ファン ON(ログの failsafe 列)。"),
    "settle": {"window_s": 120, "max_slope_c_per_min": 0.2, "timeout_s": 1800},
    "phases": phases,
}, ensure_ascii=False, indent=1))
