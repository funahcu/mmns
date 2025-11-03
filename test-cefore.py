import mmns
import os

h1 = mmns.Node('h1')
h2 = mmns.Node('h2')
mmns.Link(h1, h2)

h1.mount_override('/tmp', os.path.abspath('tmp_h1'))
h2.mount_override('/tmp', os.path.abspath('tmp_h2'))

h1.cmd('ip addr add 10.0.0.1/24 dev h1-eth0')
h2.cmd('ip addr add 10.0.0.2/24 dev h2-eth0')

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


