#!/usr/bin/env python3
"""ノードごとに負荷をずらす実験のシナリオ(2026-11-26)。H(周りのノードの熱)が自分の負荷と別に動く条件を作る。

ident:台ごとに独立なランダム負荷(0〜3 コア、180 秒ごとに変える、seed 固定)を 60 分。ファンはしきい値(75/70℃)で回す
       → H の効き c と、ファンの効き e を同定する(全台同時の負荷では c が自分の負荷と区別できなかった)
ctrl :「熱い場所が動く」負荷。2 × 2 の区画(上下 2 段 × 横 2 列)に 3 コア、ほかの台は 1 コア。区画は 240 秒ごとに
       列 1-2 → 2-3 → 3-4 → 2-3 → 1-2 と動く(20 分)。その後 12 分休み。
       方式:提案(KF + H)/自ノードの予測 + 固定マージン/しきい値。2 巡、順番は巡ごとに入れ替え

使い方:python scripts/scenarios/gen_stagger.py ident > scripts/scenarios/stagger_ident.json
       python scripts/scenarios/gen_stagger.py ctrl > scripts/scenarios/stagger_ctrl.json
"""
import json
import random
import sys

ROLES = [f"r{i}" for i in range(1, 9)]
COL = {r: (int(r[1:]) - 1) % 4 + 1 for r in ROLES}  # 1〜4 列
SETTLE = {"window_s": 120, "max_slope_c_per_min": 0.2, "timeout_s": 1800}
CONTROL = {"tlimit": 80.0, "delta_s": 30.0, "alpha": 2.0, "delta_margin": 0.5, "hysteresis": 1.0,
           "min_on_s": 30.0, "t_on": 75.0, "t_off": 70.0}


def ident():
    rng = random.Random(2026112640)
    phases = [{"name": "p0_baseline", "duration_s": 300, "load": {r: 0 for r in ROLES},
               "fan": {r: "threshold" for r in ROLES}, "fan_stage": {r: 4 for r in ROLES}}]
    for i in range(20):
        phases.append({"name": f"rnd{i + 1:02d}", "duration_s": 180, "load": {r: rng.choice([0, 1, 2, 3]) for r in ROLES}})
    phases.append({"name": "rnd_rest", "duration_s": 600, "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES}})
    return {"name": "stagger_ident", "description": "台ごとに独立なランダム負荷(0〜3 コア、180 秒ごと、seed 2026112640)60 分。"
                                                    "ファンはしきい値(75/70℃)", "settle": SETTLE, "control": CONTROL,
            "phases": phases}


def ident_rf():
    """囲いなしの同定用(11/26 追加):台ごとに独立なランダム負荷(0〜3 コア、180 秒ごと)と、
    台ごとに独立なランダムなファン(60 秒ごとに確率 0.5 で ON)を 60 分。全台のファンの効き e を同定するため"""
    rng = random.Random(2026112660)
    phases = [{"name": "p0_baseline", "duration_s": 300, "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES},
               "fan_stage": {r: 4 for r in ROLES}}]
    loads = {r: 0 for r in ROLES}
    for i in range(60):
        if i % 3 == 0:
            loads = {r: rng.choice([0, 1, 2, 3]) for r in ROLES}
        phases.append({"name": f"rf{i + 1:02d}", "duration_s": 60, "load": dict(loads),
                       "fan": {r: int(rng.random() < 0.5) for r in ROLES}})
    phases.append({"name": "rf_rest", "duration_s": 600, "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES}})
    return {"name": "open_ident", "description": "囲いなしの同定:台ごとに独立なランダム負荷(0〜3 コア、180 秒ごと)と"
                                                 "ランダムなファン(60 秒ごと、確率 0.5)を 60 分。seed 2026112660",
            "settle": SETTLE, "control": CONTROL, "phases": phases}


def box_ident():
    """囲いありの同定用(11/28 追加、実験 B):ident_rf と同じ形(台ごとのランダム負荷 0〜3 コア・ランダムなファン)。
    r5 はファンが不調なので負荷 0・ファン OFF(アイドルのまま置く)。seed 2026112870"""
    rng = random.Random(2026112870)
    phases = [{"name": "p0_baseline", "duration_s": 300, "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES},
               "fan_stage": {r: 4 for r in ROLES}}]
    loads = {r: 0 for r in ROLES}
    for i in range(60):
        if i % 3 == 0:
            loads = {r: (0 if r == "r5" else rng.choice([0, 1, 2, 3])) for r in ROLES}
        phases.append({"name": f"bf{i + 1:02d}", "duration_s": 60, "load": dict(loads),
                       "fan": {r: (0 if r == "r5" else int(rng.random() < 0.5)) for r in ROLES}})
    phases.append({"name": "bf_rest", "duration_s": 600, "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES}})
    return {"name": "box_ident", "description": "囲いありの同定:台ごとに独立なランダム負荷(0〜3 コア、180 秒ごと)と"
                                                "ランダムなファン(60 秒ごと、確率 0.5)を 60 分。r5 は負荷 0・ファン OFF。seed 2026112870",
            "settle": SETTLE, "control": CONTROL, "phases": phases}


def ctrl():
    seq = [(1, 2), (2, 3), (3, 4), (2, 3), (1, 2)]
    conds = {"proposed": "proposed", "selffixed": "self_fixed", "threshold": "threshold"}
    order = [["threshold", "proposed", "selffixed"], ["selffixed", "threshold", "proposed"]]
    phases = [{"name": "p0_baseline", "duration_s": 300, "load": {r: 0 for r in ROLES}, "fan": {r: 0 for r in ROLES},
               "fan_stage": {r: 4 for r in ROLES}}]
    for k, names in enumerate(order, 1):
        for cond in names:
            for i, cols in enumerate(seq):
                p = {"name": f"c{k}_{cond}_s{i + 1}", "duration_s": 240,
                     "load": {r: (3 if COL[r] in cols else 1) for r in ROLES}}
                if i == 0:
                    p["fan"] = {r: conds[cond] for r in ROLES}
                phases.append(p)
            phases.append({"name": f"c{k}_{cond}_rest", "duration_s": 720, "load": {r: 0 for r in ROLES},
                           "fan": {r: 0 for r in ROLES}})
    return {"name": "stagger_ctrl", "description": f"熱い場所が動く負荷(2×2 の区画に 3 コア、ほかは 1 コア、240 秒ごとに列 {seq})。"
                                                   f"3 方式 × 2 巡、順番 {order}", "settle": SETTLE, "control": CONTROL,
            "phases": phases}


if __name__ == "__main__":
    print(json.dumps({"ident": ident, "ident_rf": ident_rf, "box_ident": box_ident, "ctrl": ctrl}[sys.argv[1]](), ensure_ascii=False, indent=1))
