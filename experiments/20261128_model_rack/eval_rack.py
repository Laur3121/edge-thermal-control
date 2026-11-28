#!/usr/bin/env python3
"""ラック同時のモデル(P2・P2n)と今のモデル(P0・P1)の予測のずれを比べる(README の方法)。
使い方:python experiments/20261128_model_rack/eval_rack.py
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "scripts"))
from fit_control_params_box import load, GRID, NBR  # noqa: E402
from etc.kalman import NoiseParams, run_kf  # noqa: E402
from etc.model import ThermalParams  # noqa: E402

H = list(GRID); M90, M30 = 18, 6
PAR = json.loads((ROOT / "scripts/control_params_open.json").read_text())["nodes"]
FIT = [ROOT / "experiments/20261125_pattern_open", ROOT / "experiments/20261126_open_ident"]
EVAL = [ROOT / "experiments/20261127_delay_sweep/d60", ROOT / "experiments/20261127_delay_sweep/d30",
        ROOT / "experiments/20261127_tradeoff/d60"]


def arrays(exp):
    D, Ta = load(exp)
    th = np.array([D[h]["T"].to_numpy() - Ta for h in H])          # (8, n)
    u = np.array([D[h].u.to_numpy() / 100 for h in H])
    f = np.array([D[h].f.to_numpy() for h in H])
    ok = np.array([D[h].clk.to_numpy() >= 1790e6 for h in H])
    return th, u, f, ok


def other_mean(th, i, mode):
    idx = [H.index(s) for s in NBR[H[i]]] if mode == "nbr" else [j for j in range(len(H)) if j != i]
    return th[idx].mean(axis=0)


def fit_rack(mode):
    X, Y = {i: [] for i in range(8)}, {i: [] for i in range(8)}
    for exp in FIT:
        th, u, f, ok = arrays(exp)
        for i in range(8):
            z = other_mean(th, i, mode)
            mk = ok[i, :-1] & ok[i, 1:]
            X[i].append(np.c_[th[i, :-1], u[i, :-1], f[i, :-1], z[:-1], np.ones(th.shape[1] - 1)][mk])
            Y[i].append(th[i, 1:][mk])
    coef = {}
    for i in range(8):
        c, *_ = np.linalg.lstsq(np.vstack(X[i]), np.concatenate(Y[i]), rcond=None)
        coef[i] = c
    return coef


def rack_predict(coef, th0, u0, f0, mode, m):
    """8 台を同時に m ステップ進める。戻り値 (8, m)"""
    x = th0.copy(); out = []
    for _ in range(m):
        nx = np.empty(8)
        for i in range(8):
            a, b, e, g, d = coef[i]
            idx = [H.index(s) for s in NBR[H[i]]] if mode == "nbr" else [j for j in range(8) if j != i]
            nx[i] = a * x[i] + b * u0[i] + e * f0[i] + g * x[idx].mean() + d
        x = nx; out.append(x.copy())
    return np.array(out).T


def main():
    coefs = {mode: fit_rack(mode) for mode in ("all", "nbr")}
    for mode, c in coefs.items():
        print(mode, {H[i]: np.round(v, 3).tolist() for i, v in c.items()})
    rows = []
    for exp in EVAL:
        th, u, f, ok = arrays(exp)
        n = th.shape[1]
        # P1:KF(withH)の 90 秒先・30 秒先
        p1 = {}
        for i, h in enumerate(H):
            w = PAR[h]["withH"]
            p = ThermalParams(**{k: w[k] for k in ("a", "b", "d", "c", "rho", "z_base", "e", "dt")})
            nz = NoiseParams(R=PAR[h]["R"], qT=PAR[h]["qT_H"], qH0=PAR[h].get("qH0", 0.008), beta=PAR[h].get("beta", 2.0))
            nbr = other_mean(th, i, "nbr")
            p1[(i, 90)] = run_kf(p, nz, th[i], u[i], nbr, M90, f=f[i])["pred"]
            p1[(i, 30)] = run_kf(p, nz, th[i], u[i], nbr, M30, f=f[i])["pred"]
        for k in range(n - M90):
            rp = {mode: rack_predict(coefs[mode], th[:, k], u[:, k], f[:, k], mode, M90) for mode in coefs}
            for i, h in enumerate(H):
                if h == "raspi5":
                    continue
                win = slice(k + 1, k + M90 + 1)
                if not (ok[i, k:k + M90 + 1].all() and f[i, k:k + M90 + 1].max() < 0.01
                        and u[i, win].max() - u[i, k] < 0.2):
                    continue
                s = PAR[h]["self"]; x = th[i, k]; p0 = []
                for _ in range(M90):
                    x = s["a"] * x + s["b"] * u[i, k] + s["d"]; p0.append(x)
                act = th[i, win]
                pr = {"P0": np.array(p0), "P2": rp["all"][i], "P2n": rp["nbr"][i]}
                r = dict(exp=exp.name, host=h, k=k)
                for name, path in pr.items():
                    r[f"{name}_bias"] = act.max() - max(th[i, k], path.max())
                    r[f"{name}_e90"] = act[-1] - path[-1]
                    r[f"{name}_e30"] = act[M30 - 1] - path[M30 - 1]
                r["P1_bias"] = act.max() - max(th[i, k], p1[(i, 90)][k])
                r["P1_e90"] = act[-1] - p1[(i, 90)][k]
                r["P1_e30"] = act[M30 - 1] - p1[(i, 30)][k]
                rows.append(r)
    df = pd.DataFrame(rows)
    out = Path(__file__).parent / "results"; out.mkdir(exist_ok=True)
    df.to_csv(out / "errors.csv", index=False)
    print(f"評価する時刻:{len(df)}(台・時刻)")
    tab = pd.DataFrame({m: {"ずれの中央値(最高)": df[f"{m}_bias"].median(), "90 秒先 MAE": df[f"{m}_e90"].abs().mean(),
                            "90 秒先 平均誤差": df[f"{m}_e90"].mean(), "30 秒先 MAE": df[f"{m}_e30"].abs().mean()}
                        for m in ("P0", "P1", "P2", "P2n")}).T.round(2)
    print(tab.to_string())
    print(df.groupby("host")[[f"{m}_e90" for m in ("P0", "P1", "P2", "P2n")]].mean().round(2).to_string())
    tab.to_csv(out / "summary.csv")
    for m in ("P2", "P2n"):
        b, r = abs(tab.loc[m, "ずれの中央値(最高)"]), tab.loc[m, "90 秒先 MAE"] / tab.loc["P1", "90 秒先 MAE"]
        v = "直る" if b <= 0.5 and r <= 0.8 else "一部直る" if (b <= 0.5 or r <= 0.8) else "直らない"
        print(f"{m}:|ずれ| {b:.2f}、MAE 比 {r:.2f} → {v}")


if __name__ == "__main__":
    main()
