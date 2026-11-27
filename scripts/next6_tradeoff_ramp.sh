#!/bin/bash
# next5(tradeoff A)が終わってから、A'(負荷が徐々に上がる版、遅れ 60 秒)を回す(11/27 夕、
# experiments/20261127_tradeoff/README.md の A')。next3〜5 には触らない
cd ~/edge-thermal-control
PY=~/sotuken/venv/bin/python
NODES="r1=raspi1 r2=raspi2 r3=raspi3 r4=raspi4 r5=raspi5 r6=raspi6 r7=raspi7 r8=raspi8"
log() { echo "$(date '+%F %T') $*" >> experiments/chain_20261126.log; }
until grep -q "next5 done" experiments/chain_20261126.log; do sleep 60; done
wait_end() { until grep -qE ",(end|aborted|interrupted)," "$1/events.csv" 2>/dev/null && ! pgrep -f "run_experiment.py.*$1" >/dev/null; do sleep 30; done; }
log "next6(tradeoff_ramp)開始"
exp=experiments/20261127_tradeoff/ramp_d60
for i in 1 2 3 4 5 6 7 8; do ssh -o ConnectTimeout=5 -o BatchMode=yes ubuntu@192.168.0.5$i "sudo -n systemctl restart etc-agent"; done
log "start $exp"
setsid nohup $PY scripts/run_experiment.py --scenario scripts/scenarios/tradeoff_ramp_d60.json --nodes $NODES --out $exp \
  --ambient --ambient-name ハブ２ --control-params scripts/control_params_open.json > ${exp}_run.log 2>&1 < /dev/null &
sleep 45
wait_end $exp
log "end $exp: $(tail -1 $exp/events.csv)"
$PY scripts/analyze_box_control.py $exp > ${exp}_analyze.log 2>&1
$PY scripts/judge_tradeoff.py $exp > ${exp}_judge.txt 2>&1
log "judge $exp: $(tail -1 ${exp}_judge.txt)"
log "next6 done"
