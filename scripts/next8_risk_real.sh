#!/bin/bash
# 負荷リスクの動的マージンの実機の予備実験(11/29 未明、experiments/20261129_risk_real/README.md)。囲いなし。
# 一気(step)→ 徐々(ramp)を回し、judge_risk.py で判定する。next7(B、囲い)はこれが終わってから
cd ~/edge-thermal-control
PY=~/sotuken/venv/bin/python
NODES="r1=raspi1 r2=raspi2 r3=raspi3 r4=raspi4 r5=raspi5 r6=raspi6 r7=raspi7 r8=raspi8"
log() { echo "$(date '+%F %T') $*" >> experiments/chain_20261126.log; }
wait_end() { until grep -qE ",(end|aborted|interrupted)," "$1/events.csv" 2>/dev/null && ! pgrep -f "run_experiment.py.*$1" >/dev/null; do sleep 30; done; }
run() {
  local exp=$1
  for i in 1 2 3 4 5 6 7 8; do ssh -o ConnectTimeout=5 -o BatchMode=yes ubuntu@192.168.0.5$i "sudo -n systemctl restart etc-agent"; done
  log "start $exp"
  setsid nohup $PY scripts/run_experiment.py --scenario "$2" --nodes $NODES --out $exp --ambient --ambient-name ハブ２ \
    --control-params scripts/control_params_open.json > ${exp}_run.log 2>&1 < /dev/null &
  sleep 45
  wait_end $exp
  log "end $exp: $(tail -1 $exp/events.csv)"
  $PY scripts/analyze_box_control.py $exp > ${exp}_analyze.log 2>&1
}
log "next8(risk_real)開始"
R=experiments/20261129_risk_real
mkdir -p $R
run $R/step scripts/scenarios/risk_step_d60.json
run $R/ramp scripts/scenarios/risk_ramp_d60.json
$PY scripts/judge_risk.py $R/step $R/ramp > $R/judge.txt 2>&1
log "judge $R: $(tail -1 $R/judge.txt)"
log "next8 done"
