#!/usr/bin/env python3
"""制御のパラメータを、同定に使っていないデータで確かめる(2026-11-26、囲いなし用)。

check_params.py は囲いありの常時 ON の実測と比べるので、囲いなしのパラメータには使えない。代わりに、指定した実験の
後半 40%(同定は前半 60% と別の実験で行う前提)で 30 秒先の予測(入力は今の値が続くと仮定、H は周りのノードの温度から)の
平均絶対誤差を出し、次のどれかに当たれば終了コード 1 で止める。
  - 係数の符号:0 < a < 1、b > 0、e < 0、c >= 0 でない
  - ファン ON の時刻の誤差がノードのどれかで 4.0℃ を超える
  - 全時刻の誤差がノードのどれかで 3.0℃ を超える
  基準の決め方(11/26):11/25 の誤ったパラメータを 11/25 夜のデータで見るとファン ON 4.9〜10.4℃(6 台)、
  直したパラメータを d90 のデータで見ると 1.7〜3.3℃。この間で、誤りをはっきり止められる値にした

使い方:python scripts/check_params_holdout.py scripts/control_params_open.json experiments/20261126_open_ident
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DT, M = 5.0, 6
GRID = {f"raspi{i}": ((i - 1) // 4, (i - 1) % 4) for i in range(1, 9)}


def lowpass(z, rho):
    H = np.zeros_like(z)
    for k in range(len(z) - 1):
        H[k + 1] = rho * H[k] + (1 - rho) * z[k]
    return H


def main(params: Path, exp: Path):
    P = json.loads(params.read_text())
    tel = pd.read_csv(exp / "raw" / "telemetry.csv")
    ev = pd.read_csv(exp / "events.csv")
    amb = pd.read_csv(exp / "raw" / "ambient.csv")
    amb = amb[amb.name.astype(str).str.contains("ハブ２")].sort_values("ts")
    t0 = float(ev[ev.event == "phase_start"].ts.iloc[0])
    t1 = float(ev[ev.event == "phase_end"].ts.max())
    n = int((t1 - t0) // DT)
    tk = t0 + np.arange(n) * DT + DT / 2
    Ta = np.interp(tk, amb.ts.to_numpy(), amb.temperature.to_numpy())
    D = {}
    for h in GRID:
        g = tel[tel.host == h]
        k = ((g.ts - t0) // DT).astype(int)
        D[h] = g.groupby(k).agg(T=("temp", "mean"), u=("cpu", "mean"), f=("fan", "mean")).reindex(range(n)).ffill().bfill()
    ev_idx = np.arange(int(n * 0.6), n - M)
    ok = True
    print(f"{params} を {exp} の後半 40% で確認(30 秒先)")
    for h, node in P["nodes"].items():
        w = node["withH"]
        th = D[h]["T"].to_numpy() - Ta
        u, f = D[h].u.to_numpy() / 100, D[h].f.to_numpy()
        nb = np.mean([D[s]["T"].to_numpy() - Ta for s in node["neighbors"]], axis=0)
        z = nb - w["z_base"]
        H = lowpass(z, w["rho"])
        pred = np.full(n, np.nan)
        for k in ev_idx:
            x, Hk = th[k], H[k]
            for _ in range(M):
                x_new = w["a"] * x + w["b"] * u[k] + w["c"] * Hk + w["e"] * f[k] + w["d"]
                Hk = w["rho"] * Hk + (1 - w["rho"]) * z[k]
                x = x_new
            pred[k + M] = x
        idx = ev_idx + M
        err = np.abs(pred[idx] - th[idx])
        on = f[ev_idx] > 0.5
        mae, mae_on = float(np.nanmean(err)), float(np.nanmean(err[on])) if on.any() else float("nan")
        bad = []
        if not (0 < w["a"] < 1 and w["b"] > 0 and w["e"] < 0 and w["c"] >= 0):
            bad.append("係数の符号")
        if mae_on > 4.0:
            bad.append(f"ファン ON の誤差 {mae_on:.2f}℃")
        if mae > 3.0:
            bad.append(f"全体の誤差 {mae:.2f}℃")
        print(f"  {h}: 誤差 全体 {mae:.2f} ファン ON {mae_on:.2f}℃  {'NG: ' + '、'.join(bad) if bad else 'OK'}")
        ok &= not bad
    print("結果:", "OK" if ok else "NG(実験を始めない)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
