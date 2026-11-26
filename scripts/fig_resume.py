#!/usr/bin/env python3
"""レジュメ(11/26 作り直し)の結果の図。先生の指摘(結果を文章でなくグラフで/上下・左右・斜めの違いは)に合わせた。

fig_res_direct.png  1 台だけに負荷をかけたときの、隣のノードの上昇(位置関係ごと、囲いなし/あり)
fig_res_rise.png    下段に負荷をかけたときの上段 4 台の温度 − 室温(時系列、囲いなし/あり)
fig_res_pred.png    30 秒先予測の平均絶対誤差(上段 r1〜r3 の平均、囲いなし/あり)

使い方: python scripts/fig_resume.py [rise の実験フォルダ 囲いなし] [囲いあり] [段階名]
  既定は 11/25 の pattern 実験の off_bottom_load(10 分)。今夜の実験が終わったら rise_load(40 分)に差し替える
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

plt.rcParams.update({"font.family": ["Hiragino Sans", "sans-serif"], "font.size": 8})
FIG = Path("thesis/figures")
OPEN = Path("experiments/20261125_pattern_open")
BOXED = Path("experiments/20261125_pattern_box_front_open")
LAB = {OPEN: "囲いなし", BOXED: "囲いあり"}
COL = {"囲いなし": "#8C99A6", "囲いあり": "#0099BB"}
ROOM = "ハブ２"


def fig_direct():
    rows = [("真上", "off_r6", "r2"), ("真上", "off_r7", "r3"), ("横", "off_r6", "r7"), ("横", "off_r7", "r6"),
            ("斜め上", "off_r6", "r1"), ("斜め上", "off_r6", "r3"), ("斜め上", "off_r7", "r2"),
            ("離れた位置", "off_r7", "r1")]
    fig, ax = plt.subplots(figsize=(3.3, 1.75))
    ax.axvspan(-1, 1, color="0.92", zorder=0, label="±1℃ 以内(干渉なし)")
    for exp, dy, mk in [(OPEN, 0.15, "o"), (BOXED, -0.15, "s")]:
        r = pd.read_csv(exp / "results" / "rise.csv").set_index(["phase", "role"]).rise
        v = [r[(ph, to)] for _, ph, to in rows]
        ax.scatter(v, np.arange(len(rows))[::-1] + dy, marker=mk, s=16, color=COL[LAB[exp]], label=LAB[exp],
                   zorder=3)
    ax.set_yticks(np.arange(len(rows))[::-1],
                  [f"{k}  r{ph[-1]}→{to}" for k, ph, to in rows], fontsize=7)
    ax.axvline(0, color="0.5", lw=0.6)
    ax.set_xlim(-2.5, 2.5)
    ax.set_ylim(-0.5, len(rows) - 0.4)
    ax.set_xlabel("負荷をかけていないノードの上昇 [℃]")
    ax.legend(fontsize=6.3, frameon=False, loc="lower center", bbox_to_anchor=(0.4, 1.0), ncol=3, handletextpad=0.3, columnspacing=0.6, handlelength=1.2)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    fig.tight_layout(pad=0.2)
    fig.savefig(FIG / "fig_res_direct.png", dpi=300)


def load(exp):
    tel = pd.read_csv(exp / "raw" / "telemetry.csv")
    ev = pd.read_csv(exp / "events.csv")
    amb = pd.read_csv(exp / "raw" / "ambient.csv")
    amb["name"] = amb.name.astype(str).str.strip()
    return tel, ev, amb


def fig_rise(exps, phase):
    fig, axes = plt.subplots(1, len(exps), figsize=(3.3, 1.55), sharey=True, squeeze=False)
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
    for ax, (exp, lab) in zip(axes[0], exps):
        tel, ev, amb = load(exp)
        ps = ev[(ev.event == "phase_start") & (ev.phase == phase)].ts.iloc[0]
        pe = ev[(ev.event == "phase_end") & (ev.phase == phase)].ts.iloc[0]
        t0, t1 = ps - 180, pe + 600
        a = amb[amb.name.str.contains(ROOM)].sort_values("ts")
        for c, role in zip(colors, ["r1", "r2", "r3", "r4"]):
            g = tel[(tel.host == f"raspi{role[1:]}") & (tel.ts >= t0) & (tel.ts <= t1)].sort_values("ts")
            T = g.temp.rolling(30, center=True, min_periods=5).mean()
            room = np.interp(g.ts, a.ts, a.temperature)
            ax.plot((g.ts - ps) / 60, T - room, color=c, lw=0.9, label=role)
        ax.axvspan(0, (pe - ps) / 60, color="0.9", zorder=0)
        ax.set_title(lab, fontsize=7.5, pad=2)
        for s in ["top", "right"]:
            ax.spines[s].set_visible(False)
    axes[0][0].set_ylabel("上段の温度 − 室温 [℃]")
    fig.supxlabel("下段の負荷開始からの時間 [分](灰色が負荷の区間)", fontsize=8)
    axes[0][-1].legend(fontsize=6.5, frameon=False, ncol=2, loc="lower right", handlelength=1, columnspacing=0.6)
    fig.tight_layout(pad=0.2, w_pad=0.4)
    fig.savefig(FIG / "fig_res_rise.png", dpi=300)


def fig_pred():
    models = [("①自ノードだけ(部屋の室温)", "自ノードのみ\n(部屋の室温)", "#C9D1D9"),
              ("③'自ノードだけ(温度計2・3)", "自ノードのみ\n(囲いの気温)", "#8C99A6"),
              ("②KF+H(部屋の室温)", "提案\n(KF + H)", "#0099BB")]
    fig, ax = plt.subplots(figsize=(3.3, 1.45))
    w = 0.26
    for j, exp in enumerate([OPEN, BOXED]):
        m = pd.read_csv(exp / "results" / "pred_swap" / "metrics.csv")
        m = m[m.role.isin(["r1", "r2", "r3"])].groupby("model").MAE.mean()
        for k, (key, lab, c) in enumerate(models):
            x = j + (k - 1) * w
            ax.bar(x, m[key], w * 0.92, color=c, label=lab if j == 0 else None)
            ax.text(x, m[key] + 0.02, f"{m[key]:.2f}", ha="center", va="bottom", fontsize=6.5)
    ax.set_xticks([0, 1], ["囲いなし", "囲いあり"])
    ax.set_ylabel("30 秒先の誤差 [℃]")
    ax.set_ylim(0, 1.0)
    ax.legend(fontsize=6, frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0), labelspacing=0.8)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    fig.tight_layout(pad=0.2)
    fig.savefig(FIG / "fig_res_pred.png", dpi=300)


if __name__ == "__main__":
    a = sys.argv[1:]
    exps = [(Path(a[0]), "囲いなし"), (Path(a[1]), "囲いあり")] if len(a) >= 2 else [(OPEN, "囲いなし"), (BOXED, "囲いあり")]
    phase = a[2] if len(a) >= 3 else "off_bottom_load"
    fig_direct()
    fig_rise(exps, phase)
    fig_pred()


def fig_fan(box_exp=None, box_label="囲いあり"):
    """Q3:方式ごとのファン稼働率。囲いなし = 11/14(3 台 × 3 巡)、囲いあり = box_exp(8 台 × 2 巡、あれば)。
    80℃ を超えた時間(合計)は、超えたときだけ棒の上に赤で書く。"""
    conds = [("always", "常時 ON"), ("threshold", "しきい値"), ("self_fixed", "自ノード\nの予測"), ("proposed", "提案")]
    m = pd.read_csv("experiments/20261114_compare/results/control_metrics.csv")
    m["cond"] = m.condition.replace({"selffixed": "self_fixed"})
    sets = [("囲いなし", m.rename(columns={"fan_on_ratio": "duty", "over_limit_s": "over"}), "#A7B3C2")]
    if box_exp is not None:
        b = pd.read_csv(Path(box_exp) / "results" / "control_summary.csv")
        b["cond"] = b.cond.replace({"selffixed": "self_fixed"})
        sets.append((box_label, b.rename(columns={"over80_s": "over"}), "#0099BB"))
    fig, ax = plt.subplots(figsize=(3.3, 1.55))
    w = 0.8 / len(sets)
    for j, (lab, df, c) in enumerate(sets):
        for i, (cond, _) in enumerate(conds):
            g = df[df.cond == cond]
            if g.empty:
                continue
            x = i + (j - (len(sets) - 1) / 2) * w
            v = g.duty.mean() * 100
            ax.bar(x, v, w * 0.92, color=c, label=lab if i == 0 or (j and cond == "threshold") else None)
            ax.text(x, v + 1.5, f"{v:.0f}", ha="center", va="bottom", fontsize=6)
            if g.over.sum() >= 1:
                ax.text(x, v + 9, f"超過\n{g.over.sum():.0f}秒", ha="center", va="bottom", fontsize=5.3, color="#C0392B",
                        linespacing=0.9)
    h, l = ax.get_legend_handles_labels()
    seen = {}
    for hh, ll in zip(h, l):
        seen.setdefault(ll, hh)
    ax.legend(seen.values(), seen.keys(), fontsize=6, frameon=False, loc="upper right", ncol=len(seen))
    ax.set_xticks(range(len(conds)), [n for _, n in conds], fontsize=6.5)
    ax.set_ylabel("ファン稼働率 [%]")
    ax.set_ylim(0, 128)
    ax.set_yticks([0, 50, 100])
    for s_ in ["top", "right"]:
        ax.spines[s_].set_visible(False)
    fig.tight_layout(pad=0.2)
    fig.savefig(FIG / "fig_res_fan.png", dpi=300)


def fig_fanwind(exp=Path("experiments/20261125_box_control")):
    """囲いありで下段 4 台に 4 コア・ファン ON を 40 分。上段(負荷なし・ファン OFF)の温度 − 室温。"""
    tel, ev, amb = load(exp)
    ps = ev[(ev.event == "phase_start") & (ev.phase == "rise_load")].ts.iloc[0]
    pe = ev[(ev.event == "phase_end") & (ev.phase == "rise_load")].ts.iloc[0]
    a = amb[amb.name.str.contains(ROOM)].sort_values("ts")
    fig, ax = plt.subplots(figsize=(3.3, 1.55))
    for c, role in zip(["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"], ["r1", "r2", "r3", "r4"]):
        g = tel[(tel.host == f"raspi{role[1:]}") & (tel.ts >= ps - 600) & (tel.ts <= pe + 300)].sort_values("ts")
        T = g.temp.rolling(30, center=True, min_periods=5).mean() - np.interp(g.ts, a.ts, a.temperature)
        ax.plot((g.ts - ps) / 60, T, color=c, lw=0.9, label=role)
    ax.axvspan(0, (pe - ps) / 60, color="0.9", zorder=0)
    ax.text(20, 1.02, "灰色:下段に 4 コア、下段のファン ON", transform=ax.get_xaxis_transform(), fontsize=6.3, color="0.3",
            ha="center", va="bottom")
    ax.set_xlabel("下段の負荷開始からの時間 [分]")
    ax.set_ylabel("上段の温度 − 室温 [℃]")
    ax.legend(fontsize=6.3, frameon=False, ncol=1, loc="upper left", bbox_to_anchor=(1.0, 1.0), handlelength=1)
    for s_ in ["top", "right"]:
        ax.spines[s_].set_visible(False)
    fig.tight_layout(pad=0.2)
    fig.savefig(FIG / "fig_res_fanwind.png", dpi=300)


def fig_sim_slide():
    """予備スライド用:冷却の効きの遅れ(むだ時間)と、80℃ を超えない中での最小のファン稼働率(シミュレーション、11/22)。
    データ:experiments/20261122_sim_slow_cooling/summary.csv(4 パターンの平均、どの方式も 80℃ を超える条件は除く)"""
    sm = pd.read_csv("experiments/20261122_sim_slow_cooling/summary.csv").dropna(subset=["threshold", "proposed"])
    g = sm[(sm.kind == "dead") & (sm.rule == "off")]
    th = g.groupby("delay_s").threshold.mean() * 100
    pr = g.groupby("delay_s").proposed.mean() * 100
    fig, ax = plt.subplots(figsize=(3.9, 1.85))
    ax.axvspan(-4, 4, color="#E6F5F9", zorder=0)
    ax.text(5, 66, "PoE+ HAT の\nファン(5 秒以内)", fontsize=6.5, color="#006F8A", va="top")
    ax.plot(th.index, th.values, "o-", ms=4, lw=1.4, color="#8C99A6", label="しきい値")
    ax.plot(pr.index, pr.values, "^-", ms=4.5, lw=1.6, color="#0099BB", label="提案(予測)")
    ax.set_xlabel("冷却の効き始めまでの遅れ(むだ時間)[秒]")
    ax.set_ylabel("80℃ を守れる最小の\nファン稼働率 [%]")
    ax.set_ylim(0, 75)
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    for s_ in ["top", "right"]:
        ax.spines[s_].set_visible(False)
    fig.tight_layout(pad=0.2)
    fig.savefig(FIG / "fig_sim_slide.png", dpi=300)
