"""
mmns.py
軽量Mininet風モジュール（import 可能）
- 要求: root 権限で実行する前提
- 提供機能: Node クラス, Link クラス, cleanup, CLI, mount_override, ensure_nat_bridge, connect_node_to_bridge

注意:
- mount_override は "永続的なマウント名前空間プロセス" を起動して
  そのプロセスの mount namespace を以後のコマンド実行に使います。

設計上の簡略化点:
- ip/netns/unshare/nsenter/ mount コマンドを外部コマンドで実行します。

使い方の概略:
>>> import mmns
>>> h1 = mmns.Node('h1')
>>> h2 = mmns.Node('h2')
>>> mmns.Link(h1,h2)
>>> h1.cmd('ip addr add 10.0.0.1/24 dev h1-eth0')
>>> h2.cmd('ip addr add 10.0.0.2/24 dev h2-eth0')
>>> mmns.CLI({'h1':h1,'h2':h2})
>>> # ファイル単位のオーバーライド
>>> h1.mount_override('/usr/local/cefore/cefnetd.conf','/var/tmp/mmns/node1/cefnetd.conf')

"""

import subprocess
import atexit
import os
import shlex
import signal
import time
import ipaddress
from typing import Dict, Tuple


def _run(cmd, check=True, capture_output=False, text=True):
    # helper wrapper
    # print for debugging
    print(f"[run] {cmd}")
    return subprocess.run(cmd, shell=True, check=check, capture_output=capture_output, text=text)


class Node:
    """簡易 Node クラス
    - name: ノード名
    - interfaces: 生成したインタフェース名のリスト
    - if_count: 次のeth番号
    - mount_ns_pid: mount namespace を維持するためのプロセス pid（存在すればそれを使って nsenter で実行）
    """

    def __init__(self, name: str):
        self.name = name
        self.interfaces = []
        self.if_count = 0
        self.mount_ns_pid = None

        # create netns
        _run(f"ip netns add {shlex.quote(self.name)}")

        # bring up loopback
        _run(f"ip netns exec {shlex.quote(self.name)} ip link set lo up")

    def add_iface(self, ifname=None):
        """インタフェース名を登録して返す"""
        if ifname is None:
            ifname = f"{self.name}-eth{len(self.interfaces)}"
        self.interfaces.append(ifname)
        _run(f"ip -n {self.name} link set {ifname} up")
        return ifname

    def cleanup(self):
        """ノード固有の後始末。mount helper プロセスがあれば殺す。"""
        if self.mount_ns_pid:
            try:
                os.kill(int(self.mount_ns_pid), signal.SIGTERM)
            except Exception:
                pass
            self.mount_ns_pid = None

    def mount_override(self, target_path: str, src_path: str):
        """指定した target_path を src_path で override する mount namespace helper"""

        if not os.path.exists(src_path):
            raise FileNotFoundError(f"src path not found: {src_path}")
        if not os.path.isabs(target_path):
            raise ValueError("target_path must be absolute")
        if not os.path.isabs(src_path):
            raise ValueError("src_path must be absolute")

        # 既存のhelperがあればクリーンアップ
        if self.mount_ns_pid:
            try:
                os.kill(int(self.mount_ns_pid), signal.SIGTERM)
                time.sleep(0.1)
            except Exception:
                pass

        parent = os.path.dirname(target_path)
        is_file = os.path.isfile(src_path)

        # マウント名前空間の影響を受けない場所を使う
        pid_dir = "/run/mmns"
        os.makedirs(pid_dir, exist_ok=True)
        pid_file = f"{pid_dir}/helper_{self.name}.pid"
        log_file = f"{pid_dir}/helper_{self.name}.log"

        # 準備コマンド
        if is_file:
            prep_cmd = f"mkdir -p {shlex.quote(parent)} && touch {shlex.quote(target_path)}"
        else:
            prep_cmd = f"mkdir -p {shlex.quote(target_path)}"

        inner_script = (
            f'{prep_cmd} && '
            f'mount --bind {shlex.quote(src_path)} {shlex.quote(target_path)} && '
            f'echo $$ > {pid_file} && '
            f'exec sleep infinity'
        )

        cmd = [
            'ip', 'netns', 'exec', self.name,
            'unshare', '--mount', '--propagation', 'private',
            'bash', '-c', inner_script
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=open(log_file, 'w'),
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid
        )

        # PIDファイルを待つ
        for i in range(30):
            time.sleep(0.1)
            if os.path.exists(pid_file):
                break
            if proc.poll() is not None:
                with open(log_file, 'r') as f:
                    raise RuntimeError(f"mount_override failed: {f.read()}")
        else:
            proc.terminate()
            with open(log_file, 'r') as f:
                raise RuntimeError(f"mount_override timeout: {f.read()}")

        with open(pid_file, 'r') as f:
            helper_pid = int(f.read().strip())

        os.unlink(pid_file)

        self.mount_ns_pid = helper_pid
        return helper_pid

    def cmd(self, command: str, timeout: int = None) -> str:
        """ノード内でコマンド実行。mount_override が存在する場合はその mount namespace を共有する。"""

        if self.mount_ns_pid:
            # mount helperプロセスが生きているか確認
            try:
                os.kill(int(self.mount_ns_pid), 0)  # signal 0 = 生存確認
            except (OSError, ProcessLookupError):
                print(f"[warn] mount helper process {self.mount_ns_pid} is dead, falling back to netns exec")
                self.mount_ns_pid = None

            # デバッグ：helperプロセスがどのnetnsにいるか確認
            netns_check = subprocess.run(
                f"ip netns identify {int(self.mount_ns_pid)}",
                shell=True, capture_output=True, text=True
            )
            helper_netns = netns_check.stdout.strip()
