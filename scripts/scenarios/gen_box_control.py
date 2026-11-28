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
CONDITIONS = {"always": 1, "threshold": "threshold", "selffixed": "self_fixed", "proposed": "proposed",
              "proposed_hr": "proposed_hr", "pnoh": "proposed@use_h=0",  # pnoh:H なしの提案(11/27 追加、実験 B)
              "periodic": None, "random": None}  # periodic / random は 60 秒ごとに ON/OFF を切り替える(11/26 追加、11/24 の先生の案)
SLOT = 60
PATTERN = [(1, 120), (4, 360), (0, 180), (4, 300), (2, 120), (4, 120)]  # 11/14 の比較実験と同じ
# 徐々に上がる負荷(11/27 追加):PATTERN の 4 コアに上がる所を 1 分ごとに 1 コアずつにしたもの。各ブロックの長さは同じ
RAMP = [(1, 120), (2, 60), (3, 60), (4, 240), (0, 180), (1, 60), (2, 60), (3, 60), (4, 120), (2, 120), (3, 60), (4, 60)]
REST_S, ROUNDS = 720, 2


def cond_value(cond: str):
    """方式名 → シナリオの fan の値。th<N> はしきい値 N℃ ON・N−5℃ OFF、pa<α> は提案の α、pd<δ> は提案の δ を変えたもの(小数点は p)(11/27 追加)。"""
    import re
    if cond in CONDITIONS:
        return CONDITIONS[cond]
    m = re.fullmatch(r"th(\d+)", cond)
    if m:
        t = int(m.group(1))
        return f"threshold@t_on={t},t_off={t - 5}"
    m = re.fullmatch(r"pa(\d+(?:p\d+)?)", cond)
    if m:
        return f"proposed@alpha={m.group(1).replace('p', '.')}"
    m = re.fullmatch(r"pd(\d+(?:p\d+)?)", cond)
    if m:  # 提案のマージンの定数 δ を変えたもの(σ がほぼ一定なので α より点が動く)
        return f"proposed@delta_margin={m.group(1).replace('p', '.')}"
    raise SystemExit(f"知らない方式: {cond}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fan", nargs="*", default=[])
    ap.add_argument("--rise-only", action="store_true")
    ap.add_argument("--ctrl-only", action="store_true", help="第 2 部だけ(11/26 朝追加)")
    ap.add_argument("--half-load", action="store_true",
                    help="負荷パターンのコア数を 4→2、2→1 に下げる(11/26 朝追加。囲いで 4 コアはファンの余裕がなかったため)")
    ap.add_argument("--conds", nargs="*", default=list(CONDITIONS), help="使う方式")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--delta", type=float, default=30.0, help="予測の先読み Δ [秒](11/26 朝追加)")
    ap.add_argument("--stage", type=int, default=STAGE, help="ファン ON のときの段階(0〜4、11/26 朝追加)")
    ap.add_argument("--random-load", type=int, default=None, metavar="SEED",
                    help="台ごとに独立なランダム負荷(11/26 昼追加):20 分を 120 秒 × 10 区間に分け、各区間・各ノードで"
                         "0〜4 コアを等確率で選ぶ。同じ表を全方式・全巡で使う(方式どうしを同じ負荷で比べるため)")
    ap.add_argument("--ramp", action="store_true",
                    help="負荷を 1 分ごとに 1 コアずつ上げるパターン(RAMP)にする(11/27 追加)")
    ap.add_argument("--fan-delay", type=float, default=0.0,
                    help="ファンの指令を送るまでの遅れ [秒](11/26 夜追加。冷却の効きが遅い条件を実機で作る)")
    args = ap.parse_args()
    fan_roles = [r for r in ROLES if r not in args.no_fan]
    load_roles = fan_roles  # ファンを使えないノードには負荷をかけない

    def phase(name, dur, load, fan):
        return {"name": name, "duration_s": dur, "load": {r: load.get(r, 0) for r in ROLES},
                "fan": {r: fan.get(r, 0) for r in fan_roles}}

    base = RAMP if args.ramp else PATTERN
    pattern = [({4: 2, 2: 1}.get(c, c), d) for c, d in base] if args.half_load else base
    rload = None
    if args.random_load is not None:
        lrng = random.Random(args.random_load)
        rload = [{r: (lrng.choice([0, 1, 2, 3, 4]) if r in load_roles else 0) for r in ROLES} for _ in range(10)]
    if args.ctrl_only:
        phases = [{**phase("p0_baseline", 300, {}, {}), "fan_stage": {r: args.stage for r in fan_roles}}]
    else:
        phases = [{**phase("rise_pre", RISE_PRE, {}, {}), "fan_stage": {r: STAGE for r in fan_roles}},
                  phase("rise_load", RISE_LOAD, {r: RISE_CORES for r in BOTTOM if r in load_roles},
                        {r: 1 for r in BOTTOM if r in fan_roles}),
                  phase("rise_rest", RISE_REST, {}, {})]
    order = []
    if not args.rise_only:
        rng = random.Random(args.seed)
        for k in range(1, ROUNDS + 1):
            names = list(args.conds)
            rng.shuffle(names)
            order.append(names)
            for cond in names:
                if cond in ("periodic", "random"):
                    # 負荷パターンを 60 秒ずつに分け、ファンを periodic は ON/OFF 交互、random は各ノード独立に確率 0.5 で決める
                    frng = random.Random(f"{args.seed}-{k}-{cond}")
                    slot = 0
                    for i, (cores, dur) in enumerate(pattern):
                        for j in range(dur // SLOT):
                            if cond == "periodic":
                                fan = {r: 1 - slot % 2 for r in fan_roles}
                            else:
                                fan = {r: int(frng.random() < 0.5) for r in fan_roles}
                            phases.append({"name": f"c{k}_{cond}_s{i + 1}_{j + 1}", "duration_s": SLOT,
                                           "load": {r: (cores if r in load_roles else 0) for r in ROLES}, "fan": fan})
                            slot += 1
                    phases.append(phase(f"c{k}_{cond}_rest", REST_S, {}, {}))
                    continue
                if rload is not None:
                    for i, row in enumerate(rload):
                        ph = {"name": f"c{k}_{cond}_s{i + 1}", "duration_s": 120, "load": dict(row)}
                        if i == 0:
                            ph["fan"] = {r: cond_value(cond) for r in fan_roles}
                        phases.append(ph)
                    phases.append(phase(f"c{k}_{cond}_rest", REST_S, {}, {}))
                    continue
                for i, (cores, dur) in enumerate(pattern):
                    ph = {"name": f"c{k}_{cond}_s{i + 1}", "duration_s": dur,
                          "load": {r: (cores if r in load_roles else 0) for r in ROLES}}
                    if i == 0:
                        ph["fan"] = {r: cond_value(cond) for r in fan_roles}
                    phases.append(ph)
                phases.append(phase(f"c{k}_{cond}_rest", REST_S, {}, {}))
    total = sum(p["duration_s"] for p in phases)
    sc = {"name": "rise_only" if args.rise_only else "box_control",
          "description": (("" if args.ctrl_only else f"温度上昇を長く見る(下段 {RISE_CORES} コア {RISE_LOAD} 秒、上段アイドル)")
                          + ("" if args.rise_only else
                             f" + ファン制御の比較 {len(args.conds)} 方式 × {ROUNDS} 巡(順番 {order}、seed={args.seed}、"
                             f"負荷パターン {('台ごとのランダム(seed ' + str(args.random_load) + ')') if rload else pattern}、Δ={args.delta:.0f} 秒、ON の段階 {args.stage}"
                             + (f"、ファンの指令の遅れ {args.fan_delay:.0f} 秒" if args.fan_delay > 0 else "") + ")")
                          + f"。ファンなし:{args.no_fan or 'なし'}。合計 {total / 3600:.1f} 時間(落ち着き待ちを除く)"),
          "settle": {"window_s": 120, "max_slope_c_per_min": 0.2, "timeout_s": 1800},
          "control": {"tlimit": 80.0, "delta_s": args.delta, "alpha": 2.0, "delta_margin": 0.5, "hysteresis": 1.0,
                      "min_on_s": 30.0, "t_on": 75.0, "t_off": 70.0,
                      **({"fan_delay_s": args.fan_delay} if args.fan_delay > 0 else {})},
          "phases": phases}
    print(json.dumps(sc, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
