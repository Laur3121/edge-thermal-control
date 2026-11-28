"""2 段のモデル G2 の同定・シミュレーション・制御器(sim_g2 用)。"""
import json, math, sys
from collections import deque
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "experiments/20261128_model_check"))
sys.path.insert(0, str(ROOT / "experiments/20261128_model_rack"))
from check_models import arrays, H, fit  # noqa: E402
M90 = 18; DT = 5.0
Phi = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _ms(p, th, u, f, ks, m=M90):
    a11, a12, b1, e1, d1, a21, a22, b2, e2, d2 = p
    x2 = np.empty_like(th); x2[0] = th[0]
    for t in range(len(th) - 1):
        x2[t + 1] = a21 * th[t] + a22 * x2[t] + b2 * u[t] + e2 * f[t] + d2
    x1, y2 = th[ks].copy(), x2[ks].copy(); out = []
    for j in range(m):
        x1, y2 = (a11 * x1 + a12 * y2 + b1 * u[ks + j] + e1 * f[ks + j] + d1,
                  a21 * x1 + a22 * y2 + b2 * u[ks + j] + e2 * f[ks + j] + d2)
        out.append(th[ks + j + 1] - x1)
    return np.array(out)


def _starts(ok, lo, hi):
    return np.array([k for k in range(max(lo, 1), hi - M90) if ok[k - 1:k + M90 + 1].all()])


def fit_g2(runs, i):
    """runs:[(th, u, f, ok), ...](各 (8, n))。ノード i の G2 の係数。"""
    th0, u0, f0, ok0 = runs[0]
    a, b, e, d = fit("S1", th0[i], u0[i], f0[i], ok0[i], 0, th0.shape[1])
    lo = [-np.inf] * 10; hi = [np.inf] * 10; lo[6], hi[6] = 0.0, 0.995
    best = None
    for split in (0.3, 0.6):
        p0 = [a - 0.05, 0.05, b * split, e * 0.2, d * 0.5, 0.05, 0.93, b * (1 - split) * 0.3, e * 0.5, d * 0.3]
        def resid(p):
            r = np.concatenate([_ms(p, th[i], u[i], f[i], _starts(ok[i], 0, th.shape[1])).ravel() for th, u, f, ok in runs])
            return r if np.isfinite(r).all() else np.full(r.size, 1e3)
        r = least_squares(resid, p0, bounds=(lo, hi))
        if best is None or r.cost < best.cost:
            best = r
    return best.x


class G2Plant:
    def __init__(s, p, T_amb=20.0, T0=58.0, u0=0.25):
        s.p = p; s.Ta = T_amb
        a11, a12, b1, e1, d1, a21, a22, b2, e2, d2 = p
        s.x1 = T0 - T_amb; s.x2 = (a21 * s.x1 + b2 * u0 + d2) / (1 - a22)

    def step(s, u, f):
        a11, a12, b1, e1, d1, a21, a22, b2, e2, d2 = s.p
        s.x1, s.x2 = (a11 * s.x1 + a12 * s.x2 + b1 * u + e1 * f + d1, a21 * s.x1 + a22 * s.x2 + b2 * u + e2 * f + d2)

    @property
    def T(s):
        return s.x1 + s.Ta


def simulate_g2(ctrl, plant, U, noise_sd=0.3, seed=0, delay_steps=0, fs_on=82.0):
    rng = np.random.default_rng(seed); Tl, fl, cmds = [], [], []; f_cur = 0
    for k, u in enumerate(U):
        y = plant.T + rng.normal(0, noise_sd)
        dec = ctrl.step(k * DT, y, u, f_cur, plant.Ta)
        Tl.append(plant.T); fl.append(f_cur)
        plant.step(u, f_cur)
        cmds.append(dec.fan); src = len(cmds) - 1 - delay_steps
        f_cmd = cmds[src] if src >= 0 else 0
        f_cur = 1 if plant.T >= fs_on else f_cmd
    return np.array(Tl), np.array(fl)


class D:
    def __init__(s, fan): s.fan = fan


class G2Ctrl:
    """制御側のモデルを G2 にした KF + 判断。mode = "fixed"(Tsafe = 80 − 2σ − δ)か "risk"(負荷リスク、ε)"""
    def __init__(s, p, L, mode, knob, p_rise=0.2, q=(0.05, 0.01), R=0.09, tlimit=80.0, min_on=30.0, hyst=1.0, delta_s=30.0):
        a11, a12, b1, e1, d1, a21, a22, b2, e2, d2 = p
        s.A = np.array([[a11, a12], [a21, a22]]); s.B = np.array([b1, b2]); s.E = np.array([e1, e2]); s.dd = np.array([d1, d2])
        s.Q = np.diag(q); s.R = R; s.x = None; s.P = np.eye(2) * 4.0; s.prev = None
        s.Ld = int(round(L / DT)); s.m = int(round((delta_s + L) / DT))
        s.hist = deque([0] * s.Ld, maxlen=s.Ld) if s.Ld else None
        s.mode, s.knob, s.p, s.tl, s.min_on, s.h = mode, knob, p_rise, tlimit, min_on, hyst
        s.fan, s.on_since = 0, None

    def _path(s, fs, useq):
        x = s.x.copy(); P = s.P.copy(); mx = -1e9
        for f, u in zip(fs, useq):
            x = s.A @ x + s.B * u + s.E * f + s.dd; P = s.A @ P @ s.A.T + s.Q; mx = max(mx, x[0])
        return mx, math.sqrt(P[0, 0])

    def step(s, t, T, u, f, T_amb):
        th = T - T_amb
        if s.x is None:
            s.x = np.array([th, th])
        else:
            u0, f0 = s.prev
            s.x = s.A @ s.x + s.B * u0 + s.E * f0 + s.dd; s.P = s.A @ s.P @ s.A.T + s.Q
            K = s.P[:, 0] / (s.P[0, 0] + s.R); s.x = s.x + K * (th - s.x[0]); s.P = s.P - np.outer(K, s.P[0, :])
        s.prev = (u, f)
        fs = ([0.0] + [float(v) for v in s.hist] + [0.0] * (s.m - 1 - s.Ld))[:s.m] if s.Ld else [0.0] * s.m
        thr = s.tl - T_amb
        pc, sig = s._path(fs, [u] * s.m)
        ok = s.on_since is None or t - s.on_since >= s.min_on
        if s.mode == "fixed":
            tsafe = thr - 2 * sig - s.knob
            on, off = pc > tsafe, pc < tsafe - s.h
        else:
            P = Phi((pc - thr) / sig)
            ups = [v for v in (0.25, 0.5, 0.75, 1.0) if v > u + 1e-6]
            if ups and u < 0.95:
                pr = np.mean([Phi((s._path(fs, [u] * st + [v] * (s.m - st))[0] - thr) / sig) for st in range(0, s.m, 2) for v in ups])
                P = (1 - s.p) * P + s.p * pr
            on, off = P > s.knob, P < s.knob / 2
        if s.fan == 0 and on: s.fan, s.on_since = 1, t
        elif s.fan == 1 and ok and off: s.fan, s.on_since = 0, None
        if s.hist is not None: s.hist.append(s.fan)
        return D(s.fan)
