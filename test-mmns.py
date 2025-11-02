import mmns

h1 = mmns.Node('h1')
h2 = mmns.Node('h2')
mmns.Link(h1, h2)

h1.cmd('ip addr add 10.0.0.1/24 dev h1-eth0')
h2.cmd('ip addr add 10.0.0.2/24 dev h2-eth0')
mmns.CLI({'h1':h1, 'h2':h2})



