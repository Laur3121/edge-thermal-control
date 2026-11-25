#!/usr/bin/env python3
"""ラックの配置図(11/26 描き直し。先生の指摘:風の向き・ポート・HAT の付き方・「縦向き」が分からない)。

(a) 正面(ポート側)から見た図:各ノードはボードを縦に立てて固定。ポートは上から USB2・USB3・RJ45、
    PoE+ HAT はボードの右側(レオ確認、11/26)
(b) 横から見た図:囲いあり(上・左右・後ろを覆い、正面と下は開いている)、温度計の位置、PoE スイッチ
ラック:GeeekPi DeskPi RackMate T0(10 インチ、4U)。
出力:thesis/figures/fig_rack_layout.png
"""
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

plt.rcParams.update({"font.family": "Hiragino Sans", "font.size": 8})
INK, BOX, PCB, HATC = "#2D3A3A", "#a0522d", "#3a7d44", "#555555"

fig, (ax, bx) = plt.subplots(1, 2, figsize=(3.45, 1.75), gridspec_kw={"width_ratios": [2.6, 1]})

# (a) 正面
W, H, GX, GY = 1.0, 1.0, 0.08, 0.18
for i in range(8):
    row, col = divmod(i, 4)
    x, y = col * (W + GX), (1 - row) * (H + GY) + 0.3
    ax.add_patch(Rectangle((x, y), W, H, fc="#f4f4f4", ec=INK, lw=0.6))
    ax.add_patch(Rectangle((x + 0.24, y + 0.08), 0.05, 0.84, fc=PCB, ec="none"))  # ボード(縦に立つ)
    for (y0, h, c) in [(0.66, 0.24, "#222222"), (0.38, 0.24, "#2b7bd0"), (0.08, 0.26, "#bbbbbb")]:
        ax.add_patch(Rectangle((x + 0.29, y + y0), 0.3, h, fc=c, ec="none"))
    ax.add_patch(Rectangle((x + 0.64, y + 0.08), 0.12, 0.84, fc=HATC, ec="none"))  # HAT
    ax.text(x + 0.88, y + 0.5, f"r{i + 1}", ha="center", va="center", fontsize=7, rotation=90, color=INK)
tw = 4 * W + 3 * GX
ax.add_patch(Rectangle((-0.05, 0.05), tw + 0.1, 0.22, fc="#888888", ec="none"))
ax.text(tw / 2, 0.16, "PoE スイッチ", ha="center", va="center", fontsize=6.5, color="white")
# 凡例(最初のノードに引き出し線)
x0, y0 = 0.0, H + GY + 0.3
for (yy, lab) in [(0.78, "USB2"), (0.5, "USB3"), (0.21, "RJ45")]:
    ax.annotate(lab, xy=(x0 + 0.44, y0 + yy), xytext=(-0.55, y0 + yy), fontsize=6, va="center",
                arrowprops=dict(arrowstyle="-", lw=0.4, color="0.4"))
ax.annotate("ボード", xy=(x0 + 0.26, y0 + 0.95), xytext=(-0.55, y0 + 1.13), fontsize=6, va="center",
            arrowprops=dict(arrowstyle="-", lw=0.4, color="0.4"))
ax.annotate("PoE+ HAT\n(ファン付き)", xy=(x0 + 3 * (W + GX) + 0.7, y0 + 0.95), xytext=(tw - 0.6, y0 + 1.28),
            fontsize=6, ha="center", va="center", arrowprops=dict(arrowstyle="-", lw=0.4, color="0.4"))
ax.text(tw + 0.08, 0.3 + H / 2, "下段", fontsize=7, va="center")
ax.text(tw + 0.08, 0.3 + H + GY + H / 2, "上段", fontsize=7, va="center")
ax.set_xlim(-0.6, tw + 0.45)
ax.set_ylim(0, 2 * H + GY + 0.3 + 0.45)
ax.set_aspect("equal")
ax.axis("off")
ax.set_title("(a) 正面(ポート側)", fontsize=7.5, pad=2)

# (b) 横(左が正面)。ボードの面が見える向き
D, NH = 0.95, 0.62
for k, y in enumerate([0.35, 0.35 + NH + 0.12]):
    bx.add_patch(Rectangle((0.1, y), D, NH, fc="#dfeee2", ec=PCB, lw=0.6))
    bx.add_patch(Rectangle((0.1, y + 0.06), 0.1, NH - 0.12, fc="#bbbbbb", ec="none"))
    bx.text(0.1 + D / 2 + 0.05, y + NH / 2, "上段" if k else "下段", ha="center", va="center", fontsize=6.5)
bx.add_patch(Rectangle((0.0, 0.05), D + 0.2, 0.22, fc="#888888", ec="none"))
top = 0.35 + 2 * NH + 0.12
bx.plot([-0.02, D + 0.32, D + 0.32], [top + 0.3, top + 0.3, 0.02], color=BOX, lw=1.2, ls="--")
bx.text(D / 2 + 0.15, top + 0.36, "囲い", ha="center", va="bottom", fontsize=6, color=BOX)
bx.text(-0.08, top - 0.25, "正面\n開放", fontsize=6, ha="right", va="center", color=BOX)
bx.plot(0.6, top + 0.15, marker="o", ms=3.5, color="#d62728")
bx.text(0.75, top + 0.15, "温度計 1", fontsize=5.5, ha="left", va="center", color="#d62728")
bx.plot(-0.3, 0.04, marker="o", ms=3.5, color="#d62728")
bx.text(-0.3, 0.13, "温度計\n2・3", fontsize=5.5, ha="center", va="bottom", color="#d62728")
bx.text(0.1, 0.35 + 2 * NH + 0.13, "ポート", fontsize=5, ha="left", va="bottom", color="0.35")
bx.set_xlim(-0.75, D + 0.45)
bx.set_ylim(0, top + 0.6)
bx.set_aspect("equal")
bx.axis("off")
bx.set_title("(b) 横(左が正面)", fontsize=7.5, pad=2)
fig.tight_layout(pad=0.1, w_pad=0.2)
fig.savefig("thesis/figures/fig_rack_layout.png", dpi=300, bbox_inches="tight", pad_inches=0.02)
