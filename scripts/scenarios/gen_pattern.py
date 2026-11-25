#!/usr/bin/env python3
"""干渉が起こる条件(位置関係・熱量・ファン)を測るシナリオ(2026-11-25)。開いた状態と段ボールの囲いで同じものを回す。

ラック(2 段 × 4 列、ポート側から見て):
  上段: r1 r2 r3 r4        r1・r2・r3・r6・r7 は PoE+ HAT 付き(測定とファン制御)
  下段: r5 r6 r7 r8        r4・r5・r8 は HAT なし(熱源として負荷だけかける。ファンなし)

ブロック(負荷はすべて 2 コア):
  ファン OFF(負荷 600 秒 → 休み 720 秒):
    off_r6      r6 だけ(下段の左から 2 番目)→ 真上 r2、横 r7、斜め上 r1・r3
    off_r7      r7 だけ(下段の左から 3 番目)→ 真上 r3、横 r6、斜め上 r2、遠い r1
    off_bottom  下段 4 台(r5〜r8)    → 上段への熱の昇り(熱量を増やす)
    off_all     8 台すべて             → 全体の昇温
  (a) ファンの風で隣に排熱が飛ぶか:
    fanA_r6     r6 のファンだけ ON にして 720 秒置き(基準をそろえる)→ r6 に負荷 600 秒 → 休み 720 秒(ファン OFF)
                off_r6 と比べ、r6 のファンが ON のとき隣(r2・r7・r1・r3)の上昇が大きくなるか
  (b) 隣が熱いと自分の冷え方が弱くなるか(対象は r2 = 上段の真ん中):
    cool_alone  r2 だけ負荷(ファン OFF)600 秒 → r2 のファン ON 300 秒(負荷は続ける)→ 休み 720 秒
    cool_nbrs   同じ手順で、ほかの 7 台にも同時に負荷(r2 以外のファンは OFF)
                ファン ON 後の r2 の下がり幅と最後 60 秒の温度を比べる
使い方:python scripts/scenarios/gen_pattern.py > scripts/scenarios/pattern.json
"""

import json

ROLES = [f"r{i}" for i in range(1, 9)]
HAT = ["r1", "r2", "r3", "r6", "r7"]
LOAD_S, REST_S, COOL_S, CORES, STAGE = 600, 720, 300, 2, 4


def ph(name, dur, loaded=(), fan_on=()):
    return {"name": name, "duration_s": dur,
            "load": {r: (CORES if r in loaded else 0) for r in ROLES},
            "fan": {r: (1 if r in fan_on else 0) for r in HAT}}


def main():
    phases = [{**ph("p0_baseline", 300), "fan_stage": {r: STAGE for r in HAT}}]
    for name, loaded in [("off_r6", ["r6"]), ("off_r7", ["r7"]),
                         ("off_bottom", ["r5", "r6", "r7", "r8"]), ("off_all", ROLES)]:
        phases += [ph(f"{name}_load", LOAD_S, loaded), ph(f"{name}_rest", REST_S)]
    phases += [ph("fanA_r6_pre", REST_S, fan_on=["r6"]), ph("fanA_r6_load", LOAD_S, ["r6"], ["r6"]),
               ph("fanA_r6_rest", REST_S)]
    for name, loaded in [("cool_alone", ["r2"]), ("cool_nbrs", ROLES)]:
        phases += [ph(f"{name}_load", LOAD_S, loaded), ph(f"{name}_fan", COOL_S, loaded, ["r2"]),
                   ph(f"{name}_rest", REST_S)]
    total = sum(p["duration_s"] for p in phases)
    sc = {"name": "pattern",
          "description": f"干渉が起こる条件。負荷 {CORES} コア。ファン OFF 4 ブロック、(a) ファンの風、(b) 冷却時の干渉。"
                         f"合計 {total / 3600:.1f} 時間(落ち着き待ちを除く)",
          "settle": {"window_s": 120, "max_slope_c_per_min": 0.2, "timeout_s": 1800}, "phases": phases}
    print(json.dumps(sc, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
