#!/usr/bin/env python3
"""ラックの配置図(11/26 昼、5 版目)。(a-1) 1 台を正面から、(a-2) 1 台を上から(横長、左が正面)、(b) 正面から見た配置(r1〜r8 だけ)。

(a) 1 台(上から):基板を縦に立て、ポート(USB・RJ45)を正面に向ける。PoE+ HAT は基板と平行に付き、ファンは HAT の
    外側の面(レオの写真、11/26)。風の向き(吸い込みか吹き出しか)は確かめていないので描かない。寸法はおおよそ(基板 85 mm)
(b) 配置(正面から):2 段 × 4 列、r1〜r8。囲いは上・左右・後ろ(正面と下は開放)。温度計 1 はラックの上、
    温度計 3 は左、2 は右の正面の床(11/13 の記録、レオ「左右で分かれている」)。下に PoE スイッチ
写真版は scripts/fig_rack_photo.py(本論文・スライドの予備用)
出力:thesis/figures/fig_rack_layout.png
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

plt.rcParams.update({"font.family": "Hiragino Sans", "font.size": 8})
INK, PCB, HAT, BOX, RED = "#2D3A3A", "#3a7d44", "#0099BB", "#a0522d", "#d62728"

def draw_front(cx):
    """(a-1) 1 台を正面(ポート側)から見た図。x:左右 [mm]、y:高さ [mm]。ポートは上から USB2・USB3・RJ45(写真)"""
    cx.add_patch(Rectangle((0, 0), 1.6, 56, fc=PCB, ec="none"))                      # 基板(縦に立つ)
    for y0, h, c, name in [(38, 14, "#222222", "USB2"), (22, 14, "#2b7bd0", "USB3"), (3, 16, "#bbbbbb", "RJ45")]:
        cx.add_patch(Rectangle((1.6, y0), 14, h, fc=c, ec=INK, lw=0.3))
        cx.text(-2.5, y0 + h / 2, name, ha="right", va="center", fontsize=6.5)
    cx.add_patch(Rectangle((18.5, 0), 1.6, 56, fc=HAT, ec="none"))                    # HAT(基板の右側に平行)
    cx.add_patch(Rectangle((20.1, 16), 5.5, 24, fc="#555555", ec="none"))             # ファン(HAT の外側の面)
    cx.text(19.3, 58.5, "HAT", ha="center", va="bottom", fontsize=7, color=HAT)
    cx.text(0.8, 58.5, "基板", ha="center", va="bottom", fontsize=7, color=PCB)
    cx.text(27, 44, "ファン", ha="left", va="center", fontsize=6.5)
    # 風の軸:ファンは HAT の板に平行なので、風は HAT に垂直(正面から見て左右)。吸い込みか吹き出しかは未確認なので両向き
    cx.add_patch(FancyArrowPatch((27, 28), (46, 28), arrowstyle="<|-|>", mutation_scale=9, color=INK, lw=1.1))
    cx.text(27.5, 22, "風の軸\n(向きは未確認)", ha="left", va="top", fontsize=5.5, color="0.3", linespacing=1.0)
    cx.set_xlim(-22, 58)
    cx.set_ylim(-4, 68)
    cx.set_aspect("equal")
    cx.axis("off")
    cx.set_title("(a-1) 正面から", fontsize=8, pad=1, loc="left")


def draw(ax, bx):

    # (a) 1 台を上から見た図。x:前後 [mm](0 が正面、右が奥)、y:左右 [mm]。
    #     正面に立って奥を向いたときの右手側が図の下側になる(HAT は右側なので基板の下)
    ax.add_patch(Rectangle((0, 26), 85, 1.6, fc=PCB, ec="none"))                 # 基板(縦に立つ)
    ax.add_patch(Rectangle((0, 11), 6, 15, fc="#bbbbbb", ec=INK, lw=0.4))        # ポート(部品の面 = HAT 側に出る)
    ax.add_patch(Rectangle((14, 7.9), 65, 1.6, fc=HAT, ec="none"))               # HAT(基板と平行)
    ax.add_patch(Rectangle((38, 2.4), 22, 5.5, fc="#555555", ec="none"))         # ファン(HAT の外側の面)
    ax.text(87, 26.8, "基板", ha="left", va="center", fontsize=7.5, color=PCB)
    ax.text(81, 8.7, "PoE+ HAT", ha="left", va="center", fontsize=7.5, color=HAT)
    ax.text(49, 0.5, "ファン", ha="center", va="top", fontsize=7.5)
    ax.text(8, 18, "ポート", ha="left", va="center", fontsize=7.5)
    ax.add_patch(FancyArrowPatch((-3, 18), (-15, 18), arrowstyle="-|>", mutation_scale=8, color=INK, lw=0.9))
    ax.text(-17, 18, "正面", ha="right", va="center", fontsize=7.5)
    ax.set_xlim(-32, 114)
    ax.set_ylim(-7, 31)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("(a-2) 上から", fontsize=8, pad=1, loc="left")

    # (b) 配置(正面から)
    W, H, GX, GY = 1.0, 0.62, 0.14, 0.14
    for i in range(8):
        row, col = divmod(i, 4)
        x, y = col * (W + GX), (1 - row) * (H + GY) + 0.38
        bx.add_patch(FancyBboxPatch((x, y), W, H, boxstyle="round,pad=0,rounding_size=0.06", fc="#f4f4f4", ec=INK, lw=0.6))
        bx.text(x + W / 2, y + H / 2, f"r{i + 1}", ha="center", va="center", fontsize=9, weight="bold", color=INK)
    tw = 4 * W + 3 * GX
    top = 0.38 + 2 * H + GY
    bx.add_patch(Rectangle((-0.05, 0.05), tw + 0.1, 0.28, fc="#888888", ec="none"))
    bx.text(tw / 2, 0.19, "PoE スイッチ", ha="center", va="center", fontsize=6.5, color="white")
    bx.plot([-0.16, -0.16, tw + 0.16, tw + 0.16], [0.0, top + 0.32, top + 0.32, 0.0], color=BOX, lw=1.2, ls="--")
    bx.text(tw / 2, top + 0.39, "囲い:上・左右・後ろ(正面と下は開放)", ha="center", va="bottom", fontsize=7, color=BOX)
    for x, y, name, ha in [(tw / 2, top + 0.16, "温度計 1", "left"), (0.1, -0.14, "温度計 3", "left"),
                           (tw - 0.1, -0.14, "温度計 2", "right")]:
        bx.plot(x, y, marker="o", ms=3.6, color=RED)
        bx.text(x + (0.08 if ha == "left" else -0.08), y, name, ha=ha, va="center", fontsize=6.5, color=RED)
    bx.text(tw + 0.25, 0.38 + H + GY + H / 2, "上段", ha="left", va="center", fontsize=7.5)
    bx.text(tw + 0.25, 0.38 + H / 2, "下段", ha="left", va="center", fontsize=7.5)
    bx.set_xlim(-0.3, tw + 0.75)
    bx.set_ylim(-0.3, top + 0.62)
    bx.set_aspect("equal")
    bx.axis("off")
    bx.set_title("(b) 正面から見た配置", fontsize=8, pad=1, loc="left")


# レジュメ・成果の要旨用:上の段に (a-1)(a-2)、下の段に (b)
fig = plt.figure(figsize=(3.4, 2.75))
gs = fig.add_gridspec(2, 2, height_ratios=[0.95, 1.6], width_ratios=[0.8, 1])
cx, ax, bx = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[1, :])
draw_front(cx)
draw(ax, bx)
for a_ in (cx, ax):
    a_.set_anchor("N")  # 同じ段の図を上端でそろえ、題名の高さを合わせる
fig.tight_layout(pad=0.1, h_pad=0.2, w_pad=0.1)
fig.savefig("thesis/figures/fig_rack_layout.png", dpi=300, bbox_inches="tight", pad_inches=0.02)
# スライド用:(a-1)(a-2)(b) を横に並べる
fig, (cx, ax, bx) = plt.subplots(1, 3, figsize=(6.2, 1.8), gridspec_kw={"width_ratios": [0.7, 1.0, 1.05]})
draw_front(cx)
draw(ax, bx)
for a_ in (cx, ax, bx):
    a_.set_anchor("N")  # 3 つの図を上端でそろえ、題名の高さを合わせる
fig.tight_layout(pad=0.1, w_pad=0.6)
fig.savefig("thesis/figures/fig_rack_layout_wide.png", dpi=300, bbox_inches="tight", pad_inches=0.02)
