"""第 1 段:G2 の実機役で A・A' の 6 設定を再現できるか。"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from g2lib import G2Plant, simulate_g2, ROOT, DT  # noqa: E402
from etc.control import ControlConfig, controller_from_dict  # noqa: E402
PL = json.loads((Path(__file__).parent / "results/plant_g2_1128.json").read_text())
PAR = json.loads((ROOT / "scripts/control_params_open.json").read_text())["nodes"]
STEP = [(1,120),(4,360),(0,180),(4,300),(2,120),(4,120)]
RAMP = [(1,120),(2,60),(3,60),(4,240),(0,180),(1,60),(2,60),(3,60),(4,120),(2,120),(3,60),(4,60)]
seq = lambda p: np.concatenate([np.full(int(d / DT), c / 4) for c, d in p])
SET = {"th65": ("threshold", dict(t_on=65, t_off=60)), "th70": ("threshold", dict(t_on=70, t_off=65)),
       "th75": ("threshold", dict(t_on=75, t_off=70)), "pd0p5": ("proposed", dict(delta_margin=0.5)),
       "pd3": ("proposed", dict(delta_margin=3)), "pd6": ("proposed", dict(delta_margin=6))}
REAL = {"一気": "experiments/20261127_tradeoff/d60", "徐々": "experiments/20261127_tradeoff/ramp_d60"}


# 実測の条件(11/28 夜、第 1 段が決めた条件で再現できなかったので実測に合わせた。README に記載)
COND = {"一気": (21.1, {"raspi1": 67.3, "raspi2": 62.9, "raspi3": 64.5, "raspi4": 61.9, "raspi6": 70.1, "raspi7": 66.0, "raspi8": 58.7}),
        "徐々": (21.8, {"raspi1": 68.1, "raspi2": 64.4, "raspi3": 66.0, "raspi4": 63.0, "raspi6": 69.9, "raspi7": 66.8, "raspi8": 59.2})}
CUR = {"pn": "一気"}


def run(make, U, L=60):
    duty, over = [], 0.0
    Ta, T0 = COND[CUR["pn"]]
    for h, p in PL.items():
        for seed in (1, 2):
            T, f = simulate_g2(make(h), G2Plant(p, T_amb=Ta, T0=T0[h], u0=0.0), U, seed=seed, delay_steps=int(L / DT))
            duty.append(f.mean()); over += (T > 80).sum() * DT
    return np.mean(duty) * 100, over


rows = []
for pn, pat in (("一気", STEP), ("徐々", RAMP)):
    CUR["pn"] = pn
    real = pd.read_csv(ROOT / REAL[pn] / "results/control_summary.csv"); real = real[real.host != "raspi5"]
    ra = real.groupby("cond").agg(duty=("duty", "mean"), over=("over80_s", "sum"))
    for name, (mode, kw) in SET.items():
        d, o = run(lambda h: controller_from_dict(mode, PAR[h], ControlConfig(fan_delay_s=60, **kw)), seq(pat))
        rd, ro = ra.loc[name, "duty"] * 100, ra.loc[name, "over"]
        ok = abs(d - rd) <= 5 and ((0.5 * ro <= o <= 2 * ro) if ro >= 60 else o < 120)
        rows.append(dict(load=pn, set=name, sim_duty=round(d, 1), real_duty=round(rd, 1), sim_over=round(o), real_over=round(ro), ok=ok))
df = pd.DataFrame(rows); print(df.to_string(index=False))
print("再現できた点:", int(df.ok.sum()), "/ 12 →", "再現できた" if df.ok.sum() >= 9 else "再現できない")
df.to_csv(Path(__file__).parent / "results/stage1_measured.csv", index=False)
