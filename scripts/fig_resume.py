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


def fig_fan(box_exp="experiments/20261125_box_control", box_label="囲いあり", bad=("self_fixed", "proposed"), wide=False,
            omit_bad=True, out=None):
    """Q3:方式ごとの (a) ファン稼働率 と (b) 最高温度(全ノード・全巡の最大)。80℃ を超えた時間(合計)は (b) に赤で書く。
    囲いなし = 11/14(3 台 × 3 巡)、囲いあり = box_exp(8 台 × 2 巡)。
    bad:パラメータに誤りがあった方式(11/25 夜はファンの効きを 6 台で過大に見積もっていた)。斜線・白抜きにして注を書く。
    omit_bad=True(本文用、11/26 にレオと決めた):bad の方式は描かず「再実験中」と書く。False:斜線・白抜きで描く(予備スライド用)
    wide=False はレジュメ用(上下 2 段、fig_res_fan.png)、True はスライド用(横 2 つ、fig_res_fan_wide.png)"""
    conds = [("always", "常時 ON"), ("threshold", "しきい値"), ("self_fixed", "自ノード\nの予測"), ("proposed", "提案")]
    m = pd.read_csv("experiments/20261114_compare/results/control_metrics.csv")
    m["cond"] = m.condition.replace({"selffixed": "self_fixed"})
    sets = [("囲いなし", m.rename(columns={"fan_on_ratio": "duty", "over_limit_s": "over", "T_max": "tmax"}), "#A7B3C2", ())]
    if box_exp is not None:
        b = pd.read_csv(Path(box_exp) / "results" / "control_summary.csv")
        b["cond"] = b.cond.replace({"selffixed": "self_fixed"})
        sets.append((box_label, b.rename(columns={"over80_s": "over", "max_temp": "tmax"}), "#0099BB", bad))
    if wide:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.6, 1.8))
    else:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(3.3, 2.4), sharex=True, gridspec_kw={"height_ratios": (1, 1.3)})
    w = 0.8 / len(sets)
    for j, (lab, df, c, badset) in enumerate(sets):
        for i, (cond, _) in enumerate(conds):
            g = df[df.cond == cond]
            if g.empty:
                continue
            x = i + (j - (len(sets) - 1) / 2) * w
            isbad = cond in badset
            if isbad and omit_bad:
                ax1.text(x, 2, "再\n実\n験\n中", ha="center", va="bottom", fontsize=5.5, color="0.35", linespacing=1.0)
                ax2.text(x, 61, "再\n実\n験\n中", ha="center", va="bottom", fontsize=5.5, color="0.35", linespacing=1.0)
                continue
            v = g.duty.mean() * 100
            ax1.bar(x, v, w * 0.92, color=c, edgecolor="white", linewidth=0, hatch="////" if isbad else None,
                    label=lab if i == 0 else None)
            ax1.text(x, v + 1.5, f"{v:.0f}", ha="center", va="bottom", fontsize=6)
            t = g.tmax.max()
            ax2.plot([x, x], [60, t], color=c, lw=1.0, zorder=1)
            ax2.plot(x, t, "o", ms=4.5, color=c, mfc="white" if isbad else c, mew=1.2, zorder=3)
            ax2.text(x, t + 0.8, f"{t:.1f}", ha="center", va="bottom", fontsize=5.3)
            if g.over.sum() >= 1:
                ax2.text(x, t + 3.3, f"{g.over.sum():.0f}秒", ha="center", va="bottom", fontsize=5.3, color="#C0392B")
    ax1.legend(fontsize=6.3, frameon=False, loc="upper right", ncol=2)
    ax1.set_ylabel("(a) ファン稼働率 [%]" if wide else "(a) 稼働率 [%]", fontsize=7)
    ax1.set_ylim(0, 125)
    ax1.set_yticks([0, 50, 100])
    ax2.axhline(80, color="#C0392B", lw=0.7, ls="--", zorder=0)
    ax2.set_ylabel("(b) 最高温度 [℃]", fontsize=7)
    ax2.set_ylim(60, 93)
    ax2.set_yticks([60, 70, 80, 90])
    for ax in (ax1, ax2):
        ax.set_xticks(range(len(conds)), [n for _, n in conds], fontsize=6.5)
        ax.set_xlim(-0.6, len(conds) - 0.4)
        ax.tick_params(labelsize=6.5)
        for s_ in ["top", "right"]:
            ax.spines[s_].set_visible(False)
    note = "(b) 赤の破線:80℃、赤字:80℃ を超えた時間(全ノード・全巡の合計)"
    if len(sets) > 1 and sets[1][3] and omit_bad:
        note += "\n囲いありの予測の 2 方式は、パラメータを同定し直して再実験中"
    elif len(sets) > 1 and sets[1][3]:
        note += ("\n斜線・白抜き:囲いありの自ノードの予測と提案は、ファンの効きを過大に見積もったパラメータのまま(同定し直して再実験中)"
                 if wide else "\n斜線・白抜き:ファンの効きを過大に見積もったパラメータのまま(再実験中)")
    nl = note.count("\n") + 1
    fig.text(0.01, 0.005, note, ha="left", va="bottom", fontsize=5.6, color="0.3", linespacing=1.25)
    fig.tight_layout(pad=0.2, h_pad=0.4, rect=(0, (0.062 if wide else 0.036) * nl + 0.01, 1, 1))
    fig.savefig(FIG / (out or ("fig_res_fan_wide.png" if wide else "fig_res_fan.png")), dpi=300)


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


