#!/usr/bin/env python3
"""pattern 実験で 30 秒先の温度予測を 3 つのモデルで比べる(pattern_box の README「予測の比較」で実行前に決めた)。

① 自ノードだけ(KF、H なし。室温 = ハブ 2)
② KF + H(室温 = ハブ 2。H は縦・横・斜めで接するノードの温度の平均から)
③ 自ノードだけ(KF、H なし。室温 = 防水温湿度計 1:開いた状態ではラックの上、箱では箱の中)

同定:off_r6・off_r7・off_bottom(負荷と休み)。評価:off_all、cool_alone_load、cool_nbrs_load と休み、fanA_r6_rest。
ファン(強制 ON を含む)が回っている遷移は同定から外し、[k, k+Δ] にファン ON を含む時刻は評価から外す
(ファンの係数をこのデータで同定できないため。README の「ファン ON の区間は外す」を強制 ON にも当てはめた)。

--swap(11/25 昼に追加、開いた状態の結果を見た後):同定と評価を入れ替える。実行前に決めた分け方では、
上段 r1〜r4 は同定区間で一度も負荷がかからず、負荷の係数 b が決まらない(設計の誤り)。入れ替えると、
同定(後半)では全台に負荷がかかり、評価(前半)は「自分は休み・隣だけ負荷」= 干渉だけの区間になる。

使い方: python scripts/eval_pattern_pred.py experiments/20261125_pattern_open [--swap]
出力: <exp>/results/pred[_swap]/metrics.csv、params.json、summary.txt
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from etc.kalman import NoiseParams, run_kf  # noqa: E402
from etc.metrics import prediction_metrics  # noqa: E402
from etc.model import fit_self_only, fit_with_H  # noqa: E402

DT, DELTA = 5.0, 30.0
M = int(DELTA / DT)
GRID = {"r1": (0, 0), "r2": (0, 1), "r3": (0, 2), "r4": (0, 3),
        "r5": (1, 0), "r6": (1, 1), "r7": (1, 2), "r8": (1, 3)}
NBR = {r: [s for s, q in GRID.items() if s != r and max(abs(p[0] - q[0]), abs(p[1] - q[1])) == 1]
       for r, p in GRID.items()}
ID_BLOCKS = ["off_r6_load", "off_r6_rest", "off_r7_load", "off_r7_rest", "off_bottom_load", "off_bottom_rest"]
EV_BLOCKS = ["off_all_load", "off_all_rest", "fanA_r6_rest", "cool_alone_load", "cool_alone_rest",
             "cool_nbrs_load", "cool_nbrs_rest"]
IDENT = Path("experiments/20261113_step_identify/results/identify.json")


def main(exp: Path, swap: bool = False):
    global ID_BLOCKS, EV_BLOCKS
    if swap:
        ID_BLOCKS, EV_BLOCKS = EV_BLOCKS, ID_BLOCKS
    out = exp / "results" / ("pred_swap" if swap else "pred")
    out.mkdir(parents=True, exist_ok=True)
    tel = pd.read_csv(exp / "raw" / "telemetry.csv")
    ev = pd.read_csv(exp / "events.csv")
    amb = pd.read_csv(exp / "raw" / "ambient.csv")
    amb["name"] = amb.name.astype(str).str.strip()
    ps = ev[ev.event == "phase_start"].reset_index(drop=True)
    pe = ev[ev.event == "phase_end"].set_index("phase").ts
    t0 = float(ps.ts.iloc[0])
    t_end = float(pe.max())
    n = int((t_end - t0) // DT)
    tk = t0 + np.arange(n) * DT + DT / 2

    def block_mask(names):
        mk = np.zeros(n, bool)
        for p in names:
            s = float(ps[ps.phase == p].ts.iloc[0])
            e = float(pe[p])
            mk[int((s - t0) // DT):int((e - t0) // DT)] = True
        return mk

    def ambient(name):
        a = amb[amb.name.str.contains(name)].sort_values("ts")
        return np.interp(tk, a.ts.to_numpy(), a.temperature.to_numpy())

    T_room, T_in = ambient("ハブ２"), ambient("防水温湿度計 1")
    T_23 = (ambient("防水温湿度計 2") + ambient("防水温湿度計 3")) / 2  # ③'(11/25 11:05 追加、吸気側)
    R = json.loads(IDENT.read_text())["noise"]["R_1s"] / DT
    D = {}
    for r in GRID:
        g = tel[tel.host == f"raspi{r[1:]}"]
        k = ((g.ts - t0) // DT).astype(int)
        a = g.groupby(k).agg(T=("temp", "mean"), u=("cpu", "mean"), f=("fan", "max")).reindex(range(n))
        D[r] = a.ffill().bfill()
    id_mask, ev_mask = block_mask(ID_BLOCKS), block_mask(EV_BLOCKS)
    rows, params = [], {}
    for r in GRID:
        T, u, f = D[r]["T"].to_numpy(), D[r].u.to_numpy() / 100.0, D[r].f.to_numpy()
        fan_free = np.array([f[k:k + M + 1].max() == 0 for k in range(n)])
        trans = (id_mask[:-1] & id_mask[1:] & (f[:-1] == 0) & (f[1:] == 0))
        idx_ev = np.where(ev_mask & fan_free)[0]
        preds = {}
        for label, Tamb, useH in [("①自ノードだけ(部屋の室温)", T_room, False),
                                  ("②KF+H(部屋の室温)", T_room, True),
                                  ("③自ノードだけ(温度計1)", T_in, False),
                                  ("③'自ノードだけ(温度計2・3)", T_23, False)]:
            th = T - Tamb
            nbr = np.mean([D[s]["T"].to_numpy() - Tamb for s in NBR[r]], axis=0)
            if useH:
                z_base = float(nbr[id_mask].mean())
                p, res = fit_with_H(th, u, nbr, DT, z_base=z_base, mask=trans,
                                    rho_grid=np.linspace(0.5, 0.995, 100))
                if p.c < 0:  # c < 0 は物理的にありえない(11/14 合意)→ H なし
                    p0, res = fit_self_only(th, u, DT, mask=trans)
                    p.a, p.b, p.d, p.c = p0.a, p0.b, p0.d, 0.0
                beta = 2.0
            else:
                p, res = fit_self_only(th, u, DT, mask=trans)
                beta = 0.0
            nz = NoiseParams(R=R, qT=max(float(np.var(res)) - (1 + p.a ** 2) * R, 1e-4), qH0=0.008, beta=beta)
            kf = run_kf(p, nz, th, u, nbr, M)
            pm = prediction_metrics(th, kf["pred"], M, idx_ev)
            # 負荷中だけ(評価区間のうち load ブロック)
            load_idx = idx_ev[block_mask([b for b in EV_BLOCKS if b.endswith("_load")])[idx_ev]]
            nbr_heat = np.zeros(n, bool)  # 自分は休み・隣のどれかに負荷(干渉だけの時刻)
            for s_ in NBR[r]:
                nbr_heat |= D[s_].u.to_numpy() > 30
            pi = prediction_metrics(th, kf["pred"], M, idx_ev[(u[idx_ev] < 0.1) & nbr_heat[idx_ev]])
            pl = prediction_metrics(th, kf["pred"], M, load_idx)
            rows.append({"role": r, "model": label, "MAE": round(pm["MAE"], 3), "RMSE": round(pm["RMSE"], 3),
                         "bias": round(pm["bias"], 3), "n": pm["n"], "MAE_load": round(pl["MAE"], 3),
                         "MAE_nbr_only": round(pi["MAE"], 3), "n_nbr_only": pi["n"],
                         "c": round(p.c, 4), "rho": round(p.rho, 3) if useH else None})
            params[f"{r} {label}"] = {**p.to_dict(), "qT": nz.qT, "neighbors": NBR[r]}
            preds[label] = kf["pred"] + Tamb
        np.savez(out / f"pred_{r}.npz", tk=tk, T=T, **{f"m{i}": v for i, v in enumerate(preds.values())})
    df = pd.DataFrame(rows)
    df.to_csv(out / "metrics.csv", index=False)
    (out / "params.json").write_text(json.dumps(params, ensure_ascii=False, indent=1, default=float))
    piv = df.pivot(index="role", columns="model", values="MAE")
    pl = df.pivot(index="role", columns="model", values="MAE_load")
    pn = df.pivot(index="role", columns="model", values="MAE_nbr_only")
    c = df[df.model.str.startswith("②")].set_index("role")[["c", "rho"]]
    up = piv.loc[["r1", "r2", "r3"]].mean()
    txt = "\n".join([f"# {exp.name}{' (swap)' if swap else ''} 30 秒先の MAE [℃](評価区間、ファン OFF)", piv.round(2).to_string(), "",
                     "上段 r1〜r3 の平均", up.round(2).to_string(), "", "8 台の平均", piv.mean().round(2).to_string(), "",
                     "負荷中だけの MAE", pl.round(2).to_string(), "",
                     "自分は休み・隣が負荷の時刻だけの MAE", pn.round(2).to_string(), "", "② の c・ρ", c.to_string(), "",
                     f"室温(ハブ2)の範囲 {T_room.min():.1f}〜{T_room.max():.1f}℃、温度計1 {T_in.min():.1f}〜{T_in.max():.1f}℃"])
    (out / "summary.txt").write_text(txt)
    print(txt)


if __name__ == "__main__":
    main(Path(sys.argv[1]), swap="--swap" in sys.argv)
