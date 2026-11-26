# open_ident(囲いなし:制御のパラメータの同定)

2026-11-26。条件は実行前(12:30)に決めた。生ログは編集しない。`scripts/next_20261126.sh` が、レオが箱を外した後(`experiments/BOX_REMOVED`)に自動で始める。

## なぜやるか

囲いありで同定したパラメータ(`control_params_box2.json`)は、囲いの中の温まりを含んでおり、囲いなしにそのまま使うと 11/25 夜と同じ「モデルと実機のずれ」が起きる。囲いなしで同定し直す。11/25 の囲いなしの測定(`20261125_pattern_open`)はファンを回した区間が r2・r6 にしかないので、全台のファンの効きを同定するデータを足す。

## 条件

- 配置:10 インチラック、2 段 × 4 列、**囲いなし**(箱を外す)。8 台とも PoE+ HAT(段階 4)
- 負荷:台ごとに独立に 0〜3 コアを 180 秒ごとにランダム(seed 2026112660)
- ファン:台ごとに独立に 60 秒ごと、確率 0.5 で ON(負荷と温度に関係なく決める。ファンの効きを負荷と切り分けて同定するため)
- 60 分 + 休み 10 分。シナリオ:`scripts/scenarios/gen_stagger.py ident_rf` → `open_ident.json`

## 同定と確認

- 同定:`fit_control_params_box.py --exp experiments/20261125_pattern_open experiments/20261126_open_ident --head-frac 0.6` → `scripts/control_params_open.json`(この実験は前半 6 割だけ)
- 確認:`check_params_holdout.py scripts/control_params_open.json experiments/20261126_open_ident`(後半 4 割で 30 秒先の誤差。係数の符号、ファン ON の誤差 4.0℃ 以下、全体 3.0℃ 以下)。NG なら後の実験は回さない
- 確認の基準の決め方:11/25 夜の誤ったパラメータはファン ON の誤差 4.9〜10.4℃(6 台)、直したものは 1.7〜3.3℃(d90 のデータ)

## 結果

(未)
