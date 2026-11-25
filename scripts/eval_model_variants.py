#!/usr/bin/env python3
"""式の見直し(2026-11-26):囲いの中でファンを回したデータで、モデルの形を比べる。

データ:20261125_box_control 第 2 部(4 方式でファンが ON/OFF する)。同定 = 1 巡目(c1_*)、評価 = 2 巡目(c2_*)。
       分け方は結果を見る前に決めた(このスクリプトを書いた時点)
比べるモデル(θ = 温度 − 室温、dt = 5 秒、H は周りのノードの温度の一次遅れ):
  A  今のパラメータ(control_params_box.json、11/25 午後のデータ。6 台は e が借り物)
  B  同じ形で同定し直す:θ' = aθ + bu + cH + e f + d
  C  B + 隣のファンの項:θ' = aθ + bu + cH + e f + g f_nbr + d(f_nbr = 周りのノードのファンの平均)
評価:30 秒先の予測(入力は今の値が続くと仮定。KF は使わず、H は実測の隣の温度から計算)の平均絶対誤差。
      全時刻と、ファン ON の時刻、ファン OFF の時刻に分けて出す。あわせて、ファン ON・4 コアの定常温度の実測との差

使い方:python scripts/eval_model_variants.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

EXP = Path("experiments/20261125_box_control")
DT, M = 5.0, 6
GRID = {f"raspi{i}": ((i - 1) // 4, (i - 1) % 4) for i in range(1, 9)}
NBR = {h: [s for s, q in GRID.items() if s != h and max(abs(p[0] - q[0]), abs(p[1] - q[1])) == 1]
       for h, p in GRID.items()}
P = json.loads(Path("scripts/control_params_box.json").read_text())


def lowpass(z, rho):
    H = np.zeros_like(z)
    for k in range(len(z) - 1):
        H[k + 1] = rho * H[k] + (1 - rho) * z[k]
    return H


def predict(coef, cols_now, th, rho_H, m):
    """m ステップ先を、入力(u, f, f_nbr, z)は今の値が続くとして回す。coef = dict。"""
    pred = np.full(len(th), np.nan)
    for k in range(len(th) - m):
        x, H = th[k], cols_now["H"][k]
        for _ in range(m):
            x_new = coef["a"] * x + coef["b"] * cols_now["u"][k] + coef["c"] * H + coef["e"] * cols_now["f"][k] \
                + coef.get("g", 0.0) * cols_now["fn"][k] + coef["d"]
            H = rho_H * H + (1 - rho_H) * cols_now["z"][k]
            x = x_new
        pred[k + m] = x
    return pred


def main():
    tel = pd.read_csv(EXP / "raw" / "telemetry.csv")
    ev = pd.read_csv(EXP / "events.csv")
    amb = pd.read_csv(EXP / "raw" / "ambient.csv")
    amb = amb[amb.name.astype(str).str.contains("ハブ２")].sort_values("ts")
    ps = ev[ev.event == "phase_start"][["ts", "phase"]].reset_index(drop=True)
    ps["end"] = list(ps.ts[1:]) + [ev.ts.max()]
    t0 = ps[ps.phase.str.startswith("c1_")].ts.min()
    t1 = ps[ps.phase.str.startswith("c2_")].end.max()
    n = int((t1 - t0) // DT)
    tk = t0 + np.arange(n) * DT + DT / 2
    Ta = np.interp(tk, amb.ts.to_numpy(), amb.temperature.to_numpy())
    rnd = np.where(tk < ps[ps.phase.str.startswith("c2_")].ts.min(), 1, 2)
    D = {}
    for h in GRID:
        g = tel[tel.host == h]
        k = ((g.ts - t0) // DT).astype(int)
        D[h] = g.groupby(k).agg(T=("temp", "mean"), u=("cpu", "mean"), f=("fan", "mean"), fs=("failsafe", "max"),
                                clk=("clock", "min")).reindex(range(n)).ffill().bfill()
    rows = []
    for h in GRID:
        th = D[h]["T"].to_numpy() - Ta
        u, f = D[h].u.to_numpy() / 100, D[h].f.to_numpy()
        fn = np.mean([D[s].f.to_numpy() for s in NBR[h]], axis=0)
        nb = np.mean([D[s]["T"].to_numpy() - Ta for s in NBR[h]], axis=0)
        ok = (D[h].clk.to_numpy() >= 1790e6)
        tr = (rnd[:-1] == 1) & ok[:-1] & ok[1:]
        ev_idx = np.where((rnd == 2))[0]
        res = {}
        # A:今のパラメータ
        w = P["nodes"][h]["withH"]
        zA = nb - w["z_base"]
        colsA = dict(u=u, f=f, fn=fn, z=zA, H=lowpass(zA, w["rho"]))
        res["A"] = (predict(dict(a=w["a"], b=w["b"], c=w["c"], e=w["e"], d=w["d"]), colsA, th, w["rho"], M), None)
        # B・C:1 巡目で同定(ρ は格子探索)
        z_base = float(nb[rnd == 1].mean())
        z = nb - z_base
        for name, use_g in (("B", False), ("C", True)):
            best = None
            for rho in np.linspace(0.5, 0.995, 60):
                H = lowpass(z, rho)
                cols = [th[:-1], u[:-1], H[:-1], f[:-1]] + ([fn[:-1]] if use_g else []) + [np.ones(n - 1)]
                X = np.column_stack(cols)[tr]
                y = th[1:][tr]
                coef, *_ = np.linalg.lstsq(X, y, rcond=None)
                sse = float(((y - X @ coef) ** 2).sum())
                if best is None or sse < best[0]:
                    best = (sse, rho, coef, H)
            _, rho, coef, H = best
            names = ["a", "b", "c", "e"] + (["g"] if use_g else []) + ["d"]
            cd = dict(zip(names, coef))
            if cd["c"] < 0:  # c < 0 は物理的にありえない → H なしで同定し直す
                cols = [th[:-1], u[:-1], f[:-1]] + ([fn[:-1]] if use_g else []) + [np.ones(n - 1)]
                X = np.column_stack(cols)[tr]
                coef, *_ = np.linalg.lstsq(X, th[1:][tr], rcond=None)
                cd = dict(zip(["a", "b", "e"] + (["g"] if use_g else []) + ["d"], coef))
                cd["c"] = 0.0
            res[name] = (predict(cd, dict(u=u, f=f, fn=fn, z=z, H=H), th, rho, M), cd)
        for name, (pred, cd) in res.items():
            err = np.abs(pred - th)[ev_idx]
            fon = f[ev_idx] > 0.5
            row = dict(host=h, model=name, MAE=np.nanmean(err), MAE_fan_on=np.nanmean(err[fon]),
                       MAE_fan_off=np.nanmean(err[~fon]))
            if cd is not None:
                row.update({k: round(float(v), 4) for k, v in cd.items()})
            rows.append(row)
    df = pd.DataFrame(rows)
    out = EXP / "results" / "model_variants"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "metrics.csv", index=False)
    piv = df.pivot(index="host", columns="model", values=["MAE", "MAE_fan_on", "MAE_fan_off"]).round(2)
    txt = "\n".join(["# 30 秒先の平均絶対誤差 [℃](同定 = 1 巡目、評価 = 2 巡目)", piv.to_string(), "",
                     "8 台の平均", df.groupby("model")[["MAE", "MAE_fan_on", "MAE_fan_off"]].mean().round(2).to_string(),
                     "", "C の係数(g = 隣のファンの項)", df[df.model == "C"][["host", "a", "b", "c", "e", "g", "d"]].to_string(index=False),
                     "", "B の係数", df[df.model == "B"][["host", "a", "b", "c", "e", "d"]].to_string(index=False)])
    (out / "summary.txt").write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
