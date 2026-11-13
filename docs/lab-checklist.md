# レオの作業チェックリスト(実機・事務)

タスク表 [tasks.md](tasks.md) の E・C・F のうち、本人が手を動かすものを手順に落としたもの。終わったら tasks.md の該当タスクを `[x]` に。
困ったら、出たエラーや画面をそのまま Claude に貼る。

## 11/13(金)

### 1. 3台を決めて配置を固定する(30分)【C3】

- [ ] 実験に使う3台を決める:A(負荷をかける)、B(A のすぐ隣)、C(A から一番離れた位置)。ホスト名をメモ
- [ ] 筐体の状態を決める(密閉のまま / 吸気口を開ける)。以後の実験は全部これで固定
- [ ] A–B、A–C の距離を測り、全体と各ノードの写真を撮る(論文の実験環境の図に使う)
- [ ] 同じ筐体にいる他のノードは電源を切るか、アイドルのまま動かさないかを決める(条件を毎回同じにするため)

### 2. ファンについて(配線は不要)

ファンは PoE+ HAT 付属のもの。Linux から制御できるので配線しない(GPIO14 の公式ケースファンではなかった)。詳しくは `scripts/node/README.md`。

- [ ] **給電を PoE に統一**:2026-11-13 の確認で raspi2 だけ PoE 電流が 0(USB-C 給電の可能性)。USB-C はコイル鳴き(蝉のような音)がするので PoE にそろえる
- [ ] 3台とも HAT を付けたまま、ファンの向きも同じ(全条件で HAT ありに統一)

### 3. 各 RasPi のセットアップ(1台5分、sudo パスワードを1回入れる)【C4】

ファイルは Claude Code がコピー済み。Mac のターミナルで:

```sh
ssh -t ubuntu@raspi1 'sudo bash ~/install_node.sh'
ssh -t ubuntu@raspi2 'sudo bash ~/install_node.sh'
ssh -t ubuntu@raspi3 'sudo bash ~/install_node.sh'
```

最後に `OK:` と出れば完了。以後のファン操作・CPU ガバナの切り替えは、サービスの起動・停止で自動的に行われる。

### 4. 収集用 PC に Claude が入れるようにする(1分)

```sh
ssh-copy-id laur@192.168.0.50
```

入れるようになれば、PC の準備(5)と旧収集スクリプトの確認は Claude Code がやる(sudo が要るところだけ頼む)。

### 5. 収集用 Linux PC の準備(30分)【A6】

```sh
sudo apt install -y mosquitto mosquitto-clients python3-paho-mqtt
# mosquitto 2.x は初期状態だと自分自身からしか接続できないので、LAN から受け付ける設定を足す
echo -e "listener 1883\nallow_anonymous true" | sudo tee /etc/mosquitto/conf.d/lan.conf
sudo systemctl restart mosquitto
ip addr                                  # PC の IP アドレスをメモ
git clone https://github.com/Laur3121/edge-thermal-control.git   # まだなら
```

- [ ] 旧収集スクリプトが PC にあれば、場所をメモする(ブローカーのアドレスとトピック名を合わせるため)

疎通確認:

```sh
# PC
python3 scripts/collector.py --broker localhost --out experiments/test_collector
# 各 RasPi
python3 node_agent.py --broker <PCのIP>
# PC の別端末からファンを切り替えてみる
mosquitto_pub -h localhost -t etc/<Aのホスト名>/fan/set -m 1
mosquitto_pub -h localhost -t etc/<Aのホスト名>/fan/set -m 0
```

- [ ] collector の画面に3台とも `last seen 0〜1s` と出る
- [ ] ファンが指令どおりに回る・止まる(HAT のファン)
- [ ] 確認が済んだら、指令を止めて10秒後にファンが強制 ON になる(安全機能)ことも見ておく

### 6. SwitchBot 温湿度計(設置10分 + 放置1時間)【E3】

- [ ] アプリで、温湿度計2台の「クラウドサービス」を ON(Hub 経由で API から読めるようにする)
- [ ] トークンとシークレットを取得:アプリの プロフィール → 設定 → アプリバージョンを10回タップ → 開発者向けオプション
  - **チャットやリポジトリには貼らない。** PC の `edge-thermal-control/.env` に `SWITCHBOT_TOKEN=...` と `SWITCHBOT_SECRET=...` の2行で保存する(.env は git に入らない設定済み)
- [ ] 2台を並べて1時間置く(個体差の確認。取得スクリプトは Claude が用意する)
- [ ] その後、1台は筐体から離れた場所(室温)、1台は筐体の吸気口付近に設置して写真を撮る

### 7. 先生への連絡(15分)【F5】

伝えること:

1. IPSJ 時のカルマンフィルタのコードが残っておらず、予稿の式どおりに再実装したこと
2. 旧データは CPU 使用率の記録方法に問題があり、パラメータを同定できなかったため、実験をやり直すこと
3. 特研IIではファン(公式ケースファンを GPIO で ON/OFF)を操作量にして、予測と動的マージンで必要なときだけ回す制御を加えること
4. 予備審査(11/27)では1〜5章と予備的な実験結果を出し、ファン制御の本実験は12月に行う予定であること

文面が必要なら Claude に頼む。

### 8. 予備審査の形式とテンプレート(15分)【F2】

先生か先輩に聞くこと:

- [ ] 発表時間と質疑の時間
- [ ] アブストの書式(ページ数、テンプレート)
- [ ] 予備審査で出す論文のページ数の目安
- [ ] 研究室の LaTeX テンプレート(.cls / .tex)。もらえたら `thesis/` に置く

## 11/14(土)

### 9・10. 同定用ステップ実験(ファンの応答時間を含む。約3時間、見ているだけ)【E2・B1・B2・B3】

負荷とファンの切り替えはスクリプトが自動でやる。前日の 1〜5 が済んでいることが前提。

```sh
# 各 RasPi で node_agent を起動しておく(3台とも)
python3 node_agent.py --broker <PCのIP>

# PC で:まず段階の一覧を確認(何も動かない)
python3 scripts/run_experiment.py --scenario scripts/scenarios/step_identify.json \
    --nodes A=<Aのホスト名> B=<Bのホスト名> C=<Cのホスト名> --out experiments/20261114_step_identify --dry-run
# 本番(--dry-run を外す)。collector も自動で起動する
python3 scripts/run_experiment.py --scenario scripts/scenarios/step_identify.json \
    --nodes A=<Aのホスト名> B=<Bのホスト名> C=<Cのホスト名> --out experiments/20261114_step_identify
```

中身(全部 A にだけ負荷。B・C はアイドル・ファン OFF):

1. 開始前に3台の温度が落ち着くまで自動で待つ(最大30分)
2. part1:ファンの効果と応答時間。A を 75℃ まで温め、ファン ON 5分 / OFF(75℃ に戻るまで)を3回
3. part2:A のファン ON のまま、負荷 2コア 15分 → 休み 10分 → 1コア 15分 → 休み 10分(自己発熱と、B・C への干渉)
4. part3:ファン OFF で、76℃ までの短い負荷パルスを3回

やること:

- [ ] 開始時と終了時に室温をメモ(SwitchBot の値)
- [ ] 実験中は部屋の窓・エアコン・人の出入りをなるべく変えない
- [ ] 終わったら `experiments/20261114_step_identify/README.md`(自動で雛形ができる)の「条件」を埋める
- [ ] 中断したいときは Ctrl-C(負荷とファンは自動で止まる)。やり直すときは `--out` を別の名前に(生ログは上書きしない)
- [ ] commit して push。解析は Claude がやる
