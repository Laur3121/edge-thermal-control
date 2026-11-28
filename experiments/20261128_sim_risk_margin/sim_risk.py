import json, sys, math
from collections import deque
import numpy as np
sys.path.insert(0, "src")
from etc.control import ControlConfig, controller_from_dict
from etc.model import ThermalParams
P = json.load(open("scripts/control_params_open.json"))
dt = 5.0
STEP = [(1,120),(4,360),(0,180),(4,300),(2,120),(4,120)]
RAMP = [(1,120),(2,60),(3,60),(4,240),(0,180),(1,60),(2,60),(3,60),(4,120),(2,120),(3,60),(4,60)]
def seq(p): return np.concatenate([np.full(int(d/dt), c/4) for c,d in p])
hosts = [f"raspi{i}" for i in range(1, 9) if i != 5]
Phi = lambda x: 0.5*(1+math.erf(x/math.sqrt(2)))

def simulate(ctrl, p, U, T_amb=20.0, T0=58.0, noise_sd=0.3, seed=0, delay_steps=0, fs_on=82.0):
    rng = np.random.default_rng(seed); th = T0-T_amb; Tl=[]; fl=[]; cmds=[]; f_cur=0
    for k,u in enumerate(U):
        y = th+T_amb+rng.normal(0,noise_sd)
        dec = ctrl.step(k*p.dt, y, u, f_cur, T_amb)
        Tl.append(th+T_amb); fl.append(f_cur)
        th = p.a*th + p.b*u + p.e*f_cur + p.d
        cmds.append(dec.fan); src=len(cmds)-1-delay_steps
        f_cmd = cmds[src] if src>=0 else 0
        f_cur = 1 if th+T_amb >= fs_on else f_cmd
    return np.array(Tl), np.array(fl)

def rise_prob(U, m, thr=0.2):
    n = len(U)-m
    return float(np.mean([U[k+1:k+m+1].max()-U[k] >= thr for k in range(n)]))

class D:
    def __init__(s, fan): s.fan = fan

class RiskCtrl:
    """負荷が上がる確率を入れた判断(README の方法)。KF の更新は中の proposed に任せ、判断は自分でする"""
    def __init__(s, node, L, eps, p_rise, tlimit=80.0, min_on=30.0):
        s.inner = controller_from_dict("proposed", node, ControlConfig(fan_delay_s=L))
        s.Ld, s.m = s.inner.Ld, s.inner.m
        s.hist = deque([0]*s.Ld, maxlen=s.Ld) if s.Ld else None
        s.eps, s.p, s.tl, s.min_on = eps, p_rise, tlimit, min_on
        s.fan, s.on_since = 0, None
    def path_max(s, fs, useq, z):
        kf = s.inner.kf; x = kf.x.copy(); mx = -1e9
        for f, u in zip(fs, useq):
            x = kf.A @ x + kf._drive(u, z, float(f)); mx = max(mx, x[0])
        return mx
    def step(s, t, T, u, f, T_amb):
        s.inner.step(t, T, u, f, T_amb)  # KF を更新(中の判断は使わない)
        kf = s.inner.kf; z = s.inner.p.z_base - s.inner.p.z_base
        fs = ([0.0] + [float(v) for v in s.hist] + [0.0]*(s.m-1-s.Ld))[:s.m] if s.Ld else [0.0]*s.m
        _, sig = kf.predict_path(fs, u, s.inner.p.z_base)
        thr = s.tl - T_amb
        pc = Phi((s.path_max(fs, [u]*s.m, z) - thr)/sig)
        ups = [v for v in (0.25, 0.5, 0.75, 1.0) if v > u + 1e-6]
        if ups and u < 0.95:
            pr = np.mean([Phi((s.path_max(fs, [u]*st + [v]*(s.m-st), z) - thr)/sig) for st in range(s.m) for v in ups])
            P = (1-s.p)*pc + s.p*pr
        else:
            P = pc
        ok = s.on_since is None or t - s.on_since >= s.min_on
        if s.fan == 0 and P > s.eps: s.fan, s.on_since = 1, t
        elif s.fan == 1 and ok and P < s.eps/2: s.fan, s.on_since = 0, None
        if s.hist is not None: s.hist.append(s.fan)
        return D(s.fan)

def run(make, U, L):
    duty=[]; over=0.0
    for h in hosts:
        s = P["nodes"][h]["self"]
        plant = ThermalParams(a=s["a"], b=s["b"], d=s["d"], e=s["e"], c=0.0, dt=s["dt"])
        for seed in (1,2):
            T,f = simulate(make(h), plant, U, seed=seed, delay_steps=int(L/dt))
            duty.append(f.mean()); over += (T>80).sum()*dt
    return float(np.mean(duty))*100, over

if __name__ == "__main__":
    out = {}
    for pn, pat in (("一気", STEP), ("徐々", RAMP)):
        U = seq(pat)
        for L in (30, 60):
            m = int((30+L)/dt); pr = rise_prob(U, m)
            fixed = [(dl,)+run(lambda h, dl=dl: controller_from_dict("proposed", P["nodes"][h], ControlConfig(fan_delay_s=L, delta_margin=dl)), U, L)
                     for dl in (0, 0.5, 1, 2, 3, 4, 6, 8, 10)]
            risk = [(e,)+run(lambda h, e=e: RiskCtrl(P["nodes"][h], L, e, pr), U, L) for e in (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5)]
            fd = sorted((d_, o) for _, d_, o in fixed)
            xs, ys = [a for a,_ in fd], [b for _,b in fd]
            ratios=[]
            for e, d_, o in risk:
                if xs[0] <= d_ <= xs[-1]:
                    ref = float(np.interp(d_, xs, ys))
                    if ref >= 30: ratios.append(o/ref)
            med = float(np.median(ratios)) if ratios else float("nan")
            verdict = "良い" if med <= 0.7 else "良くない" if med >= 1.0 else "はっきりしない"
            print(f"== {pn} 遅れ{L} p={pr:.2f}")
            print("  固定δ:", "  ".join(f"{a}:{b:.0f}%/{c:.0f}s" for a,b,c in fixed))
            print("  リスク:", "  ".join(f"{a}:{b:.0f}%/{c:.0f}s" for a,b,c in risk))
            print(f"  比 {[round(r,2) for r in ratios]} 中央値 {med:.2f} → {verdict}")
            out[f"{pn}|{L}"] = dict(p=pr, fixed=fixed, risk=risk, ratios=ratios, med=med, verdict=verdict)
    json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False)
