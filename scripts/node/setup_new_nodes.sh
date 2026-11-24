#!/usr/bin/env bash
# 新しいノード(raspi4〜8 など)を一度だけ準備する。Mac のターミナルでレオが実行する(パスワード入力が要るため)。
#
#   bash scripts/node/setup_new_nodes.sh 54 55 56 57 58
#
# ノードごとに、ubuntu のパスワードを 2 回聞かれる(1 回目 = 鍵の登録、2 回目 = sudo)。
# やること:Mac の SSH 鍵を登録 → node_agent.py と install_node.sh をコピー → install_node.sh を sudo で実行
# (paho-mqtt と stress-ng を入れる、etc-agent サービスを作る。詳しくは install_node.sh の先頭)
set -u
cd "$(dirname "$0")"
for n in "$@"; do
  h=ubuntu@192.168.0.$n
  echo "===== 192.168.0.$n ====="
  ssh-copy-id -o StrictHostKeyChecking=accept-new "$h" || { echo "鍵の登録に失敗($n)、次へ"; continue; }
  scp -q node_agent.py install_node.sh "$h":~/ || { echo "コピーに失敗($n)、次へ"; continue; }
  ssh -t "$h" 'sudo bash ~/install_node.sh && echo "OK: $(hostname)"' || echo "インストールに失敗($n)"
done
echo "終わったら Claude に「終わった」と伝える(PC からの鍵の登録と動作確認は Claude がやる)"
