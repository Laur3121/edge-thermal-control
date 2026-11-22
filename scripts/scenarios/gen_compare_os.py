#!/usr/bin/env python3
"""OS 標準のファン制御との比較実験のシナリオを作る(2026-11-22)。

- 条件:OS 標準(step_wise、40/45/50/55℃ で段階 1〜4)/ しきい値 ON-OFF(75/70℃)/ 提案手法
  しきい値と提案は 11/14 の比較実験と同じ設定。11/14 の結果の再現も兼ねる
- 負荷パターン・休み・3 台同時・3 巡は 11/14 の比較実験(gen_compare.py)と同じ
- 順番はラテン方格(各条件が各巡の 1・2・3 番目に 1 回ずつ)。最初の巡の順番だけ乱数で決める。
  単純に巡ごとに乱数で並べると、条件が 3 つでは偏りやすく(試したら提案が 3 回とも最後になった)、
  夜の間の室温の変化と順番が重なるため
- 休みの間は、どの条件もファン OFF(11/14 と同じ。開始温度をそろえる)
  OS 標準の条件は、負荷パターンの 20 分の間だけファンを OS に任せる

使い方:python scripts/scenarios/gen_compare_os.py > scripts/scenarios/compare_os.json
"""

import json
import random

from gen_compare import PATTERN, REST_S, ROLES, ROUNDS

SEED = 20261122
CONDITIONS = {"os": "os", "threshold": "threshold", "proposed": "proposed"}


def main():
    rng = random.Random(SEED)
    phases = [{"name": "p0_baseline", "duration_s": 300, "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES}}]
    order = []
    first = list(CONDITIONS)
    rng.shuffle(first)
    for k in range(1, ROUNDS + 1):
        names = first[k - 1:] + first[:k - 1]  # 巡回させてラテン方格にする
        order.append(names)
        for cond in names:
            for i, (cores, dur) in enumerate(PATTERN):
                ph = {"name": f"r{k}_{cond}_s{i + 1}", "duration_s": dur, "load": {r: cores for r in ROLES}}
                if i == 0:
                    ph["fan"] = {r: CONDITIONS[cond] for r in ROLES}
                phases.append(ph)
            phases.append({"name": f"r{k}_{cond}_rest", "duration_s": REST_S,
                           "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES}})
    sc = {
        "name": "compare_os",
        "description": (f"OS 標準との比較(seed={SEED}、scripts/scenarios/gen_compare_os.py で生成)。"
                        f"3 条件 × {ROUNDS} 巡、順番はラテン方格:{order}。負荷パターン(コア数, 秒)={PATTERN}、休み {REST_S} 秒"),
        "settle": {"window_s": 120, "max_slope_c_per_min": 0.2, "timeout_s": 1800},
        "control": {"tlimit": 80.0, "delta_s": 30.0, "alpha": 2.0, "delta_margin": 0.5, "hysteresis": 1.0,
                    "min_on_s": 30.0, "t_on": 75.0, "t_off": 70.0},
        "phases": phases,
    }
    print(json.dumps(sc, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
