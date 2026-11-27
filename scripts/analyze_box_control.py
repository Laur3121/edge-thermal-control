#!/usr/bin/env python3
"""box_control 実験の第 2 部(ファン制御の比較)を、README で実行前に決めた指標で集計し、図を作る。

指標(方式ごと、2 巡 × 8 台):ファン稼働率(20 分の負荷パターンの間に ON だった割合)、80℃ を超えた時間、最高温度、
強制 ON の時間、最低クロック、ON/OFF の回数
追加の指標(11/26 昼、レオと決めた。実行前に決めた判定には使わない参考の指標):
  clock_low_s    クロックが 1795 MHz 未満だった時間(温度によるクロックの制限。ガバナは performance で、アイドルでも 1800 MHz)
  clock_loss_pct 20 分の間の平均のクロック低下 [%](1 − クロック / 1800 MHz の時間平均)。処理の遅れの目安
出力:<exp>/results/control_summary.csv、summary_control.txt、fig_control.png

使い方:python scripts/analyze_box_control.py experiments/20261125_box_control
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

plt.rcParams.update({"font.family": ["Hiragino Sans", "sans-serif"], "font.size": 8})
COND = {"always": "常時 ON", "periodic": "1 分おき", "random": "ランダム", "threshold": "しきい値",
        "selffixed": "自ノードの\n予測", "proposed": "提案\n(KF + H)", "proposed_hr": "提案\n+ 余力"}
COL = {"always": "#C9D1D9", "periodic": "#DDE3E8", "random": "#DDE3E8", "threshold": "#A7B3C2",
       "selffixed": "#8C99A6", "proposed": "#0099BB", "proposed_hr": "#006F8A"}


def main(exp: Path):
    tel = pd.read_csv(exp / "raw" / "telemetry.csv")
    ev = pd.read_csv(exp / "events.csv")
    ps = ev[ev.event == "phase_start"][["ts", "phase"]].reset_index(drop=True)
    ps["end"] = list(ps.ts[1:]) + [ev.ts.max()]
    rows = []
    # 方式は段階名 c<巡>_<方式>_s<番号> から拾う(th65・pa1 など、11/27 追加の方式も含める)
    found = ps.phase.str.extract(r"^c\d+_(.+)_s\d+$")[0].dropna().unique()
    for c in found:
        if c not in COND:
            COND[c] = ({"th": "しきい値\n", "pa": "提案 α=", "pd": "提案 δ="}[c[:2]] + c[2:].replace("p", ".")
                       if c[:2] in ("th", "pa", "pd") else c)
            COL[c] = "#A7B3C2" if c.startswith("th") else "#0099BB" if c[:2] in ("pa", "pd") else "#C9D1D9"
    for k in (1, 2):
        for cond in COND:
            sub = ps[ps.phase.str.match(rf"c{k}_{cond}_s\d")]
            if sub.empty:
                continue
            t0, t1 = sub.ts.min(), sub.end.max()
            for h, g in tel[(tel.ts >= t0) & (tel.ts < t1)].groupby("host"):
                g = g.sort_values("ts")
                dt = np.diff(g.ts.to_numpy(), append=g.ts.iloc[-1])
                dt = np.clip(dt, 0, 5)
                f = g.fan.to_numpy()
                rows.append(dict(round=k, cond=cond, host=h, duty=float((f * dt).sum() / dt.sum()),
                                 over80_s=float(dt[g.temp.to_numpy() > 80].sum()), max_temp=g.temp.max(),
                                 failsafe_s=float(dt[g.failsafe.to_numpy() == 1].sum()),
                                 min_clock_mhz=g.clock.min() / 1e6,
                                 clock_low_s=float(dt[g.clock.to_numpy() / 1e6 < 1795].sum()),
                                 clock_loss_pct=float((np.clip(1 - g.clock.to_numpy() / 1e6 / 1800, 0, 1) * dt).sum()
                                                      / dt.sum() * 100),
                                 switches=int((np.diff(f) != 0).sum()), complete=bool(t1 - t0 > 1150)))
    df = pd.DataFrame(rows)
    out = exp / "results"
    out.mkdir(exist_ok=True)
    df.to_csv(out / "control_summary.csv", index=False)
    agg = df.groupby("cond").agg(duty=("duty", "mean"), duty_min=("duty", "min"), duty_max=("duty", "max"),
                                 over80_s=("over80_s", "sum"), max_temp=("max_temp", "max"),
                                 failsafe_s=("failsafe_s", "sum"), min_clock=("min_clock_mhz", "min"),
                                 clock_low_s=("clock_low_s", "sum"), clock_loss_pct=("clock_loss_pct", "mean"),
                                 clock_loss_max=("clock_loss_pct", "max"),
                                 switches=("switches", "mean"), n=("duty", "size")).reindex(list(COND)).dropna(how="all")
    per_round = df.groupby(["cond", "round"]).duty.mean().unstack()
    txt = "\n".join(["# box_control 第 2 部(方式ごと、2 巡 × 8 台)", agg.round(3).to_string(), "",
                     "巡ごとのファン稼働率(8 台の平均)", per_round.round(3).to_string()])
    (out / "summary_control.txt").write_text(txt)
    print(txt)

    fig, ax = plt.subplots(figsize=(3.3, 1.5))
    for i, cond in enumerate(agg.index):
        ax.bar(i, agg.loc[cond, "duty"] * 100, 0.6, color=COL[cond])
        for k, v in per_round.loc[cond].dropna().items():
            ax.plot(i + (k - 1.5) * 0.18, v * 100, "o", ms=2.5, color="0.25")
        ax.text(i, agg.loc[cond, "duty"] * 100 + 3, f"{agg.loc[cond, 'duty'] * 100:.0f}%", ha="center", fontsize=7)
    ax.set_xticks(range(len(agg)), [COND[c] for c in agg.index], fontsize=7)
    ax.set_ylabel("ファン稼働率 [%]")
    ax.set_ylim(0, 115)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    fig.tight_layout(pad=0.2)
    fig.savefig(out / "fig_control.png", dpi=300)  # レジュメの図 thesis/figures/fig_res_fan.png は上書きしない


if __name__ == "__main__":
    main(Path(sys.argv[1]))
