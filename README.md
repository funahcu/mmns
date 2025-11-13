# minimininetspace (mmns)

mininet-like network environment (IP only)

## How to use it

1. import mmns.py
2. create node by mmns.Node
3. create link by mmns.Link
4. execute command on h1 by h1.cmd('command')
5. use command line interface (cli) by mmns.CLI( dict )  
   you can input commands on h1 by "h1 command" for mmns> prompt

typical code
```python
import mmns

h1 = mmns.Node('h1')
h2 = mmns.Node('h2')
mmns.Link(h1, h2)

h1.cmd('ip addr add 10.0.0.1/24 dev h1-eth0')
h2.cmd('ip addr add 10.0.0.2/24 dev h2-eth0')
mmns.CLI()
```
(included as test-mmns.py)

## Advanced usage 1

Allow created nodes to access the Internet via real NIC

### create nat-enabled bridge

ensure_nat_bridge(bridge_name="bridge_name", subnet="subnet_addr (CIDR notation)", external_if="real_NIC_to_be_connected")

(example)
```python
ensure_nat_bridge(bridge_name="br-nat", subnet="10.0.0.0/24", external_if="eth0")
```

### connect each node to the created bridge

connect_node_to_bridge(node, bridge="bridge_name", subnet="subnet_addr (CIDR notation)", ip_last="last_part_of_IP_address_if_specified")

(example)
```python
connect_node_to_bridge(h1, bridge="br-nat", subnet="10.10.0.0/24", ip_last=None)
```

## Advanced Usage 2

Mount specified file/directory on specified path in virtual node

Node.mount_override(target_path="target_path_on_node", src_path="real_path_on_host_os")

(example)
```python
h1.mount_override('/tmp', os.path.abspath('tmp_h1'))

```
Now, we have assigned different /tmp for virtual node h1

