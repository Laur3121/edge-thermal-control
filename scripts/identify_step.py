#!/usr/bin/env python3
"""同定用ステップ実験(scripts/scenarios/step_identify.json)から自ノードの熱モデルを同定し、別区間で検証する。

- データ:node A の 1 秒ログを dt 秒の平均に(量子化雑音を減らすため。既定 5 秒)
- 同定:part2(A のファン ON、負荷 2→0→1→0)と part3(ファン OFF、負荷パルス)
- 検証:part1(負荷一定でファン ON/OFF を切り替え)= 同定に使っていない区間
- ファンの扱いを 2 案で比較(docs/parameters.md「ファンの効果」)
    案A(切替):ファン OFF/ON で (a, b, d) を別々に同定
    案B(加算):T_{t+1} = a T + b u + e f + d を 1 組で同定
- 検証指標:Δ 秒先予測(入力は現在の値が続くと仮定。ファン状態は制御側が決めるので既知とする)の RMSE
- 隣接ノード B・C への干渉:A の温度を隣接入力にして fit_with_H で c, ρ を推定(参考)

出力:<run>/results/identify.json、identify_validation.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from etc.model import ThermalParams, fit_self_only, fit_with_H  # noqa: E402


def resample(tel: pd.DataFrame, host: str, dt: float, t0: float) -> pd.DataFrame:
    g = tel[tel.host == host].copy()
    g["k"] = ((g.ts - t0) // dt).astype(int)
    agg = g.groupby("k").agg(T=("temp", "mean"), u=("cpu", "mean"), f=("fan", "mean"), n=("temp", "size"))
    agg["u"] = agg.u / 100.0
    agg["t"] = agg.index * dt
    return agg


def phase_of(ev: pd.DataFrame, t0: float, t: np.ndarray) -> np.ndarray:
    st = ev[ev.event == "phase_start"][["phase", "ts"]].to_numpy()
    out = np.array([""] * len(t), dtype=object)
    for i, (name, ts) in enumerate(st):
        end = st[i + 1][1] if i + 1 < len(st) else np.inf
        out[(t >= ts - t0) & (t < end - t0)] = name
    return out


def lstsq(X, y):
    th, *_ = np.linalg.lstsq(X, y, rcond=None)
    return th, y - X @ th


def predict_m(T, u, f, m, step, fan_known=False):
    """各 k から m ステップ先を予測。u は時刻 k の値が続くと仮定。
    ファンは制御側が決める入力なので、fan_known=True なら実際の将来の値を使う(False なら時刻 k の値が続く)。"""
    N = len(T)
    out = np.full(N, np.nan)
    for k in range(N - m):
        x = T[k]
        for j in range(m):
            x = step(x, u[k], f[k + j] if fan_known else f[k])
        out[k] = x
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--dt", type=float, default=5.0)
    ap.add_argument("--delta", type=float, default=30.0)
    ap.add_argument("--ambient", default="ハブ", help="室温に使う温湿度計の名前(部分一致)。'none' で室温を使わない")
    args = ap.parse_args()
    d = Path(args.run_dir)
    tel = pd.read_csv(d / "raw" / "telemetry.csv")
    ev = pd.read_csv(d / "events.csv")
    nodes = json.loads((d / "config.json").read_text())["nodes"]
    t0 = float(ev.ts.min())
    dt, m = args.dt, int(round(args.delta / args.dt))

    A = resample(tel, nodes["A"], dt, t0)
    A["phase"] = phase_of(ev, t0, A.t.to_numpy())
    A["part"] = A.phase.str.slice(0, 2)
    # 室温:モデルは室温からの上昇分 θ = T - T_amb で立てる(RC モデル:θ_{t+1} = a θ + b u + d、d = (1-a) R P0)
    Tamb = np.zeros(len(A))
    amb_path = d / "raw" / "ambient.csv"
    if args.ambient != "none" and amb_path.exists():
        amb = pd.read_csv(amb_path)
        amb = amb[amb.name.str.contains(args.ambient)].sort_values("ts")
        Tamb = np.interp(A.t.to_numpy() + t0 + dt / 2, amb.ts.to_numpy(), amb.temperature.to_numpy())
    A["Tamb"] = Tamb
    # 遷移 k→k+1 を使う条件:同じ part、ファン状態が区間内で一定(0 か 1)、サンプルが揃っている
    Tabs, u, f = A["T"].to_numpy(), A.u.to_numpy(), A.f.to_numpy()
    T = Tabs - Tamb  # 以下 T は室温からの上昇分
    fk = np.round(f)
    ok = (np.abs(f - fk) < 1e-9) & (A.n.to_numpy() >= dt * 0.8)
    ok_tr = ok[:-1] & ok[1:] & (fk[:-1] == fk[1:]) & (A.part.to_numpy()[:-1] == A.part.to_numpy()[1:])
    part = A.part.to_numpy()[:-1]
    idm = ok_tr & np.isin(part, ["p2", "p3"])
    valm = ok_tr & (part == "p1")

    X = np.column_stack([T[:-1], u[:-1], np.ones(len(T) - 1)])
    y = T[1:]
    res = {"dt": dt, "delta": args.delta, "m": m, "n_identify": int(idm.sum()), "n_validate": int(valm.sum()),
           "ambient": args.ambient, "ambient_range": [float(Tamb.min()), float(Tamb.max())],
           "note": "温度は室温からの上昇分。T_inf は上昇分の定常値"}

    # 案A:ファン OFF / ON で別々
    pA = {}
    for st in (0, 1):
        sel = idm & (fk[:-1] == st)
        (a, b, dd), r = lstsq(X[sel], y[sel])
        p = ThermalParams(a=a, b=b, d=dd, dt=dt)
        pA[st] = p
        res[f"caseA_fan{st}"] = {**p.to_dict(), "issues": p.check(), "n": int(sel.sum()),
                                 "resid_var": float(r.var()),
                                 "T_inf_u0": dd / (1 - a), "T_inf_u05": (0.5 * b + dd) / (1 - a),
                                 "gain_per_100pct": b / (1 - a)}
    # 案B:加算項
    XB = np.column_stack([T[:-1], u[:-1], fk[:-1], np.ones(len(T) - 1)])
    (aB, bB, eB, dB), rB = lstsq(XB[idm], y[idm])
    res["caseB"] = {"a": aB, "b": bB, "e": eB, "d": dB, "tau": -dt / np.log(aB) if 0 < aB < 1 else None,
                    "resid_var": float(rB.var())}

    # 検証(part1):1 ステップと Δ 秒先
    def stepA(x, uu, ff):
        p = pA[int(round(ff))]
        return p.a * x + p.b * uu + p.d

    def stepB(x, uu, ff):
        return aB * x + bB * uu + eB * round(ff) + dB

    vk = np.where(np.r_[valm, False])[0]
    for name, stepf in (("caseA", stepA), ("caseB", stepB)):
        one = np.array([stepf(T[k], u[k], fk[k]) for k in vk])
        e1 = T[vk + 1] - one
        kk = vk[(vk + m < len(T))]
        kk = kk[np.isin(A.part.to_numpy()[kk + m], ["p1"])]
        r = {"rmse_1step": float(np.sqrt((e1 ** 2).mean()))}
        for known in (False, True):
            pm = predict_m(T, u, fk, m, stepf, fan_known=known)
            em = T[kk + m] - pm[kk]
            tag = "fan_known" if known else "fan_held"
            r[tag] = {"rmse": float(np.sqrt((em ** 2).mean())), "mae": float(np.abs(em).mean()),
                      "bias": float(em.mean()), "max_abs": float(np.abs(em).max()), "n": int(len(kk))}
            if known:
                A[f"pred_{name}"] = pd.Series(pm + Tamb, index=A.index).shift(m)
        res[f"val_{name}"] = r

    # 観測ノイズ:ファン ON・アイドルで落ち着いた区間(p2_rest の後半)の 1 秒値と dt 平均値のばらつき
    g1 = tel[tel.host == nodes["A"]]
    rest = ev[(ev.event == "phase_start") & (ev.phase == "p2_rest")].ts.iloc[0]
    rest_end = ev[(ev.event == "phase_end") & (ev.phase == "p2_rest")].ts.iloc[0]
    seg = g1[(g1.ts > rest + 300) & (g1.ts < rest_end)]
    trend = np.polyval(np.polyfit(seg.ts, seg.temp, 1), seg.ts)
    res["noise"] = {"R_1s": float(np.var(seg.temp - trend)),
                    "quantization_step": float(np.median(np.diff(np.unique(np.round(g1.temp, 3))))),
                    "note": "R_1s は 1 秒値のトレンド除去後の分散。dt 平均ではおよそ R_1s/dt 程度まで下がる"}

    # 干渉(参考):A の温度を隣接入力として B, C を fit_with_H
    for role in ("B", "C"):
        if role not in nodes:
            continue
        Bdf = resample(tel, nodes[role], dt, t0).reindex(A.index)
        good = Bdf["T"].notna().to_numpy() & A["T"].notna().to_numpy()
        TB, uB, nb = Bdf["T"].to_numpy()[good], Bdf.u.to_numpy()[good], A["T"].to_numpy()[good]
        zb = float(np.nanmean(A["T"].to_numpy()[:int(300 / dt)]))
        pH, rH = fit_with_H(TB, uB, nb, dt, z_base=zb)
        p0, r0 = fit_self_only(TB, uB, dt)
        res[f"interference_{role}"] = {**pH.to_dict(), "issues": pH.check(),
                                       "resid_var_withH": float(np.var(rH)), "resid_var_self": float(np.var(r0)),
                                       "T_range": [float(TB.min()), float(TB.max())],
                                       "steady_rise_per_degC_of_A": pH.c / (1 - pH.a) if pH.a < 1 else None}

    out = d / "results"
    out.mkdir(exist_ok=True)
    (out / "identify.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=float))

    # 図:検証区間(part1)
    v = A[A.part == "p1"]
    fig, ax = plt.subplots(2, 1, figsize=(8, 5.5), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    tm = v.t / 60
    ax[0].plot(tm, v["T"], "k-", lw=1.2, label="Measured")
    ax[0].plot(tm, v.pred_caseA, "-", lw=1, label=f"Case A (switching), {args.delta:.0f} s ahead")
    ax[0].plot(tm, v.pred_caseB, "--", lw=1, label=f"Case B (additive), {args.delta:.0f} s ahead")
    ax[0].set_title("Validation (part 1, not used for identification); fan schedule known to predictor", fontsize=8)
    ax[0].set_ylabel("CPU temperature [°C]")
    ax[0].legend(fontsize=8)
    ax[1].step(tm, v.f, where="post", color="C2", label="Fan")
    ax[1].plot(tm, v.u, color="0.4", lw=0.8, label="CPU usage (0-1)")
    ax[1].set_ylabel("Fan / load")
    ax[1].set_xlabel("Time from start [min]")
    ax[1].legend(fontsize=8, loc="center right")
    fig.tight_layout()
    fig.savefig(out / "identify_validation.png", dpi=150)
    print(json.dumps(res, indent=1, ensure_ascii=False, default=lambda x: round(float(x), 4)))


if __name__ == "__main__":
    main()