def fig_sim_trace(L_list=(0, 60), pattern="compare"):
    """予備スライド・論文用:「こうなるはず」の時系列(11/22 のシミュレーション、11/26 に図示)。
    設定は実機の実験と同じ(しきい値 75/70℃、提案 α = 2・δ = 0.5)で、後から選んだ値ではない。
    冷却の効き始めの遅れ(むだ時間)L ごとに、温度とファンの指令を並べる。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sim_slow_cooling as S
    plant, cp = S.load_models()
    u = S.load_patterns()[pattern]
    t = np.arange(len(u)) * S.DT / 60
    fig = plt.figure(figsize=(6.6, 2.5))
    gs = fig.add_gridspec(3, len(L_list), height_ratios=(0.45, 3, 0.9), hspace=0.12, wspace=0.12)
    styles = {"threshold": ("しきい値(75℃ で ON)", "#8C99A6", 75.0), "proposed": ("提案(予測)", "#0099BB", 2.0)}
    for j, L in enumerate(L_list):
        axl = fig.add_subplot(gs[0, j])
        axt = fig.add_subplot(gs[1, j], sharex=axl)
        axf = fig.add_subplot(gs[2, j], sharex=axl)
        axl.fill_between(t, 0, u * 4, step="post", color="0.8", lw=0)
        axl.set_ylim(0, 4.4)
        axl.set_yticks([])
        axl.set_title(f"冷却の遅れ {L} 秒" + ("(PoE+ HAT 相当)" if L == 0 else ""), fontsize=7.5, pad=2)
        if j == 0:
            axl.set_ylabel("負荷\n(0〜4 コア)", fontsize=6, rotation=0, ha="right", va="center")
        for k, (mode, (lab, c, val)) in enumerate(styles.items()):
            x = S.simulate(plant, cp, u, "dead", L, mode, val, trace=True)
            axt.plot(t, x["T"], color=c, lw=1.2, label=f"{lab}:稼働 {x['fan_ratio'] * 100:.0f}%、最高 {x['T_max']:.1f}℃")
            axf.fill_between(t, k, k + 0.8 * x["cmd"], step="post", color=c, lw=0)
        axt.axhline(80, color="#C0392B", lw=0.7, ls="--")
        axt.set_ylim(42, 85)
        axt.set_yticks([50, 60, 70, 80])
        axt.legend(fontsize=5.6, frameon=False, loc="lower right", handlelength=1.2)
        axf.set_ylim(-0.1, 2)
        axf.set_yticks([0.4, 1.4], ["しきい値", "提案"] if j == 0 else ["", ""], fontsize=6)
        axf.set_xlabel("時間 [分]", fontsize=7)
        if j == 0:
            axt.set_ylabel("温度 [℃]", fontsize=7)
            axf.set_ylabel("ファン", fontsize=6.5, rotation=0, ha="right", va="center", labelpad=28)
        else:
            axt.tick_params(labelleft=False)
        for ax in (axl, axt):
            ax.tick_params(labelbottom=False)
        for ax in (axl, axt, axf):
            ax.tick_params(labelsize=6.5)
            for s_ in ["top", "right"]:
                ax.spines[s_].set_visible(False)
    fig.subplots_adjust(left=0.1, right=0.99, top=0.92, bottom=0.15)
    fig.savefig(FIG / "fig_sim_trace.png", dpi=300)
