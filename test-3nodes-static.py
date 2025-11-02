#!/usr/bin/env python3
from mmns import Node, Link, CLI, cleanup

# クリーンアップしてから開始
cleanup()

# ノードを定義
h1 = Node("h1")
r1 = Node("r1")
h2 = Node("h2")

# リンクを作成
Link(h1, r1)
Link(r1, h2)

# 各ノードのインタフェース設定
h1.cmd("ip addr add 10.0.1.1/24 dev h1-eth0")
r1.cmd("ip addr add 10.0.1.254/24 dev r1-eth0")
r1.cmd("ip addr add 10.0.2.254/24 dev r1-eth1")
h2.cmd("ip addr add 10.0.2.1/24 dev h2-eth0")

# インタフェースを有効化
#for n in (h1, r1, h2):
#    n.cmd("ip link set lo up")
#    for iface in n.interfaces:
#        n.cmd(f"ip link set {iface} up")

# ルーティング設定
h1.cmd("ip route add default via 10.0.1.254")
h2.cmd("ip route add default via 10.0.2.254")

# r1でIPv4フォワーディングを有効化
r1.cmd("sysctl -w net.ipv4.ip_forward=1")

print("\n=== Network setup complete ===")
print("Try: h1 ping -c 2 10.0.2.1\n")

# CLIを起動
CLI({"h1": h1, "r1": r1, "h2": h2})

## 終了処理
#cleanup()
