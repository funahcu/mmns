import mmns

mmns.ensure_nat_bridge("br-nat", "10.0.0.0/24", "eth0")

h1 = mmns.Node('h1')
h2 = mmns.Node('h2')

mmns.connect_node_to_bridge(node=h1, bridge="br-nat", subnet="10.0.0.0/24")
mmns.connect_node_to_bridge(node=h2, bridge="br-nat", subnet="10.0.0.0/24")

#mmns.Link(h1, h2)
## インタフェースを有効化
#for n in (h1, h2):
#    n.cmd("ip link set lo up")
#    for iface in n.interfaces:
#        n.cmd(f"ip link set {iface} up")

#h1.cmd('ip addr add 10.0.0.1/24 dev h1-eth0')
#h2.cmd('ip addr add 10.0.0.2/24 dev h2-eth0')
mmns.CLI({'h1':h1, 'h2':h2})



