"""論文・スライド・レジュメ共通の図を作る(日本語ラベル)。

出力:thesis/figures/*.png(300 dpi)。生ログは読むだけで書き換えない。
  python scripts/make_figures.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "thesis" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
EXP = ROOT / "experiments"

plt.rcParams.update({
    "font.family": "Hiragino Sans",
    "font.size": 10,
    "axes.titlesize": 10,
    "axes.labelsize": 10,
    "legend.fontsize": 8.5,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
})

COL = {"nofan": "#c0392b", "always": "#7f8c8d", "threshold": "#e67e22",
       "selffixed": "#27ae60", "proposed": "#1f5fbf"}
NAME = {"nofan": "ファンなし", "always": "常時 ON", "threshold": "しきい値(75/70℃)",
        "selffixed": "予測 + 固定マージン", "proposed": "提案"}


def phase_windows(events: pd.DataFrame) -> dict:
    """条件ごと(r1_proposed など)の開始・終了時刻。s1〜s6 をまとめる。"""
    st = events[events.event == "phase_start"].set_index("phase").ts
    en = events[events.event == "phase_end"].set_index("phase").ts
    out = {}
    for ph in st.index:
        if "_s" not in ph:
            continue
        key = ph.rsplit("_s", 1)[0]
        a, b = st[ph], en.get(ph, np.nan)
        lo, hi = out.get(key, (np.inf, -np.inf))
        out[key] = (min(lo, a), max(hi, b))
    return out


def fig_control_round():
    """比較実験の 1 巡目、ノード A の 4 条件を並べる(拡大版)。"""
    d = EXP / "20261114_compare"
    ev = pd.read_csv(d / "events.csv")
    tel = pd.read_csv(d / "raw" / "telemetry.csv", usecols=["ts", "host", "temp", "cpu", "fan"])
    ctl = pd.read_csv(d / "control.csv")
    win = phase_windows(ev)
    tel = tel[tel.host == "raspi1"].sort_values("ts")
    ctl = ctl[ctl.host == "raspi1"]
    conds = ["nofan", "always", "threshold", "proposed"]
    fig, axes = plt.subplots(len(conds), 1, figsize=(6.6, 7.2), sharex=True, sharey=True)
    for ax, c in zip(axes, conds):
        t0, t1 = win[f"r1_{c}"]
        w = tel[(tel.ts >= t0) & (tel.ts <= t1)].copy()
        w["m"] = (w.ts - t0) / 60
        w5 = w.set_index(pd.to_datetime(w.ts, unit="s")).resample("5s").mean(numeric_only=True)
        ax.fill_between(w5.m, 40, 40 + 8 * w5.fan.clip(0, 1), step="post",
                        color=COL[c], alpha=0.25, lw=0, label="ファン ON")
        ax.plot(w5.m, 40 + 8 * w5.cpu / 100, color="#555", lw=0.8, ls=":", label="CPU 使用率(右下の目盛り)")
        ax.plot(w5.m, w5.temp, color="black", lw=1.1, label="CPU 温度")
        ax.axhline(80, color="#c0392b", lw=0.9, ls="--", label="80℃")
        cw = ctl[(ctl.ts >= t0) & (ctl.ts <= t1)]
        if len(cw):
            ax.plot((cw.ts - t0) / 60, cw.tsafe, color="#e67e22", lw=0.9, ls="-.",
                    label="安全閾値 $T_{\\mathrm{safe}}$" if c == "proposed" else "ON の温度")
        on = w5.fan.mean()
        note = "(82℃ での強制 ON のみ)" if c == "nofan" else ""
        ax.set_title(f"{NAME[c]}  最高 {w5.temp.max():.1f}℃ / ファン稼働 {on * 100:.0f}%{note}", loc="left")
        ax.set_ylim(38, 86)
        ax.set_ylabel("温度 [℃]")
    axes[-1].set_xlabel("負荷パターン開始からの時間 [分]")
    axes[-1].set_xlim(0, 20)
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    hs = [Line2D([], [], color="black", lw=1.1, label="CPU 温度"),
          Line2D([], [], color="#c0392b", lw=0.9, ls="--", label="80℃"),
          Line2D([], [], color="#e67e22", lw=0.9, ls="-.", label="ON の温度 / 安全閾値"),
          Patch(color="#999", alpha=0.4, label="ファン ON(下の帯)"),
          Line2D([], [], color="#555", lw=0.8, ls=":", label="CPU 使用率(0〜100% を 40〜48℃ の高さで表示)")]
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.legend(handles=hs, loc="upper center", ncol=3, frameon=False, fontsize=8, bbox_to_anchor=(0.5, 1.0))
    fig.savefig(OUT / "fig_control_round.png")
    plt.close(fig)


def fig_control_bars():
    """5 条件のファン稼働率と最高温度(9 回の平均、ひげは最小〜最大)。"""
    m = pd.read_csv(EXP / "20261114_compare" / "results" / "control_metrics.csv")
    order = ["nofan", "always", "threshold", "selffixed", "proposed"]
    g = m.groupby("condition")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.6, 2.8))
    x = np.arange(len(order))
    for ax, col, lab, scale in [(a1, "fan_on_ratio", "ファン稼働率 [%]", 100), (a2, "T_max", "最高温度 [℃]", 1)]:
        mean = g[col].mean().reindex(order) * scale
        lo = g[col].min().reindex(order) * scale
        hi = g[col].max().reindex(order) * scale
        ax.bar(x, mean, color=[COL[o] for o in order], width=0.55)
        ax.errorbar(x, mean, yerr=[mean - lo, hi - mean], fmt="none", ecolor="black", lw=0.8, capsize=2)
        ax.set_xticks(x, [NAME[o].replace("(75/70℃)", "").replace("予測 + 固定マージン", "予測 +\n固定マージン") for o in order], rotation=0, fontsize=7.5)
        ax.set_xlim(-0.5, len(order) - 0.1)
        ax.set_ylabel(lab)
        for xi, v in zip(x, mean):
            ax.text(xi + 0.36, v, f"{v:.0f}" if scale == 100 else f"{v:.1f}",
                    ha="left", va="center", fontsize=7.5)
    a2.axhline(80, color="#c0392b", lw=0.9, ls="--")
    a2.set_ylim(55, 88)
    a1.set_ylim(0, 112)
    fig.tight_layout()
    fig.savefig(OUT / "fig_control_bars.png")
    plt.close(fig)


def fig_tradeoff():
    """シミュレーション:設定を変えたときのファン稼働率と最高温度。"""
    r = pd.read_csv(EXP / "20261114_sim_tradeoff" / "results.csv")
    pats = [("compare", "比較実験と同じ負荷"), ("random1", "ランダムな負荷 1")]
    modes = [("threshold", "しきい値(ON の温度 60〜79℃)"), ("self_fixed", "予測 + 固定マージン(0〜8℃)"),
             ("proposed", "提案(α 0〜5)")]
    cmap = {"threshold": COL["threshold"], "self_fixed": COL["selffixed"], "proposed": COL["proposed"]}
    mk = {"threshold": "o", "self_fixed": "s", "proposed": "^"}
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.9), sharey=True)
    for ax, (p, title) in zip(axes, pats):
        rp = r[r.pattern == p]
        for mo, lab in modes:
            q = rp[rp["mode"] == mo].sort_values("fan_ratio")
            ax.plot(q.fan_ratio * 100, q.T_max, marker=mk[mo], ms=3, lw=1, color=cmap[mo], label=lab)
        ax.axhline(80, color="#c0392b", lw=0.9, ls="--")
        ax.set_title(title, loc="left")
        ax.set_xlabel("ファン稼働率 [%]")
    axes[0].set_ylabel("最高温度 [℃]")
    axes[0].legend(frameon=False, fontsize=7.5, loc="upper right")
    fig.tight_layout()
    fig.savefig(OUT / "fig_tradeoff.png")
    plt.close(fig)


def fig_slow_cooling(column=False):
    """シミュレーション:冷却の効きの遅れと、80℃ を超えない中での最小ファン稼働率(4 パターンの平均)。
    column=True はレジュメの 1 段の幅に入れる縦 2 段の版(fig_slow_cooling_col.png)。"""
    sm = pd.read_csv(EXP / "20261122_sim_slow_cooling" / "summary.csv")
    sm = sm.dropna(subset=["threshold", "proposed"])  # どの方式も 80℃ を超える条件(L=120 s・ランダム 1)を除く
    kinds = [("dead", "(a) むだ時間(指令が L 秒後に効く)", "むだ時間 L [秒]"),
             ("lag", "(b) 1 次遅れ(効きが時定数 τ でゆっくり変わる)", "時定数 τ [秒]")]
    if column:
        fig, axes = plt.subplots(2, 1, figsize=(3.3, 2.9), sharey=True)
    else:
        fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.9), sharey=True)
    for ax, (k, title, xl) in zip(axes, kinds):
        g = sm[sm.kind == k]
        th = g[g.rule == "off"].groupby("delay_s").threshold.mean() * 100
        off = g[g.rule == "off"].groupby("delay_s").proposed.mean() * 100
        nxt = g[g.rule == "next"].groupby("delay_s").proposed.mean() * 100
        ax.plot(th.index, th.values, "o-", ms=4, lw=1.2, color=COL["threshold"], label="しきい値")
        ax.plot(off.index, off.values, "^-", ms=4, lw=1.2, color=COL["proposed"], label="提案(事前に決めた判断)")
        ax.plot(nxt.index, nxt.values, "^--", ms=4, lw=1.2, color="#7fa6e0", label="提案(ぎりぎりまで待つ判断)")
        ax.axvspan(-4, 4, color="#dfe6ee", zorder=0)
        ax.set_title(title, loc="left", fontsize=9)
        ax.set_xlabel(xl)
        ax.set_ylim(0, None)
    if column:
        for ax in axes:
            ax.set_ylabel("最小の稼働率 [%]")
            ax.set_ylim(0, 100)  # 凡例を線に重ねないため上を空ける
    else:
        axes[0].set_ylabel("最小のファン稼働率 [%]")
    if column:  # パネルが低いので、凡例を詰めて線に重ねない
        axes[0].legend(frameon=False, fontsize=6.3, loc="upper left", labelspacing=0.2,
                       handlelength=1.5, borderaxespad=0.1)
    else:
        axes[0].legend(frameon=False, fontsize=7.2, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / ("fig_slow_cooling_col.png" if column else "fig_slow_cooling.png"))
    plt.close(fig)


def fig_slow_cooling_resume():
    """レジュメ(2 ページ版)用:むだ時間だけ、しきい値方式と予測の 2 本に絞った図(fig_slow_cooling_resume.png)。
    予測は事前に決めた判断(rule=off)。4 パターンの平均(L=120 秒は 3 パターン)。"""
    sm = pd.read_csv(EXP / "20261122_sim_slow_cooling" / "summary.csv")
    sm = sm.dropna(subset=["threshold", "proposed"])
    g = sm[(sm.kind == "dead") & (sm.rule == "off")]
    th = g.groupby("delay_s").threshold.mean() * 100
    pr = g.groupby("delay_s").proposed.mean() * 100
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    ax.axvspan(-3, 5, color="#dfe6ee", zorder=0)
    ax.text(7, 66, "PoE+ HAT の\nファン(5 秒以内)", fontsize=8, color="#555", va="top")
    ax.plot(th.index, th.values, "o-", ms=5, lw=1.8, color=COL["threshold"])
    ax.plot(pr.index, pr.values, "^-", ms=5, lw=1.8, color=COL["proposed"])
    ax.text(th.index[-1] - 2, th.values[-1] + 4, "しきい値方式", color=COL["threshold"], fontsize=9, ha="right")
    ax.text(pr.index[-1] + 2, 12, "予測(提案)", color=COL["proposed"], fontsize=9, ha="right")
    x = 60
    ax.annotate("", xy=(x, pr[x] + 1), xytext=(x, th[x] - 1),
                arrowprops=dict(arrowstyle="<->", color="#333", lw=0.9))
    ax.text(x + 3, (th[x] + pr[x]) / 2 + 4, f"{th[x] - pr[x]:.0f}\nポイント", fontsize=8, va="center", ha="left")
    ax.set_xlabel("冷却の効果発現時間 L [秒]")
    ax.set_ylabel("80℃ を超えない最小の\nファン稼働率 [%]")
    ax.set_xlim(-3, 125)
    ax.set_ylim(0, 80)
    fig.tight_layout()
    fig.savefig(OUT / "fig_slow_cooling_resume.png")
    plt.close(fig)


def fig_predict():
    """RQ2:ランダムの実験の後半(同定に使っていない区間)の A で、実測と 30 秒先の予測、予測 + マージン。"""
    import json
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "scripts"))
    from eval_validate import resample
    from etc.kalman import NoiseParams, run_kf
    from etc.model import ThermalParams

    d = EXP / "20261114_validate_random"
    tel = pd.read_csv(d / "raw" / "telemetry.csv", usecols=["ts", "host", "temp", "cpu", "fan", "clock"])
    ev = pd.read_csv(d / "events.csv")
    amb = pd.read_csv(d / "raw" / "ambient.csv")
    amb = amb[amb.name.str.contains("ハブ")].sort_values("ts")
    prm = json.loads((d / "results" / "eval" / "params.json").read_text())
    nodeA = prm["nodes"]["A (11/14 first half)"]
    mm = pd.read_csv(d / "results" / "eval" / "margin_metrics.csv")
    fixedM = float(mm[(mm.node == "A (11/14 first half)") & (mm.method == "Self-only + fixed")
                      & (mm.subset == "all")].mean_margin.iloc[0])
    dt, m = prm["dt"], prm["m"]
    ps = ev[ev.event == "phase_start"]
    t0 = float(ps.ts.iloc[0])
    n = prm["n"]
    tk = t0 + np.arange(n) * dt
    Tamb = np.interp(tk + dt / 2, amb.ts.to_numpy(), amb.temperature.to_numpy())
    D = resample(tel, nodeA["host"], dt, t0, n).ffill().bfill()
    th = D["T"].to_numpy() - Tamb
    u, f = D.u.to_numpy(), D.f.to_numpy()
    sp = nodeA["self"]
    p = ThermalParams(a=sp["a"], b=sp["b"], d=sp["d"], e=sp["e"], c=0.0, dt=dt)  # A は c = 0(H なしと同じ)
    nz = nodeA["noise_self"]
    kf = run_kf(p, NoiseParams(R=nz["R"], qT=nz["qT"], qH0=0.0, beta=0.0), th, u, np.zeros(n), m, f=f)
    M = 2.0 * kf["sigma"] + 0.5
    a0 = prm["n_identify"] + int(20 * 60 / dt)
    a1 = min(n, a0 + int(40 * 60 / dt))
    sl = slice(a0, a1)
    tmin = (tk - t0) / 60
    tt, tf = tmin[sl], tmin[sl] + m * dt / 60
    fig, ax = plt.subplots(2, 1, figsize=(6.6, 4.6), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    ax[0].plot(tt, th[sl] + Tamb[sl], color="k", lw=1.2, label="実測")
    pr = kf["pred"][sl] + Tamb[sl]
    ax[0].plot(tf, pr, color=COL["proposed"], lw=1, label="30 秒先の予測(予測先の時刻に描画)")
    ax[0].fill_between(tf, pr, pr + M[sl], color=COL["proposed"], alpha=0.18, lw=0,
                       label=f"予測 + マージン(2σ + 0.5 = {np.nanmean(M[sl]):.1f}℃)")
    ax[0].plot(tf, pr + fixedM, color=COL["selffixed"], lw=0.9, ls="--", label=f"予測 + 固定マージン({fixedM:.1f}℃)")
    ax[0].set_ylabel("CPU 温度 [℃]")
    ax[0].legend(frameon=False, fontsize=7.5, loc="upper right")
    ax[1].plot(tt, u[sl] * 100, color="0.3", lw=1)
    ax[1].set_ylabel("CPU 使用率 [%]")
    ax[1].set_ylim(-5, 105)
    a2 = ax[1].twinx()
    a2.fill_between(tt, 0, f[sl], step="post", color="#9cc3ea", alpha=0.6, lw=0)
    a2.set_ylim(0, 3)
    a2.set_yticks([0, 1])
    a2.set_yticklabels(["OFF", "ON"])
    a2.set_ylabel("ファン", color="#5b8fc9")
    ax[1].set_xlabel("実験開始からの時間 [分]")
    fig.tight_layout()
    fig.savefig(OUT / "fig_predict.png")
    plt.close(fig)


def fig_rack_interference():
    """ラックで A だけに負荷をかけたときの 3 台の温度。"""
    d = EXP / "20261113_rack_interference"
    ev = pd.read_csv(d / "events.csv")
    tel = pd.read_csv(d / "raw" / "telemetry.csv", usecols=["ts", "host", "temp"])
    t0 = tel.ts.min()
    st = ev[ev.event == "phase_start"].set_index("phase").ts
    en = ev[ev.event == "phase_end"].set_index("phase").ts
    load_ph = [p for p in st.index if "load" in p][0]
    fig, ax = plt.subplots(figsize=(6.6, 2.8))
    lab = {"raspi1": ("A(負荷)", "#c0392b"), "raspi2": ("B(すぐ隣)", "#1f5fbf"), "raspi3": ("C(2 つ離れた位置)", "#27ae60")}
    for h, (l, c) in lab.items():
        w = tel[tel.host == h]
        w = w.set_index(pd.to_datetime(w.ts, unit="s")).resample("5s").mean(numeric_only=True)
        ax.plot((w.ts - t0) / 60, w.temp, color=c, lw=1.1, label=l)
    ax.axvspan((st[load_ph] - t0) / 60, (en[load_ph] - t0) / 60, color="#bbb", alpha=0.35, lw=0)
    ax.text((st[load_ph] - t0) / 60 + 0.3, 46, "A だけに 2 コアの負荷", fontsize=8.5)
    ax.set_xlabel("開始からの時間 [分]")
    ax.set_ylabel("CPU 温度 [℃](5 秒平均)")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / "fig_rack_interference.png")
    plt.close(fig)


def _box(ax, xy, w, h, text, fc="#eef3fb", ec="#1f5fbf", fs=9):
    ax.add_patch(FancyBboxPatch(xy, w, h, boxstyle="round,pad=0.02,rounding_size=0.06", fc=fc, ec=ec, lw=1.1))
    ax.text(xy[0] + w / 2, xy[1] + h / 2, text, ha="center", va="center", fontsize=fs, linespacing=1.4)


def _arrow(ax, a, b, text=None, off=(0, 0.12)):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=10, lw=1.1, color="#333"))
    if text:
        ax.text((a[0] + b[0]) / 2 + off[0], (a[1] + b[1]) / 2 + off[1], text, ha="center", fontsize=7.5, color="#333")


def fig_method_flow():
    """提案手法の流れ:計測 → KF → Δ 秒先予測 → マージン → ファン判断。"""
    fig, ax = plt.subplots(figsize=(7.0, 2.6))
    ax.set_xlim(0, 11.15)
    ax.set_ylim(0, 3.4)
    ax.axis("off")
    w, h, y = 1.95, 1.55, 1.6
    xs = [0.05, 2.3, 4.55, 6.8, 9.05]
    texts = ["計測(5 秒平均)\n温度 $T$・使用率 $u$\nファン $f$・室温\n隣の温度 $z$",
             "カルマン\nフィルタ\n$[T,\\ H]$ を推定",
             "30 秒先を予測\n(ファン OFF・\n負荷そのまま)\n$\\hat{T}$ と $\\sigma$",
             "動的マージン\n$M = \\alpha\\sigma + \\delta$\n$T_{\\mathrm{safe}} = 80 - M$",
             "ファンの判断\n$\\hat{T} > T_{\\mathrm{safe}}$\nなら ON\n(最小 ON 30 秒)"]
    for x, t in zip(xs, texts):
        _box(ax, (x, y), w, h, t, fs=8)
    for i in range(4):
        _arrow(ax, (xs[i] + w + 0.03, y + h / 2), (xs[i + 1] - 0.03, y + h / 2))
    _box(ax, (2.6, 0.1), 5.9, 0.7, "ノード(Raspberry Pi 4B + PoE+ HAT のファン)", fc="#f6f6f6", ec="#777", fs=8.5)
    ax.add_patch(FancyArrowPatch((xs[4] + w / 2, y - 0.03), (8.55, 0.45), arrowstyle="-|>", mutation_scale=10,
                                 lw=1.1, color="#333", connectionstyle="angle,angleA=-90,angleB=0,rad=0"))
    ax.text(xs[4] + w / 2 + 0.08, 1.0, "ON/OFF の指令", fontsize=7.5)
    ax.add_patch(FancyArrowPatch((2.55, 0.45), (xs[0] + w / 2, y - 0.03), arrowstyle="-|>", mutation_scale=10,
                                 lw=1.1, color="#333", connectionstyle="angle,angleA=180,angleB=-90,rad=0"))
    ax.text(xs[0] + w / 2 + 0.08, 1.0, "計測値(1 秒ごと)", fontsize=7.5)
    fig.savefig(OUT / "fig_method_flow.png")
    plt.close(fig)


def fig_system():
    """システム構成:ノード 3 台、制御用 PC、PoE スイッチ、室温計。間隔は未計測なので書かない。"""
    fig, ax = plt.subplots(figsize=(7.0, 3.0))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 4.6)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.05, 2.3), 6.3, 2.15, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc="none", ec="#999", ls="--", lw=1))
    ax.text(0.2, 4.15, "ラック上段(左から並べる)", fontsize=8, color="#555")
    for i, (n, r) in enumerate([("raspi1", "A(負荷側)"), ("raspi2", "B(すぐ隣)"), ("raspi3", "C(2 つ隣)")]):
        _box(ax, (0.2 + i * 2.05, 2.45), 1.9, 1.55, f"{n}\n{r}\n計測エージェント\nPoE+ HAT ファン", fs=7.5)
    _box(ax, (1.2, 0.35), 2.8, 0.95, "PoE スイッチ\n(給電とネットワーク)", fc="#f6f6f6", ec="#777", fs=8)
    _box(ax, (7.5, 2.1), 3.4, 2.2, "制御用 PC\nMQTT ブローカー\n収集・記録(CSV)\n推定・ファンの判断\n負荷の指令(実験時)",
         fc="#fdf2e6", ec="#e67e22", fs=8)
    _box(ax, (7.5, 0.3), 3.4, 1.0, "SwitchBot 温湿度計・ハブ 2\n(室温、60 秒ごと)", fc="#f6f6f6", ec="#777", fs=7.5)
    for i in range(3):
        ax.plot([1.15 + i * 2.05] * 2, [2.45, 1.8], color="#777", lw=1)
    ax.plot([1.15, 5.25], [1.8, 1.8], color="#777", lw=1)
    ax.plot([2.6, 2.6], [1.8, 1.3], color="#777", lw=1)
    _arrow(ax, (6.45, 3.65), (7.45, 3.65))
    ax.text(6.95, 3.8, "計測値\n1 秒ごと", ha="center", fontsize=7, linespacing=1.1)
    _arrow(ax, (7.45, 2.75), (6.45, 2.75))
    ax.text(6.95, 2.25, "ファン\nON/OFF", ha="center", fontsize=7, linespacing=1.1)
    _arrow(ax, (9.2, 1.33), (9.2, 2.05))
    fig.savefig(OUT / "fig_system.png")
    plt.close(fig)


if __name__ == "__main__":
    for f in [fig_control_round, fig_control_bars, fig_tradeoff, fig_rack_interference, fig_method_flow, fig_system, fig_slow_cooling, fig_predict]:
        f()
        print("ok", f.__name__)
    fig_slow_cooling(column=True)
    print("ok", "fig_slow_cooling(column)")
    fig_slow_cooling_resume()  # レジュメ(2 ページ版)用
    print("ok", "fig_slow_cooling_resume")
