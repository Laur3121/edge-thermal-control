#!/usr/bin/env python3
"""ラックの配置図(写真版、11/26)。模式図は「微妙」(レオ)・「騙していると取られかねない」(先生)ので、実物の写真に名前を入れる。

(a) 正面(ポート側)の写真:r1〜r8、上段・下段、ポートの名前(USB2・USB3・RJ45、r4 で示す)
(b) 横から見た模式図:囲い(上・後ろ・左右)、正面は開放、温度計の位置
写真:レオが 11/25 夜に撮った正面の写真(ラックの部分だけを切り出す。部屋は写さない)
出力:thesis/figures/fig_rack_photo.png(本論文・スライドの予備。レジュメ等は模式図 fig_rack_layout.png)

使い方:python scripts/fig_rack_photo.py <写真のパス>
"""
import sys

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from PIL import Image

plt.rcParams.update({"font.family": "Hiragino Sans", "font.size": 8})
BOX, PCB, INK = "#a0522d", "#3a7d44", "#2D3A3A"


def main(photo):
    im = Image.open(photo)
    im = im.crop((400, 180, 2880, 1960)).resize((1240, 890))
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(3.45, 1.85), gridspec_kw={"width_ratios": [2.55, 1]})
    ax.imshow(im)
    ax.axis("off")
    lab = dict(fontsize=7, color="white", ha="center", va="center", weight="bold",
               bbox=dict(boxstyle="round,pad=0.15", fc="#0099BB", ec="none"))
    for name, x, y in [("r1", 300, 95), ("r2", 535, 95), ("r3", 770, 95), ("r4", 1005, 95),
                       ("r5", 320, 525), ("r6", 545, 525), ("r7", 770, 525), ("r8", 985, 525)]:
        ax.text(x, y, name, **lab)
    for name, y in [("USB2", 170), ("USB3", 262), ("RJ45", 352)]:
        ax.annotate(name, xy=(1040, y), xytext=(1235, y), fontsize=6, color="white", ha="right", va="center",
                    bbox=dict(boxstyle="round,pad=0.1", fc="black", ec="none", alpha=0.75),
                    arrowprops=dict(arrowstyle="-", color="white", lw=0.7))
    ax.text(15, 240, "上段", fontsize=7, color="white", va="center",
            bbox=dict(boxstyle="round,pad=0.12", fc="black", ec="none", alpha=0.75))
    ax.text(15, 660, "下段", fontsize=7, color="white", va="center",
            bbox=dict(boxstyle="round,pad=0.12", fc="black", ec="none", alpha=0.75))
    ax.set_title("(a) 正面(ポート側)", fontsize=7.5, pad=2)

    # (b) 横から見た模式図(左が正面)
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
    bx.text(0.55, -0.02, "PoE スイッチ", fontsize=5, ha="center", va="top", color="0.35")
    bx.set_xlim(-0.75, D + 0.45)
    bx.set_ylim(-0.2, top + 0.6)
    bx.set_aspect("equal")
    bx.axis("off")
    bx.set_title("(b) 横(左が正面)", fontsize=7.5, pad=2)
    fig.tight_layout(pad=0.1, w_pad=0.2)
    fig.savefig("thesis/figures/fig_rack_photo.png", dpi=300, bbox_inches="tight", pad_inches=0.02)


if __name__ == "__main__":
    main(sys.argv[1])
