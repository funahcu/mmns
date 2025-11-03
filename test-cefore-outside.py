import mmns
import os

mmns.ensure_nat_bridge("br-nat", "10.0.0.0/24", "eth0")

h1 = mmns.Node('h1')
h2 = mmns.Node('h2')

mmns.connect_node_to_bridge(node=h1, bridge="br-nat", subnet="10.0.0.0/24")
mmns.connect_node_to_bridge(node=h2, bridge="br-nat", subnet="10.0.0.0/24")

h1.mount_override('/tmp', os.path.abspath('tmp_h1'))
h2.mount_override('/tmp', os.path.abspath('tmp_h2'))

node_dict = {'h1':h1, 'h2':h2}

for n in node_dict:
    print(f"{n} starting cefnetd")
    node = node_dict[n]
    node.cmd('cefnetdstop')
    node.cmd('cefnetdstart > /dev/null 2>&1', timeout=5)

mmns.CLI(node_dict)

for n in node_dict:
    print(f"{n} finishing cefnetd")
    node = node_dict[n]
    node.cmd('cefnetdstop')

