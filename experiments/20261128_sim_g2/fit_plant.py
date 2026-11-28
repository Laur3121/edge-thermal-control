"""11/28 の実機データで G2 の実機役を同定する(第 1 段の準備)。"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from g2lib import fit_g2, arrays, H, ROOT  # noqa: E402
runs = [arrays(ROOT / e) for e in ("experiments/20261127_delay_sweep/d60", "experiments/20261127_delay_sweep/d30",
                                     "experiments/20261127_tradeoff/d60")]
P = {}
for i, h in enumerate(H):
    if h == "raspi5":
        continue
    P[h] = fit_g2(runs, i).tolist(); print(h, [round(v, 3) for v in P[h]])
out = Path(__file__).parent / "results"; out.mkdir(exist_ok=True)
(out / "plant_g2_1128.json").write_text(json.dumps(P, indent=1))
