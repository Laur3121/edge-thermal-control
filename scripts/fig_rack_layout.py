#!/usr/bin/env python3
"""ラックの配置図(11/25 の pattern 実験)。thesis/figures/fig_rack_layout.png に保存。"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

plt.rcParams.update({"font.family": "Hiragino Sans", "font.size": 9})
HAT = {1, 2, 3, 6, 7}
fig, ax = plt.subplots(figsize=(3.4, 2.1))
W, H, GX, GY = 1.0, 1.0, 0.15, 0.25
for i in range(8):
    row, col = divmod(i, 4)
    x, y = col * (W + GX), (1 - row) * (H + GY)
    n = i + 1
    ax.add_patch(FancyBboxPatch((x, y), W, H, boxstyle="round,pad=0.02",
                                fc="#9ecae1" if n in HAT else "white", ec="black", lw=1))
    ax.text(x + W / 2, y + H * 0.62, f"r{n}", ha="center", va="center", fontsize=10, weight="bold")
    ax.text(x + W / 2, y + H * 0.28, "HAT" if n in HAT else "熱源のみ", ha="center", va="center", fontsize=7.5)
tw, th = 4 * W + 3 * GX, 2 * H + GY
ax.add_patch(Rectangle((-0.12, -0.12), tw + 0.24, th + 0.24, fill=False, ls="--", lw=1, ec="#a0522d"))
ax.text(tw + 0.12, th + 0.17, "段ボール箱(囲いの条件)", ha="right", va="bottom", fontsize=7.5, color="#a0522d")
ax.text(-0.25, H + GY + H / 2, "上段", ha="right", va="center", fontsize=8)
ax.text(-0.25, H / 2, "下段", ha="right", va="center", fontsize=8)
ax.annotate("", xy=(tw + 0.35, th), xytext=(tw + 0.35, 0), arrowprops=dict(arrowstyle="->", lw=0.8))
ax.text(tw + 0.45, th / 2, "上", ha="left", va="center", fontsize=8)
ax.set_xlim(-0.8, tw + 0.7); ax.set_ylim(-0.3, th + 0.5); ax.set_aspect("equal"); ax.axis("off")
fig.tight_layout(pad=0.1)
fig.savefig("thesis/figures/fig_rack_layout.png", dpi=300)
