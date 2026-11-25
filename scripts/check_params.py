#!/usr/bin/env python3
"""閉ループの実験を始める前に、制御のパラメータを実測と突き合わせる(2026-11-26 追加)。

11/25 夜、6 台のファンの効き e が借り物のまま制御を回し、モデルがファン ON の温度を 10〜20℃ 低く見積もっていた。
その再発を防ぐため、次を確かめ、どれか外れたら終了コード 1 で止める。

1. ファン ON・4 コアの定常温度(モデル)と、20261125_box_control の常時 ON(4 コア区間の最後 2 分)の実測の差が 5℃ 以内
2. ファン OFF・2 コアの定常温度(モデル)が 60〜110℃ の範囲(物理的にありえる値か)
3. a は 0 < a < 1、b > 0、e < 0、c >= 0
4. stage_eff があれば、0 から 1 に向かって減らない

使い方:python scripts/check_params.py scripts/control_params_box2.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REF = Path("experiments/20261125_box_control")
TOL = 5.0


def observed_on_4core():
    tel = pd.read_csv(REF / "raw" / "telemetry.csv")
    ev = pd.read_csv(REF / "events.csv")
    amb = pd.read_csv(REF / "raw" / "ambient.csv")
    amb = amb[amb.name.astype(str).str.contains("ハブ２")].sort_values("ts")
    ps = ev[ev.event == "phase_start"][["ts", "phase"]].reset_index(drop=True)
    ps["end"] = list(ps.ts[1:]) + [ev.ts.max()]
    out = {}
    for h in [f"raspi{i}" for i in range(1, 9)]:
        vals, rooms = [], []
        for k in (1, 2):
            e = ps[ps.phase == f"c{k}_always_s2"].end.iloc[0]
            vals.append(tel[(tel.host == h) & (tel.ts >= e - 120) & (tel.ts < e)].temp.mean())
            rooms.append(np.interp(e, amb.ts.to_numpy(), amb.temperature.to_numpy()))
        out[h] = (float(np.mean(vals)), float(np.mean(rooms)))
    return out


def main(path: Path):
    P = json.loads(path.read_text())
    obs = observed_on_4core()
    ok = True
    print(f"{path}:ファン ON・4 コアの定常(モデル vs 実測)、ファン OFF・2 コアの定常(モデル)")
    for h, node in P["nodes"].items():
        for name in ("self", "withH"):
            w = node[name]
            T_obs, room = obs[h]
            on = (w["b"] * 1.0 + w["e"] + w["d"]) / (1 - w["a"]) + room
            off2 = (w["b"] * 0.5 + w["d"]) / (1 - w["a"]) + room
            bad = []
            if abs(on - T_obs) > TOL:
                bad.append(f"ON の定常が実測と {on - T_obs:+.1f}℃")
            if not 60 <= off2 <= 110:
                bad.append(f"OFF・2 コアの定常 {off2:.1f}℃")
            if not (0 < w["a"] < 1 and w["b"] > 0 and w["e"] < 0 and w.get("c", 0) >= 0):
                bad.append(f"係数の符号 a={w['a']:.3f} b={w['b']:.2f} e={w['e']:.2f} c={w.get('c', 0):.3f}")
            print(f"  {h} {name:5s} ON {on:5.1f}(実測 {T_obs:5.1f}) OFF2 {off2:5.1f}  {'NG: ' + '、'.join(bad) if bad else 'OK'}")
            ok &= not bad
        if "stage_eff" in node:
            eff = node["stage_eff"]
            if not (eff[0] == 0 and all(b >= a for a, b in zip(eff, eff[1:])) and abs(eff[-1] - 1) < 1e-9):
                print(f"  {h} stage_eff がおかしい: {eff}")
                ok = False
    print("結果:", "OK" if ok else "NG(実験を始めない)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
