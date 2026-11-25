"""pattern 実験(開いた状態・箱)の図。

thesis/figures/fig_pattern_rise.png      位置関係ごとの上昇(2 段 × 4 列のラック図)
thesis/figures/fig_pattern_timeline.png  全体の温度の流れ(8 台 + 室温・温度計 1)
thesis/figures/fig_pattern_cool.png      冷却時(r2 のファン ON 前後、隣が冷たい/熱い)
thesis/figures/fig_pattern_idle.png      負荷をかける前の温度(部屋との差)、開いた状態と箱(2 つ渡したとき)

使い方: python scripts/fig_pattern.py experiments/20261125_pattern_open [experiments/20261125_pattern_box]
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402

plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
plt.rcParams["font.size"] = 9
FIG = Path("thesis/figures")
GRID = {"r1": (0, 0), "r2": (0, 1), "r3": (0, 2), "r4": (0, 3),
        "r5": (1, 0), "r6": (1, 1), "r7": (1, 2), "r8": (1, 3)}
HAT = {"r1", "r2", "r3", "r6", "r7"}
LOADED = {"off_r6": {"r6"}, "off_r7": {"r7"}, "off_bottom": {"r5", "r6", "r7", "r8"}}
TITLE = {"off_r6": "r6 だけ負荷", "off_r7": "r7 だけ負荷", "off_bottom": "下段 4 台に負荷"}
LABEL = {"open": "開いた状態", "box": "段ボールで囲う"}
CMAP = LinearSegmentedColormap.from_list("div", ["#2166ac", "#e8e8e8", "#b2182b"])


def kind(exp):
    return "box" if "box" in exp.name else "open"


def fig_rise(exps):
    fig, axes = plt.subplots(len(exps), 3, figsize=(7.0, 1.2 * len(exps) + 0.5), squeeze=False)
    norm = TwoSlopeNorm(vcenter=0, vmin=-4, vmax=4)
    for i, exp in enumerate(exps):
        r = pd.read_csv(exp / "results" / "rise.csv").set_index(["phase", "role"]).rise
        for j, ph in enumerate(LOADED):
            ax = axes[i, j]
            for role, (y, x) in GRID.items():
                v = r[(ph, role)]
                if role in LOADED[ph]:
                    fc, txt, tc = "#555555", f"{role}\n+{v:.0f}", "white"
                else:
                    fc, txt, tc = CMAP(norm(v)), f"{role}\n{v:+.1f}", "black"
                ax.add_patch(plt.Rectangle((x, 1 - y), 0.94, 0.9, fc=fc, ec="white", lw=1))
                ax.text(x + 0.47, 1 - y + 0.45, txt, ha="center", va="center", fontsize=7.5, color=tc)
                if role not in HAT:
                    ax.text(x + 0.9, 1 - y + 0.82, "*", ha="right", va="top", fontsize=7, color=tc)
            ax.set_xlim(0, 4)
            ax.set_ylim(0, 2)
            ax.set_aspect("equal")
            ax.axis("off")
            if i == 0:
                ax.set_title(TITLE[ph], fontsize=9)
            if j == 0:
                ax.text(-0.15, 1.0, LABEL[kind(exp)], rotation=90, ha="right", va="center", fontsize=9)
    sm = plt.cm.ScalarMappable(norm=norm, cmap=CMAP)
    cb = fig.colorbar(sm, ax=axes, orientation="vertical", fraction=0.025, pad=0.02)
    cb.set_label("負荷 10 分での上昇 [℃]\n(室温の変化を引いた)", fontsize=8)
    fig.text(0.01, 0.01, "上段 r1〜r4、下段 r5〜r8(ポート側から見て)。灰色は負荷をかけたノード。* は HAT なし(ファンなし)", fontsize=7)
    out = FIG / "fig_pattern_rise.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print(out)


def load(exp):
    tel = pd.read_csv(exp / "raw" / "telemetry.csv")
    ev = pd.read_csv(exp / "events.csv")
    amb = pd.read_csv(exp / "raw" / "ambient.csv")
    amb["name"] = amb.name.astype(str).str.strip()
    return tel, ev, amb


def fig_timeline(exps):
    fig, axes = plt.subplots(2, len(exps), figsize=(3.0 * len(exps) + 0.6, 2.5), sharex="col",
                             gridspec_kw={"height_ratios": [2.4, 1]}, squeeze=False)
    colors = plt.cm.tab10(np.arange(8))
    for j, exp in enumerate(exps):
        tel, ev, amb = load(exp)
        ps = ev[ev.event == "phase_start"]
        t0 = float(ps.ts.iloc[0])
        ax = axes[0, j]
        for i, role in enumerate(GRID):
            g = tel[tel.host == f"raspi{role[1:]}"]
            g = g.groupby(((g.ts - t0) // 30)).temp.mean()
            ax.plot(g.index * 0.5, g.values, lw=0.8, color=colors[i], label=role)
        for _, p in ps.iterrows():
            if str(p.phase).endswith("_load"):
                ax.axvline((p.ts - t0) / 60, color="0.8", lw=0.5, zorder=0)
        ax.axhline(80, color="0.3", ls="--", lw=0.7)
        ax.set_ylabel("CPU 温度 [℃]")
        ax.set_title(LABEL[kind(exp)], fontsize=9)
        ax.set_xlim(left=-5)
        a2 = axes[1, j]
        for name, lab, c in [("ハブ２", "部屋(ハブ 2)", "0.4"), ("防水温湿度計 1", "ラックの上(温度計 1)", "#b2182b")]:
            a = amb[amb.name.str.contains(name)]
            a2.plot((a.ts - t0) / 60, a.temperature, lw=1.0, color=c, label=lab)
        a2.set_ylabel("気温 [℃]")
        a2.set_xlabel("時間 [分](最初のブロックの開始から)")
        if j == len(exps) - 1:
            ax.legend(fontsize=6.5, loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False)
            a2.legend(fontsize=6.5, frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1))
    fig.tight_layout()
    out = FIG / "fig_pattern_timeline.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print(out)


def fig_cool(exps):
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    ls = {"open": "-", "box": "--"}
    for exp in exps:
        tel, ev, amb = load(exp)
        ps = ev[ev.event == "phase_start"].set_index("phase").ts
        g = tel[tel.host == "raspi2"]
        for case, c, lab in [("cool_alone", "#2166ac", "隣は休み"), ("cool_nbrs", "#b2182b", "隣も負荷")]:
            tf = ps[f"{case}_fan"]
            s = g[(g.ts >= tf - 600) & (g.ts < tf + 300)]
            s = s.groupby(((s.ts - tf) // 5)).temp.mean()
            ax.plot(s.index * 5 / 60, s.values, color=c, ls=ls[kind(exp)], lw=1.0,
                    label=f"{lab}({LABEL[kind(exp)]})")
    ax.axvline(0, color="0.5", lw=0.6)
    ax.text(0.15, ax.get_ylim()[1] - 1, "r2 のファン ON →", fontsize=7, color="0.3", va="top")
    ax.set_xlabel("ファン ON からの時間 [分]")
    ax.set_ylabel("r2 の CPU 温度 [℃]")
    ax.legend(fontsize=6.5, frameon=False, loc="lower left")
    fig.tight_layout()
    out = FIG / "fig_pattern_cool.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print(out)


def fig_idle(exps):
    """最初のブロック(off_r6)の直前 60 秒の温度 − 部屋(ハブ 2、直前 5 分〜1 分後の平均)。"""
    fig, ax = plt.subplots(figsize=(3.4, 1.9))
    x = np.arange(8)
    w = 0.8 / len(exps)
    for k, exp in enumerate(exps):
        tel, ev, amb = load(exp)
        t = float(ev[(ev.event == "phase_start") & (ev.phase == "off_r6_load")].ts.iloc[0])
        room = amb[amb.name.str.contains("ハブ２") & (amb.ts >= t - 300) & (amb.ts < t + 60)].temperature.mean()
        v = [tel[(tel.host == f"raspi{r[1:]}") & (tel.ts >= t - 60) & (tel.ts < t)].temp.mean() - room for r in GRID]
        ax.bar(x + (k - (len(exps) - 1) / 2) * w, v, w, color=["#A7B3C2", "#0099BB"][k % 2], label=LABEL[kind(exp)])
    ax.axvline(3.5, color="0.6", lw=0.6)
    ax.set_xticks(x, list(GRID))
    ax.set_xlabel("ノード(r1〜r4 上段、r5〜r8 下段)")
    ax.set_ylabel("負荷前の温度\n− 室温 [℃]")
    ax.legend(fontsize=7, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.22), ncol=2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    out = FIG / "fig_pattern_idle.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    exps = [Path(a) for a in sys.argv[1:]]
    fig_rise(exps)
    fig_timeline(exps)
    fig_cool(exps)
    if len(exps) > 1:
        fig_idle(exps)
