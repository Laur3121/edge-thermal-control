#!/usr/bin/env python3
"""tradeoff 実験(11/27 計画、experiments/20261127_tradeoff/README.md)の判定。

しきい値の点(th65・th70・th75)を「稼働率 → 80℃ を超えた時間」の折れ線にし、提案の各点(pd*)と同じ稼働率での
しきい値の 80℃ 超えを線形補間で求める。比 = 提案の 80℃ 超え / 補間したしきい値の 80℃ 超え。
提案の点の稼働率がしきい値の点の範囲の外なら「比べられない」。r5(ファン不調)は除く 7 台・2 巡の合計。

判定(README で実行前に決めた):比べられる提案の点のうち 2 点以上で比 ≤ 0.7 →「予測の意味あり」、
2 点以上で比 ≥ 1.0 →「意味なし」、それ以外 →「はっきりしない」。最後の行に JUDGE=<yes|no|unclear> を出す。

使い方:python scripts/judge_tradeoff.py experiments/20261127_tradeoff/d60
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def main(exp: Path, exclude=("raspi5",)):
    df = pd.read_csv(exp / "results" / "control_summary.csv")
    df = df[~df.host.isin(exclude)]
    agg = df.groupby("cond").agg(duty=("duty", "mean"), over80=("over80_s", "sum"), n=("duty", "size"))
    th = agg[agg.index.str.match(r"th\d+$")].sort_values("duty")
    pr = agg[agg.index.str.match(r"pd")]
    print("しきい値:"); print(th.round(3).to_string())
    print("提案:"); print(pr.round(3).to_string())
    yes = no = 0
    for c, r in pr.iterrows():
        if not (th.duty.min() <= r.duty <= th.duty.max()) or len(th) < 2:
            print(f"{c}: 稼働 {r.duty:.3f} はしきい値の範囲外 → 比べられない")
            continue
        ref = float(np.interp(r.duty, th.duty, th.over80))
        ratio = r.over80 / ref if ref > 0 else float("inf")
        print(f"{c}: 稼働 {r.duty:.3f}、80℃ 超え {r.over80:.0f} 秒、同じ稼働のしきい値 {ref:.0f} 秒 → 比 {ratio:.2f}")
        yes += ratio <= 0.7
        no += ratio >= 1.0
    # 副の指標(A'、11/27 追加):80℃ 超えが合計 60 秒以下の設定のうち一番少ない稼働率
    safe_th, safe_pr = th[th.over80 <= 60], pr[pr.over80 <= 60]
    if len(safe_th) and len(safe_pr):
        d = (safe_th.duty.min() - safe_pr.duty.min()) * 100
        print(f"副:80℃ 超え 60 秒以下で一番少ない稼働 しきい値 {safe_th.duty.min():.3f}({safe_th.duty.idxmin()})、"
              f"提案 {safe_pr.duty.min():.3f}({safe_pr.duty.idxmin()})→ 提案が {d:.1f} ポイント少ない"
              + ("(5 ポイント以上:80℃ を守ったまま減らせた)" if d >= 5 else ""))
    else:
        print("副:どちらかの方式で 80℃ 超え 60 秒以下の設定がない → 比べられない")
    judge = "yes" if yes >= 2 else "no" if no >= 2 else "unclear"
    print(f"JUDGE={judge}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