#            print(f"[debug] Helper PID {self.mount_ns_pid} is in netns: '{helper_netns}' (expected: '{self.name}')")

            if self.mount_ns_pid:
                # mount namespaceとnetwork namespaceの両方に入る
                cmd = f"nsenter --target {int(self.mount_ns_pid)} --mount --net bash -c {shlex.quote(command)}"
                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
                out = (proc.stdout or "") + (proc.stderr or "")
                return out

        # fallback: network namespaceのみ
        cmd = f"ip netns exec {shlex.quote(self.name)} bash -c {shlex.quote(command)}"
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        return out

# Global nodes registry for convenience
_nodes = {}


class Link:
    def __init__(self, node1, node2, if1_name=None, if2_name=None):
        if1 = if1_name or f"{node1.name}-eth{len(node1.interfaces)}"
        if2 = if2_name or f"{node2.name}-eth{len(node2.interfaces)}"

        _run(f"ip link add {if1} type veth peer name {if2}")
        _run(f"ip link set {if1} netns {node1.name}")
        _run(f"ip link set {if2} netns {node2.name}")

        node1.add_iface(if1)
        node2.add_iface(if2)

    def delete(self):
        # 明示的に削除する
        _run(f"ip -n {self.node1} link del {self.if1}")

    def __del__(self):
        # オブジェクト破棄時にも安全に削除
        try:
            self.delete()
        except Exception:
            pass

def ensure_nat_bridge(bridge_name="br-nat", subnet="10.10.0.0/24", external_if="eth0"):
    """Dockerのbridgeネットワーク相当を構築"""
    # すでに存在する場合は何もしない
    existing = _run(f"ip link show {bridge_name}", capture_output=True, check=False)
    existing_out = existing.stdout if existing.stdout else ""
    if "does not exist" not in existing_out and existing_out:
        print(f"[bridge] Using existing {bridge_name}")
        return

    net = ipaddress.ip_network(subnet, strict=False)
    bridge_addr = f"{net.network_address + 1}/{net.prefixlen}"

    print(f"[bridge] Creating NAT bridge {bridge_name}")
    _run(f"ip link add name {bridge_name} type bridge", check=False)
    _run(f"ip addr add {bridge_addr} dev {bridge_name}", check=False)
    _run(f"ip link set {bridge_name} up")

    # IP転送を有効化
    _run("sysctl -w net.ipv4.ip_forward=1")

    # NAT設定（重複を避けるため既存ルールチェック）
    rule_result = _run("iptables -t nat -S POSTROUTING", capture_output=True)
    rule_check = rule_result.stdout if rule_result.stdout else ""
    rule = f"-A POSTROUTING -s {subnet} -o {external_if} -j MASQUERADE"
    if rule not in rule_check:
        _run(f"iptables -t nat {rule}")
        print(f"[iptables] Added NAT rule for {subnet} via {external_if}")
    else:
        print("[iptables] NAT rule already present")

