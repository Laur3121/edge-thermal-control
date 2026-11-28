#!/usr/bin/env python3
"""risk_real(負荷リスクの動的マージンの実機の予備実験、experiments/20261129_risk_real/README.md)の判定。
r5 を除く 7 台・2 巡の合計。最後の行に JUDGE=<...> を出す。

使い方:python scripts/judge_risk.py experiments/20261129_risk_real/step experiments/20261129_risk_real/ramp
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd


def agg(exp):
    df = pd.read_csv(Path(exp) / "results" / "control_summary.csv")
    df = df[df.host != "raspi5"]
    return df.groupby("cond").agg(duty=("duty", "mean"), over80=("over80_s", "sum"), n=("duty", "size"))


def main(step, ramp):
    s, r = agg(step), agg(ramp)
    print("一気:"); print(s.round(3).to_string()); print("徐々:"); print(r.round(3).to_string())
    pr = [c for c in s.index if c.startswith("pr")]
    # 一気:負荷リスクの一番少ない 80℃ 超え ≤ 0.3 × pd6、かつ稼働 ≤ pd6 + 10 ポイント
    best = s.loc[pr].sort_values("over80").iloc[0]; c_best = s.loc[pr].over80.idxmin()
    ok1 = best.over80 <= 0.3 * s.loc["pd6", "over80"] and best.duty <= s.loc["pd6", "duty"] + 0.10
    print(f"一気:負荷リスクの最小 {c_best} {best.over80:.0f} 秒・{best.duty:.3f}、pd6 {s.loc['pd6', 'over80']:.0f} 秒・"
          f"{s.loc['pd6', 'duty']:.3f} → {'良い' if ok1 else '良くない'}")
    # 徐々:pd3・pd6 の折れ線と同じ稼働で比べる
    ref = r.loc[["pd3", "pd6"]].sort_values("duty"); ratios = []
    for c in pr:
        x = r.loc[c, "duty"]
        if ref.duty.min() <= x <= ref.duty.max():
            v = float(np.interp(x, ref.duty, ref.over80))
            if v >= 30:
                ratios.append(r.loc[c, "over80"] / v); print(f"徐々 {c}:比 {ratios[-1]:.2f}")
        else:
            print(f"徐々 {c}:稼働 {x:.3f} は pd3〜pd6 の範囲外")
    med = float(np.median(ratios)) if ratios else float("nan")
    v2 = "良い" if med <= 0.7 else "良くない" if med >= 1.0 else ("比べられない" if not ratios else "はっきりしない")
    print(f"徐々:比の中央値 {med:.2f} → {v2}")
    ok3 = s.loc["pr0p5", "over80"] <= 120 and r.loc["pr0p5", "over80"] <= 120
    print(f"1 つの ε(0.5%):一気 {s.loc['pr0p5', 'over80']:.0f} 秒、徐々 {r.loc['pr0p5', 'over80']:.0f} 秒 → {'守れた' if ok3 else '守れない'}")
    print(f"JUDGE=一気{'良い' if ok1 else '良くない'}・徐々{v2}・1つのε{'守れた' if ok3 else '守れない'}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
