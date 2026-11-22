#!/usr/bin/env python3
"""干渉の条件を広げる実験(ファン ON、全台に負荷)のシナリオ(2026-11-23 夜中に実行)。

ブロック(各:負荷 2 コア 600 秒 + 休み 720 秒、休みは負荷 0・ファン OFF):
  ファン OFF:A だけ / B だけ / C だけ / 3 台とも
  ファン ON(段階 4):A だけ / 3 台とも
干渉の見方:各ノードについて「3 台とも」の上昇 −「自分だけ」の上昇。A だけのときは B と C の上昇の差(11/13 と同じ)。
使い方:python scripts/scenarios/gen_interference_load.py > scripts/scenarios/interference_load.json
"""

import json

ROLES = ("A", "B", "C")
LOAD_S, REST_S, CORES = 600, 720, 2
BLOCKS = [("off_A", 0, ["A"]), ("off_B", 0, ["B"]), ("off_C", 0, ["C"]), ("off_all", 0, list(ROLES)),
          ("on_A", 1, ["A"]), ("on_all", 1, list(ROLES))]


def main():
    phases = [{"name": "p0_baseline", "duration_s": 300, "load": {r: 0 for r in ROLES},
               "fan": {r: 0 for r in ROLES}, "fan_stage": {r: 4 for r in ROLES}}]
    for name, fan, loaded in BLOCKS:
        phases.append({"name": f"{name}_load", "duration_s": LOAD_S,
                       "load": {r: (CORES if r in loaded else 0) for r in ROLES}, "fan": {r: fan for r in ROLES}})
        phases.append({"name": f"{name}_rest", "duration_s": REST_S,
                       "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES}})
    sc = {"name": "interference_load",
          "description": f"干渉の条件を広げる。負荷 {CORES} コア {LOAD_S} 秒 + 休み {REST_S} 秒。ブロック:{[b[0] for b in BLOCKS]}",
          "settle": {"window_s": 120, "max_slope_c_per_min": 0.2, "timeout_s": 1800}, "phases": phases}
    print(json.dumps(sc, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
