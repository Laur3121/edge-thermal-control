#!/bin/bash
# next3(11/27 未明〜)が全部終わってから、delay_sweep(冷却の遅れ 0・15・30・60 秒)を回す。next3 には触らない(11/27 昼、レオ)
cd ~/edge-thermal-control
PY=~/sotuken/venv/bin/python
NODES="r1=raspi1 r2=raspi2 r3=raspi3 r4=raspi4 r5=raspi5 r6=raspi6 r7=raspi7 r8=raspi8"
log() { echo "$(date '+%F %T') $*" >> experiments/chain_20261126.log; }
until grep -q "next3 done" experiments/chain_20261126.log; do sleep 60; done
wait_end() { until grep -qE ",(end|aborted|interrupted)," "$1/events.csv" 2>/dev/null && ! pgrep -f "run_experiment.py.*$1" >/dev/null; do sleep 30; done; }
log "next4(delay_sweep)開始"
for d in 60 15 30 0; do
  exp=experiments/20261127_delay_sweep/d$(printf %02d $d)
  for i in 1 2 3 4 5 6 7 8; do ssh -o ConnectTimeout=5 -o BatchMode=yes ubuntu@192.168.0.5$i "sudo -n systemctl restart etc-agent"; done
  log "start $exp"
  setsid nohup $PY scripts/run_experiment.py --scenario scripts/scenarios/delay_sweep_d$d.json --nodes $NODES --out $exp \
    --ambient --ambient-name ハブ２ --control-params scripts/control_params_open.json > ${exp}_run.log 2>&1 < /dev/null &
  sleep 45
  wait_end $exp
  log "end $exp: $(tail -1 $exp/events.csv)"
done
log "next4 done"
