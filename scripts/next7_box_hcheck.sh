#!/bin/bash
# 実験 B(囲いあり + 遅れ 60 秒で、提案の H あり/なしを比べる。11/28 夜、experiments/20261128_box_hcheck/README.md)。
# next8(負荷リスクの実機、囲いなし)が終わり、レオが箱をかぶせたら(Claude が experiments/BOX_ON を作る)始める。
# 同定(box_ident)→ 前半 6 割で同定 → 後半 4 割で check_params_holdout → c > 0 が 7 台中 3 台以上 → 制御の比較。
# どこかで条件を満たさなければ止める(README で実行前に決めた)
cd ~/edge-thermal-control
PY=~/sotuken/venv/bin/python
NODES="r1=raspi1 r2=raspi2 r3=raspi3 r4=raspi4 r5=raspi5 r6=raspi6 r7=raspi7 r8=raspi8"
log() { echo "$(date '+%F %T') $*" >> experiments/chain_20261126.log; }
wait_end() { until grep -qE ",(end|aborted|interrupted)," "$1/events.csv" 2>/dev/null && ! pgrep -f "run_experiment.py.*$1" >/dev/null; do sleep 30; done; }
run() {  # $1 フォルダ, $2 シナリオ, $3 パラメータ
  local exp=$1
  for i in 1 2 3 4 5 6 7 8; do ssh -o ConnectTimeout=5 -o BatchMode=yes ubuntu@192.168.0.5$i "sudo -n systemctl restart etc-agent"; done
  log "start $exp ($3)"
  setsid nohup $PY scripts/run_experiment.py --scenario "$2" --nodes $NODES --out $exp --ambient --ambient-name ハブ２ \
    --control-params "$3" > ${exp}_run.log 2>&1 < /dev/null &
  sleep 15
  setsid nohup $PY scripts/box_watchdog.py --exp $exp --limit 50 > ${exp}_watchdog.out 2>&1 < /dev/null &
  sleep 30
  wait_end $exp
  pkill -f "box_watchdog.py --exp $exp"
  log "end $exp: $(tail -1 $exp/events.csv)"
}
until grep -q "next8 done" experiments/chain_20261126.log; do sleep 60; done
log "next7(box_hcheck):箱を待つ(experiments/BOX_ON)"
until [ -f experiments/BOX_ON ]; do sleep 30; done
log "箱をかぶせた:$(cat experiments/BOX_ON)"
B=experiments/20261128_box_hcheck
mkdir -p $B
run $B/ident scripts/scenarios/box_ident.json scripts/control_params_box2.json
$PY scripts/fit_control_params_box.py --exp experiments/20261125_pattern_box_front_open $B/ident --head-frac 0.6 \
  --out scripts/control_params_box3.json > $B/fit_params.txt 2>&1
if ! $PY scripts/check_params_holdout.py scripts/control_params_box3.json $B/ident > $B/check_params_box3.txt 2>&1; then
  log "check_params_holdout NG(box3)→ B の制御は回さない"; log "next7 done"; exit 0; fi
NC=$($PY -c "import json;P=json.load(open('scripts/control_params_box3.json'))['nodes'];print(sum(1 for h,n in P.items() if h!='raspi5' and n.get('withH',{}).get('c',0)>0))")
log "box3:c > 0 は 7 台中 $NC 台"
if [ "$NC" -lt 3 ]; then log "c > 0 が 3 台未満 → H あり/なしの比較にならないので止める"; log "next7 done"; exit 0; fi
run $B/ctrl scripts/scenarios/box_hcheck_d60.json scripts/control_params_box3.json
$PY scripts/analyze_box_control.py $B/ctrl > $B/ctrl_analyze.log 2>&1
log "next7 done"
