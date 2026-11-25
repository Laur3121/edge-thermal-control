#!/bin/bash
# 11/26 の連続実行(入れ替え版、8:20):d90 の終わりを待つ → stage2 → next_20261126.sh
cd ~/edge-thermal-control
PY=~/sotuken/venv/bin/python
NODES="r1=raspi1 r2=raspi2 r3=raspi3 r4=raspi4 r5=raspi5 r6=raspi6 r7=raspi7 r8=raspi8"
log() { echo "$(date '+%F %T') $*" >> experiments/chain_20261126.log; }
wait_end() { until grep -qE ",(end|aborted|interrupted)," "$1/events.csv" 2>/dev/null && ! pgrep -f "run_experiment.py.*$1" >/dev/null; do sleep 30; done; }
run() {  # $1 名前, $2 シナリオ, $3 パラメータ
  local exp=experiments/$1
  for i in 1 2 3 4 5 6 7 8; do ssh -o ConnectTimeout=5 -o BatchMode=yes ubuntu@192.168.0.5$i "sudo -n systemctl restart etc-agent"; done
  log "start $1 ($3)"
  setsid nohup $PY scripts/run_experiment.py --scenario "$2" --nodes $NODES --out $exp --ambient --ambient-name ハブ２ \
    --control-params "$3" > experiments/${1}_run.log 2>&1 < /dev/null &
  sleep 15
  setsid nohup $PY scripts/box_watchdog.py --exp $exp --limit 50 > experiments/${1}_watchdog.out 2>&1 < /dev/null &
  sleep 30
  wait_end $exp
  pkill -f "box_watchdog.py --exp $exp"
  log "end $1: $(tail -1 $exp/events.csv)"
  if grep -q "上限超え" experiments/${1}_watchdog.out 2>/dev/null; then log "watchdog stopped $1; chain aborted"; exit 0; fi
}
log "chain b start (waiting for 20261126_box_control_d90)"
wait_end experiments/20261126_box_control_d90
pkill -f "box_watchdog.py --exp experiments/20261126_box_control_d90"
log "d90 ended: $(tail -1 experiments/20261126_box_control_d90/events.csv)"
if grep -q "上限超え" experiments/20261126_box_control_d90_watchdog.out 2>/dev/null; then log "watchdog stopped d90; chain aborted"; exit 0; fi
D=$($PY - <<'PYEOF'
import numpy as np, pandas as pd
d = "experiments/20261126_box_control_d90/"
tel = pd.read_csv(d + "raw/telemetry.csv"); ev = pd.read_csv(d + "events.csv")
ps = ev[ev.event == "phase_start"][["ts", "phase"]].reset_index(drop=True)
ps["end"] = list(ps.ts[1:]) + [ev.ts.max()]
over = {}
for cond in ("threshold", "proposed"):
    tot = 0.0
    for k in (1, 2):
        sub = ps[ps.phase.str.match(rf"c{k}_{cond}_s\d")]
        if sub.empty:
            continue
        w = tel[(tel.ts >= sub.ts.min()) & (tel.ts < sub.end.max())]
        for h, g in w.groupby("host"):
            g = g.sort_values("ts")
            dt = np.clip(np.diff(g.ts.to_numpy(), append=g.ts.iloc[-1]), 0, 5)
            tot += dt[g.temp.to_numpy() > 80].sum()
    over[cond] = tot
print(90 if over["proposed"] < over["threshold"] else 30, over["threshold"], over["proposed"])
PYEOF
)
log "d90: over80 threshold/proposed = $(echo $D | cut -d' ' -f2,3) -> stage2 uses delta $(echo $D | cut -d' ' -f1)"
run 20261126_box_control_stage2 scripts/scenarios/box_control_stage2_d$(echo $D | cut -d' ' -f1).json scripts/control_params_box2.json
log "run next_20261126.sh"
bash scripts/next_20261126.sh
log "chain b done"
