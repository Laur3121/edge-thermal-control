"""第 2 段:実測の条件の 2 つの実機役(G2・1 次)で、しきい値/今の提案(固定 δ)/負荷リスク(1 次)/2 段の提案(固定 δ・負荷リスク)を比べる。"""
import json, sys, io, contextlib
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "20261128_sim_risk_margin"))
from g2lib import G2Plant, G2Ctrl, simulate_g2, ROOT, DT  # noqa: E402
from etc.control import ControlConfig, controller_from_dict  # noqa: E402
PL = json.loads((Path(__file__).parent / "results/plant_g2_1128.json").read_text())
G2C = json.loads((ROOT / "experiments/20261128_model_check/results/g2_params.json").read_text())
PAR = json.loads((ROOT / "scripts/control_params_open.json").read_text())["nodes"]
STEP = [(1,120),(4,360),(0,180),(4,300),(2,120),(4,120)]
RAMP = [(1,120),(2,60),(3,60),(4,240),(0,180),(1,60),(2,60),(3,60),(4,120),(2,120),(3,60),(4,60)]
seq = lambda p: np.concatenate([np.full(int(d / DT), c / 4) for c, d in p])
COND = {"一気": (21.1, {"raspi1": 67.3, "raspi2": 62.9, "raspi3": 64.5, "raspi4": 61.9, "raspi6": 70.1, "raspi7": 66.0, "raspi8": 58.7}),
        "徐々": (21.8, {"raspi1": 68.1, "raspi2": 64.4, "raspi3": 66.0, "raspi4": 63.0, "raspi6": 69.9, "raspi7": 66.8, "raspi8": 59.2})}
EPS = (0.005, 0.02, 0.05, 0.1, 0.3)
DELTA = (0, 1, 3, 6, 10)
TON = (60, 65, 70, 75, 78)


class S1Plant:
    def __init__(s, p, T_amb, T0): s.p, s.Ta, s.th = p, T_amb, T0 - T_amb
    def step(s, u, f): p = s.p; s.th = p["a"] * s.th + p["b"] * u + p["e"] * f + p["d"]
    @property
    def T(s): return s.th + s.Ta


def rise_prob(U, m, thr=0.2):
    return float(np.mean([U[k + 1:k + m + 1].max() - U[k] >= thr for k in range(len(U) - m)]))


def job(args):
    plant_kind, pn, L, ctrl_kind, knob = args
    with contextlib.redirect_stdout(io.StringIO()):
        from sim_risk import RiskCtrl  # noqa
    U = seq(STEP if pn == "一気" else RAMP); Ta, T0 = COND[pn]; m = int((30 + L) / DT); pr = rise_prob(U, m)
    duty, over = [], 0.0
    for h in PL:
        for seed in (1, 2):
            plant = G2Plant(PL[h], T_amb=Ta, T0=T0[h], u0=0.0) if plant_kind == "G2" else S1Plant(PAR[h]["self"], Ta, T0[h])
            if ctrl_kind == "しきい値":
                c = controller_from_dict("threshold", PAR[h], ControlConfig(fan_delay_s=L, t_on=knob, t_off=knob - 5))
            elif ctrl_kind == "1次・固定δ":
                c = controller_from_dict("proposed", PAR[h], ControlConfig(fan_delay_s=L, delta_margin=knob))
            elif ctrl_kind == "1次・負荷リスク":
                c = RiskCtrl(PAR[h], L, knob, pr)
            elif ctrl_kind == "2段・固定δ":
                c = G2Ctrl(G2C[h], L, "fixed", knob)
            else:
                c = G2Ctrl(G2C[h], L, "risk", knob, p_rise=pr)
            T, f = simulate_g2(c, plant, U, seed=seed, delay_steps=int(L / DT))
            duty.append(f.mean()); over += (T > 80).sum() * DT
    return dict(plant=plant_kind, load=pn, delay=L, ctrl=ctrl_kind, knob=knob, duty=np.mean(duty) * 100, over=over)


if __name__ == "__main__":
    jobs = []
    for plant in ("G2", "1次"):
        for pn in ("一気", "徐々"):
            for L in (30, 60):
                jobs += [(plant, pn, L, "しきい値", t) for t in TON]
                jobs += [(plant, pn, L, k, d) for k in ("1次・固定δ", "2段・固定δ") for d in DELTA]
                jobs += [(plant, pn, L, k, e) for k in ("1次・負荷リスク", "2段・負荷リスク") for e in EPS]
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(job, jobs, chunksize=2))
    df = pd.DataFrame(rows); out = Path(__file__).parent / "results"; df.to_csv(out / "stage2.csv", index=False)
    print(len(df), "点")
