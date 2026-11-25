"""pattern 実験(20261125_pattern_open / _box)の指標を、README で実行前に決めた定義で計算する。

上昇 = 負荷の最後 60 秒の平均温度 − 負荷の直前 60 秒の平均温度 − 同じ時間の室温(ハブ 2)の変化
出力: <exp>/results/rise.csv, cooling.csv, summary.txt

使い方: python scripts/analyze_pattern.py experiments/20261125_pattern_open
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROLE_HOST = {f"r{i}": f"raspi{i}" for i in range(1, 9)}
WIN = 60.0
ROOM = "ハブ２"


def load(exp: Path):
    tel = pd.read_csv(exp / "raw" / "telemetry.csv")
    ev = pd.read_csv(exp / "events.csv")
    amb = pd.read_csv(exp / "raw" / "ambient.csv").rename(
        columns={"temperature": "temp", "humidity": "hum"})
    amb["name"] = amb["name"].astype(str).str.strip()
    ph = ev[ev.event == "phase_start"][["ts", "phase"]].reset_index(drop=True)
    end = ev[ev.event.isin(["phase_end", "end", "agent_stop", "stop", "interrupted"])].ts
    end = end[end > ph.ts.max()]
    ph["end"] = list(ph.ts[1:]) + [end.min() if len(end) else tel.ts.max()]
    phases = {r.phase: (r.ts, r.end) for r in ph.itertuples()}
    return tel, ev, amb, phases


def mean_temp(tel, host, t0, t1):
    s = tel[(tel.host == host) & (tel.ts >= t0) & (tel.ts < t1)].temp
    return s.mean() if len(s) else np.nan


def amb_mean(amb, name, t0, t1, pad=90.0):
    # SwitchBot は約 30〜60 秒ごと。窓が短いので前後を少し広げる
    s = amb[amb.name.str.contains(name) & (amb.ts >= t0 - pad) & (amb.ts < t1 + pad)].temp
    return s.mean() if len(s) else np.nan


def rise(tel, amb, host, phase_span):
    t0, t1 = phase_span
    before = mean_temp(tel, host, t0 - WIN, t0)
    last = mean_temp(tel, host, t1 - WIN, t1)
    d_room = amb_mean(amb, ROOM, t1 - WIN, t1) - amb_mean(amb, ROOM, t0 - WIN, t0)
    return last - before - d_room, last - before, d_room


def main(exp: Path):
    tel, ev, amb, phases = load(exp)
    out = exp / "results"
    out.mkdir(exist_ok=True)
    rows = []
    for ph in [p for p in phases if p.endswith("_load")]:
        for r, h in ROLE_HOST.items():
            rr, raw, droom = rise(tel, amb, h, phases[ph])
            t0, t1 = phases[ph]
            sub = tel[(tel.host == h) & (tel.ts >= t0) & (tel.ts < t1)]
            rows.append(dict(phase=ph.removesuffix("_load"), role=r, host=h,
                             rise=round(rr, 2), raw_rise=round(raw, 2), d_room=round(droom, 2),
                             max_temp=round(sub.temp.max(), 1),
                             min_clock_mhz=round(sub.clock.min() / 1e6),
                             fan_on_frac=round(sub.fan.mean(), 2),
                             failsafe_frac=round(sub.failsafe.mean(), 3)))
    rise_df = pd.DataFrame(rows)
    rise_df.to_csv(out / "rise.csv", index=False)

    # (b) 冷却時:r2 のファン ON の最後 60 秒
    cool = []
    for c in ["cool_alone", "cool_nbrs"]:
        if f"{c}_fan" not in phases:
            continue
        f0, f1 = phases[f"{c}_fan"]
        pre = mean_temp(tel, "raspi2", f0 - WIN, f0)
        last = mean_temp(tel, "raspi2", f1 - WIN, f1)
        room = amb_mean(amb, ROOM, f1 - WIN, f1)
        boxes = {n: amb_mean(amb, n, f1 - WIN, f1) for n in ["防水温湿度計 1", "防水温湿度計 2", "防水温湿度計 3"]}
        cool.append(dict(case=c, pre_fan=round(pre, 2), fan_last60=round(last, 2),
                         drop=round(pre - last, 2), room=round(room, 2),
                         fan_last60_minus_room=round(last - room, 2),
                         **{k: round(v, 1) for k, v in boxes.items()}))
    cool_df = pd.DataFrame(cool)
    cool_df.to_csv(out / "cooling.csv", index=False)

    fs = tel[tel.failsafe == 1]
    fs_ev = ev[ev.event.astype(str).str.contains("failsafe|force", case=False, na=False)]

    piv = rise_df.pivot(index="phase", columns="role", values="rise")
    lines = [f"# {exp.name}", "", "## 上昇 [℃](室温の変化を引いた)", piv.to_string(), "",
             "## 室温の変化 [℃]", rise_df.groupby("phase").d_room.first().to_string(), "",
             "## 最高温度 [℃]", rise_df.pivot(index="phase", columns="role", values="max_temp").to_string(), "",
             "## 最低クロック [MHz]", rise_df.pivot(index="phase", columns="role", values="min_clock_mhz").to_string(), ""]
    g = lambda ph, r: piv.loc[ph, r] if ph in piv.index else np.nan
    pairs = {"縦 r6→r2": g("off_r6", "r2"), "縦 r7→r3": g("off_r7", "r3"),
             "横 r6→r7": g("off_r6", "r7"), "横 r7→r6": g("off_r7", "r6"),
             "斜め r6→r1": g("off_r6", "r1"), "斜め r6→r3": g("off_r6", "r3"),
             "斜め r7→r2": g("off_r7", "r2"), "遠い r7→r1": g("off_r7", "r1")}
    lines += ["## 位置関係(1℃ 以上で干渉あり)"] + [f"{k}: {v:+.2f}" for k, v in pairs.items()] + [""]
    lines += ["## 熱量:off_bottom の上段"] + [f"{r}: {g('off_bottom', r):+.2f}" for r in ["r1", "r2", "r3", "r4"]] + [""]
    alone = {"r6": g("off_r6", "r6"), "r7": g("off_r7", "r7"), "r2": g("cool_alone", "r2")}
    lines += ["## off_all − 自分だけ"] + [f"{r}: all {g('off_all', r):+.2f} − alone {a:+.2f} = {g('off_all', r) - a:+.2f}"
                                       for r, a in alone.items()] + [""]
    lines += ["## (a) ファンの風:fanA_r6 − off_r6"] + [f"{r}: {g('fanA_r6', r) - g('off_r6', r):+.2f}"
                                                   for r in ["r2", "r7", "r1", "r3"]] + [""]
    lines += ["## (b) 冷却時", cool_df.to_string(index=False)]
    if len(cool_df) == 2:
        a, n = cool_df.iloc[0], cool_df.iloc[1]
        lines.append(f"cool_nbrs − cool_alone(最後 60 秒、室温を引く): "
                     f"{n.fan_last60_minus_room - a.fan_last60_minus_room:+.2f}")
    lines += ["", f"## 強制 ON:テレメトリで failsafe=1 の行 {len(fs)}(ホスト別 {fs.groupby('host').size().to_dict()})",
              fs_ev.to_string() if len(fs_ev) else "events.csv に強制 ON の記録なし"]
    if len(fs):
        for h, s in fs.groupby("host"):
            lines.append(f"{h}: {pd.to_datetime(s.ts.min(), unit='s', utc=True).tz_convert('Asia/Tokyo'):%H:%M:%S}〜"
                         f"{pd.to_datetime(s.ts.max(), unit='s', utc=True).tz_convert('Asia/Tokyo'):%H:%M:%S}")
    lines += ["", "## 囲いの中の温度計(各ブロックの負荷の最後 60 秒)"]
    for ph in [p for p in phases if p.endswith("_load") or p.endswith("_fan")]:
        t0, t1 = phases[ph]
        vals = {n: amb_mean(amb, n, t1 - WIN, t1) for n in ["防水温湿度計 1", "防水温湿度計 2", "防水温湿度計 3", ROOM]}
        lines.append(ph + ": " + "  ".join(f"{k} {v:.1f}" for k, v in vals.items()))
    lines += ["", "## 箱の中の温度の変化(負荷の最後 60 秒 − 直前 60 秒、ハブ 2 の変化は引かない)と、上昇 − 温度計 1 の変化"]
    for ph in [p for p in phases if p.endswith("_load")]:
        t0, t1 = phases[ph]
        d = {n: amb_mean(amb, n, t1 - WIN, t1) - amb_mean(amb, n, t0 - WIN, t0)
             for n in ["防水温湿度計 1", "防水温湿度計 2", "防水温湿度計 3"]}
        sub = rise_df[rise_df.phase == ph.removesuffix("_load")].set_index("role")
        ex = (sub.raw_rise - d["防水温湿度計 1"]).round(2).to_dict()
        lines.append(ph + ": " + "  ".join(f"{k[-1]}:{v:+.2f}" for k, v in d.items())
                     + " | 上昇−温度計1: " + " ".join(f"{r}{v:+.1f}" for r, v in ex.items()))
    txt = "\n".join(lines)
    (out / "summary.txt").write_text(txt)
    print(txt)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
