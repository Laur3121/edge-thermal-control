#!/usr/bin/env python3
"""遅い冷却のシミュレーションの確認の実行(新しい負荷パターン)。条件は
experiments/20261122_sim_slow_cooling/README.md の「確認の実行」(実行前に記録)。"""

from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sim_slow_cooling as S  # noqa: E402

SEED_PAT = 20261123
OUT = S.OUT / "confirm"


def new_patterns():
    rng = np.random.default_rng(SEED_PAT)
    pats = {}
    for i in range(3):
        seq, total = [], 0
        while total < 3 * 3600:
            dur = int(rng.integers(2, 11)) * 60
            seq.append((int(rng.integers(0, 5)), dur))
            total += dur
        pats[f"new{i + 1}"] = np.concatenate([np.full(int(d / S.DT), c / 4) for c, d in seq])
    return pats


def run(args):
    kind, delay, rule = args
    plant, cp = S.load_models()
    rows = []
    for pname, u in new_patterns().items():
        for mode, grid in S.SWEEPS.items():
            for val in grid:
                r = S.simulate(plant, cp, u, kind, delay, mode, float(val), rule=rule)
                rows.append({"rule": rule, "kind": kind, "delay_s": delay, "pattern": pname, "mode": mode,
                             "value": float(val), **r})
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(k, d, r) for r in ("off", "next") for k, d in S.DELAYS]
    with ProcessPoolExecutor() as ex:
        df = pd.DataFrame([r for part in ex.map(run, jobs) for r in part])
    df.to_csv(OUT / "results.csv", index=False, float_format="%.4f")
    best, piv = S.summarize(df)
    m78 = (df[(df.T_max <= 78)].groupby(["rule", "kind", "delay_s", "pattern", "mode"]).fan_ratio.min()
           .unstack("mode")[list(S.SWEEPS)])
    piv.to_csv(OUT / "summary.csv", index=False, float_format="%.4f")
    m78.to_csv(OUT / "min_duty_T78.csv", float_format="%.4f")
    with pd.option_context("display.width", 200, "display.max_rows", 200):
        print(piv.to_string(index=False, float_format="%.3f"))
        print((m78 * 100).round(1).groupby(["rule", "kind", "delay_s"]).mean())


if __name__ == "__main__":
    main()
