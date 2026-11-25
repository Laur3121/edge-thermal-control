# stagger_ident(囲いあり:台ごとに負荷をずらして H を同定する)

2026-11-26。条件は実行前(8:20)に決めた。生ログは編集しない。`scripts/next_20261126.sh` が自動で始める。

## なぜやるか

制御の実験では 8 台に同じ負荷を同時にかけていたので、「周りのノードの熱(H)」と「自分の負荷」が同じ動きをして区別できず、同定すると H の効き c が 8 台中 6 台で 0 になった(`docs/model-review-2026-11-26.md` の 3)。台ごとに負荷をずらしたデータで、c を同定し直す(レオ:1 個おき・一部の区画・強弱を変えるなど)。

## 条件

- 配置・囲い:昨夜から同じ。8 台とも PoE+ HAT(段階 4)
- 負荷:台ごとに独立に、0・1・2・3 コアから 180 秒ごとにランダムに選ぶ(seed 2026112640)。20 回 = 60 分
- ファン:しきい値(75℃ ON、70℃ OFF)で回す(囲いの中で 3 コアはファン OFF のままだと 80℃ を超えるため。ファンの効き e も同時に同定できる)
- シナリオ:`scripts/scenarios/gen_stagger.py ident` → `stagger_ident.json`(約 1.3 時間)
- 同定:`fit_control_params_box.py --exp experiments/20261125_pattern_box_front_open experiments/20261126_stagger_ident --out scripts/control_params_box3.json`(11/25 午後の 1 台ずつ負荷をかけたデータと合わせる。全台同時のデータ = 昨夜の制御は入れない)。`check_params.py` が NG なら、`stagger_ctrl` は `control_params_box2.json` で回し、その旨をログに書く
- 予想(Claude):c は半分以上の台で正になるが、小さい(0.01〜0.1)

## 結果

(未)