_bridge_ip_alloc = {}

def connect_node_to_bridge(node, bridge="br-nat", subnet="10.10.0.0/24", ip_last=None):
    """ノードをbridgeに接続してNAT経由で外部通信可能にする"""
    net = ipaddress.ip_network(subnet, strict=False)
    base = str(net.network_address).rsplit(".", 1)[0] + "."

    if bridge not in _bridge_ip_alloc:
        _bridge_ip_alloc[bridge] = 2

    if ip_last is None:
        ip_last = _bridge_ip_alloc[bridge]
        _bridge_ip_alloc[bridge] += 1

    iface = f"{node.name}-eth{len(node.interfaces)}"
    _run(f"ip link add {iface} type veth peer name {iface}-br")
    _run(f"ip link set {iface} netns {node.name}")
    _run(f"ip link set {iface}-br master {bridge}")
    _run(f"ip link set {iface}-br up")

    ip_addr = f"{base}{ip_last}/{net.prefixlen}"
    gw_addr = f"{base}1"

    node.add_iface(iface)
#    _run(f"ip -n {node.name} link set {iface} up")
    _run(f"ip -n {node.name} addr add {ip_addr} dev {iface}")
    _run(f"ip -n {node.name} route add default via {gw_addr}")

def bridge_exists(bridge_name: str) -> bool:
    """Check if a given bridge device exists."""
    result = subprocess.run(
        ["ip", "link", "show", bridge_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return result.returncode == 0

def cleanup():
    """全ノードの cleanup を呼び出してから、残った netns を削除する。
    また mount helper プロセスも terminate する。
    """
    # kill mount helper processes and delete netns for known nodes
    for n in list(_nodes.values()):
        try:
            n.cleanup()
        except Exception:
            pass
    # try to delete any remaining namespaces
    try:
        _run("ip -all netns delete")
    except Exception:
        pass
    # best-effort: remove veths that remain whose names match pattern *_eth*
    try:
        res = subprocess.run("ip -o link show", shell=True, capture_output=True, text=True)
        for line in (res.stdout or "").splitlines():
            parts = line.split(':', 2)
            if len(parts) >= 2:
                name = parts[1].strip().split('@', 1)[0]
#                if '-eth' in name or name.endswith('eth0'):
                if name.startwith("veth") or "-" in name:
                    try:
                        _run(f"ip link delete {shlex.quote(name)}")
                    except Exception:
                        pass
    except Exception:
        pass

    print("[cleanup] Deleting bridge br-nat if exists...")
    if bridge_exists("br-nat"):
        try:
            delete_bridge("br-nat")
        except Exception as e:
            print(f"[cleanup] Warning: failed to delete bridge br-nat: {e}")


atexit.register(cleanup)

def delete_bridge(bridge_name):
    print(f"[cleanup] Deleting bridge {bridge_name}")
    _run(f"ip link set {bridge_name} down", check=False)
    _run(f"ip link delete {bridge_name} type bridge", check=False)


def CLI(nodes: Dict[str, Node]):
    """簡易 CLI。nodes は名前->Node オブジェクトの辞書。

    コマンド形式:
      <node> <command...>
    例:
      h1 ip addr
      h2 ping -c1 10.0.0.1
      all uname -a    # 全ノードで実行
      exit
    """
    print("Entering mini CLI. Type 'exit' to quit.")
    # register nodes in global
    _nodes.update(nodes)
    try:
        while True:
            try:
                line = input('mmns> ').strip()
            except EOFError:
                break
            if not line:
                continue
            if line in ('exit', 'quit'):
                break
            parts = line.split(maxsplit=1)
            if len(parts) == 1:
                print("Usage: <node|all> <command>")
                continue
            target, cmd = parts
            if target == 'all':
                for n in nodes.values():
                    out = n.cmd(cmd)
                    if out:
                        print(f"[{n.name}] {out}")
            else:
                if target not in nodes:
                    print(f"Unknown node: {target}")
                    continue
                out = nodes[target].cmd(cmd)
                if out:
                    print(out)
    finally:
        print("Exiting CLI...")
