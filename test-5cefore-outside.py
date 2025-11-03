import mmns
import os

mmns.ensure_nat_bridge("br-nat", "10.0.0.0/24", "eth0")

n_node = 5
node_list = []
node_dict = {}
for n in range(1, n_node+1):
    node_name = 'h' + str(n)
    node_list.append(mmns.Node(node_name))
    mmns.connect_node_to_bridge(node=node_list[-1], bridge="br-nat", subnet="10.0.0.0/24")
    tmp_dir = 'tmp_' + node_name
    os.makedirs(tmp_dir, exist_ok=True)
    node_list[-1].mount_override('/tmp', os.path.abspath(tmp_dir))
    node_dict[node_name] = node_list[-1]

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

