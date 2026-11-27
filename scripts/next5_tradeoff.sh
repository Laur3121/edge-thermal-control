#!/bin/bash
# next4(delay_sweep)が終わってから、実験 A(tradeoff、遅れ 60 秒)を回す。判定が yes なら遅れ 30 秒も回す(11/27 夕、
# experiments/20261127_tradeoff/README.md で実行前に決めた分岐)。next3・next4 には触らない
cd ~/edge-thermal-control
PY=~/sotuken/venv/bin/python
NODES="r1=raspi1 r2=raspi2 r3=raspi3 r4=raspi4 r5=raspi5 r6=raspi6 r7=raspi7 r8=raspi8"
log() { echo "$(date '+%F %T') $*" >> experiments/chain_20261126.log; }
until grep -q "next4 done" experiments/chain_20261126.log; do sleep 60; done
wait_end() { until grep -qE ",(end|aborted|interrupted)," "$1/events.csv" 2>/dev/null && ! pgrep -f "run_experiment.py.*$1" >/dev/null; do sleep 30; done; }
run() {  # $1 = 遅れ [秒]
  exp=experiments/20261127_tradeoff/d$1
  for i in 1 2 3 4 5 6 7 8; do ssh -o ConnectTimeout=5 -o BatchMode=yes ubuntu@192.168.0.5$i "sudo -n systemctl restart etc-agent"; done
  log "start $exp"
  setsid nohup $PY scripts/run_experiment.py --scenario scripts/scenarios/tradeoff_d$1.json --nodes $NODES --out $exp \
    --ambient --ambient-name ハブ２ --control-params scripts/control_params_open.json > ${exp}_run.log 2>&1 < /dev/null &
  sleep 45
  wait_end $exp
  log "end $exp: $(tail -1 $exp/events.csv)"
  $PY scripts/analyze_box_control.py $exp > ${exp}_analyze.log 2>&1
  $PY scripts/judge_tradeoff.py $exp > ${exp}_judge.txt 2>&1
  log "judge $exp: $(tail -1 ${exp}_judge.txt)"
}
log "next5(tradeoff)開始"
run 60
if grep -q "JUDGE=yes" experiments/20261127_tradeoff/d60_judge.txt; then
  run 30
else
  log "tradeoff d60 は yes でない → d30 は回さない(README の分岐)"
fi
log "next5 done"
