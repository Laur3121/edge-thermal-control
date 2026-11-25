#!/usr/bin/env python3
"""ファンの段階を使う実験のシナリオ(2026-11-26)。

ident:段階ごとのファンの効きを同定する。8 台に 2 コアの負荷をかけたまま、ファン OFF 120 秒 → 段階 s で ON 240 秒 を、
       s = 1, 2, 3, 4, 4, 3, 2, 1 の順に繰り返す(温度の流れの影響を打ち消すため往復)
ms   :段階を予測で選ぶ提案(proposed_ms)と、OS 標準(step_wise)、しきい値(75/70℃、段階 4)を、負荷の形 2 種で比べる
       一気:3 コア 12 分 → 0 コア 8 分 / 徐々:1 → 2 → 3 コアを 2 分ずつ → 3 コア 6 分 → 0 コア 8 分
       12 分休み。2 巡、順番はランダム(seed 固定)

使い方:python scripts/scenarios/gen_stage_ms.py ident > scripts/scenarios/stage_ident.json
       python scripts/scenarios/gen_stage_ms.py ms > scripts/scenarios/stage_ms.json
"""
import json
import random
import sys

ROLES = [f"r{i}" for i in range(1, 9)]
SHAPES = {"sudden": [(3, 720), (0, 480)], "ramp": [(1, 120), (2, 120), (3, 360), (0, 480)]}
CONDS = {"os": "os", "threshold": "threshold", "ms": "proposed_ms"}
REST_S, ROUNDS, SEED = 720, 2, 2026112630


def ph(name, dur, load, fan, stage=None):
    p = {"name": name, "duration_s": dur, "load": {r: load for r in ROLES}, "fan": {r: fan for r in ROLES}}
    if stage is not None:
        p["fan_stage"] = {r: stage for r in ROLES}
    return p


def ident():
    phases = [ph("p0_baseline", 300, 0, 0, 4), ph("warm", 300, 2, 1, 4)]
    for i, s in enumerate([1, 2, 3, 4, 4, 3, 2, 1]):
        phases += [ph(f"id{i + 1}_s{s}_off", 120, 2, 0, s), ph(f"id{i + 1}_s{s}_on", 240, 2, 1, s)]
    phases.append(ph("id_rest", 600, 0, 0, 4))
    return {"name": "stage_ident", "description": "段階ごとのファンの効きの同定。2 コア、OFF 120 秒 → 段階 s で ON 240 秒、"
                                                   "s = 1,2,3,4,4,3,2,1", "settle": {"window_s": 120, "max_slope_c_per_min": 0.2, "timeout_s": 1800},
            "phases": phases}


def ms():
    rng = random.Random(SEED)
    phases = [ph("p0_baseline", 300, 0, 0, 4)]
    order = []
    for k in range(1, ROUNDS + 1):
        combos = [(c, s) for c in CONDS for s in SHAPES]
        rng.shuffle(combos)
        order.append(combos)
        for cond, shape in combos:
            for i, (cores, dur) in enumerate(SHAPES[shape]):
                p = {"name": f"c{k}_{cond}-{shape}_s{i + 1}", "duration_s": dur, "load": {r: cores for r in ROLES}}
                if i == 0:
                    p["fan"] = {r: CONDS[cond] for r in ROLES}
                    p["fan_stage"] = {r: 4 for r in ROLES}  # しきい値は段階 4。proposed_ms は自分で段階を送る
                phases.append(p)
            phases.append(ph(f"c{k}_{cond}-{shape}_rest", REST_S, 0, 0))
    total = sum(p["duration_s"] for p in phases)
    return {"name": "stage_ms", "description": f"段階を予測で選ぶ提案 vs OS 標準 vs しきい値 × 負荷の形(一気・徐々)× {ROUNDS} 巡。"
                                                f"順番 {order}(seed {SEED})。合計 {total / 3600:.1f} 時間",
            "settle": {"window_s": 120, "max_slope_c_per_min": 0.2, "timeout_s": 1800},
            "control": {"tlimit": 80.0, "delta_s": 30.0, "alpha": 2.0, "delta_margin": 0.5, "hysteresis": 1.0,
                        "min_on_s": 30.0, "t_on": 75.0, "t_off": 70.0},
            "phases": phases}


if __name__ == "__main__":
    print(json.dumps({"ident": ident, "ms": ms}[sys.argv[1]](), ensure_ascii=False, indent=1))
