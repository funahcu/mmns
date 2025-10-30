"""
mmns.py
軽量Mininet風モジュール（import 可能）
- 要求: root 権限で実行する前提
- 提供機能: Node クラス, create_link, cleanup, CLI, mount_override

注意:
- mount_override は "永続的なマウント名前空間プロセス" を起動して
  そのプロセスの mount namespace を以後のコマンド実行に使います。
- そのため mount_override を使う場合は root 権限が必須です。

設計上の簡略化点:
- ip/netns/unshare/nsenter/ mount コマンドを外部コマンドで実行します。

使い方の概略:
>>> import mmns
>>> h1 = mmns.Node('h1')
>>> h2 = mmns.Node('h2')
>>> mmns.create_link(h1,h2)
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

    def add_iface(self) -> str:
        """自動インタフェース名生成: <name>-eth{n} を返す（ただし実体作成は create_link が行う）"""
        iface = f"{self.name}-eth{self.if_count}"
        self.if_count += 1
        self.interfaces.append(iface)
        return iface

    def cmd(self, command: str, timeout: int = None) -> str:
        """ノード内でコマンド実行。mount_override が存在する場合はその mount namespace を共有する。

        戻り値: 標準出力 + 標準エラー (両方) の文字列
        """
        # If a mount namespace helper process is present, use nsenter to enter both mount and net namespaces
        if self.mount_ns_pid:
            cmd = f"nsenter --target {int(self.mount_ns_pid)} --mount --net -- bash -c {shlex.quote(command)}"
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        else:
            # fallback: use ip netns exec for network namespace only
            cmd = f"ip netns exec {shlex.quote(self.name)} bash -c {shlex.quote(command)}"
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        return out

    def cleanup(self):
        """ノード固有の後始末。mount helper プロセスがあれば殺す。"""
        if self.mount_ns_pid:
            try:
                os.kill(int(self.mount_ns_pid), signal.SIGTERM)
            except Exception:
                pass
            self.mount_ns_pid = None
        # delete netns
        try:
            _run(f"ip netns delete {shlex.quote(self.name)}")
        except Exception:
            # might be already deleted
            pass

    def mount_override(self, target_path: str, src_path: str):
        """指定した target_path を src_path で override するための mount namespace helper を起動する。

        - target_path: ノード側の見えるパス（絶対パス推奨）。ファイルまたはディレクトリを指定可能。
        - src_path: ホスト側の実体パス（ファイル または ディレクトリ）

        実装:
        1) ip netns exec <node> unshare --mount bash -c 'mkdir -p $(dirname target); mount --bind src target; exec sleep infinity' &
        2) 起動したプロセス pid を self.mount_ns_pid に保存
        3) 以後の cmd() は nsenter --target <pid> --mount --net で実行され、mount override が見える

        注意:
        - target_path の親ディレクトリが存在しないと失敗するため、mkdir -p を実行している
        - root 権限が必要
        """
        target = target_path
        src = src_path
        # basic checks
        if not os.path.exists(src):
            raise FileNotFoundError(f"src path not found: {src}")
        if not os.path.isabs(target):
            raise ValueError("target_path must be absolute")

        # craft command
        # ensure parent exists inside the namespace by creating it on host if possible
        parent = os.path.dirname(target)
        # We cannot create inside namespace directly; ensure parent exists on host so bind can succeed
        # If parent does not exist on host, create it (this modifies host fs). Alternatively, bind to a temp location.
        if not os.path.exists(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except Exception as e:
                # fallback: raise
                raise

        # Prepare the unshare command executed inside the node's netns. It will create a private mount namespace,
        # perform the bind mount, then sleep forever to keep the mount namespace alive.
        # Use setsid to allow backgrounding independent pid.
        # We use bash -c 'mount --bind ... && exec sleep infinity' so that the process remains and holds mount ns.
        cmd = (
            f"ip netns exec {shlex.quote(self.name)} "
            f"unshare --mount --propagation private bash -c \"mkdir -p {shlex.quote(parent)} && "
            f"mount --bind {shlex.quote(src)} {shlex.quote(target)} && exec sleep infinity\""
        )
        # Start as backgrounded subprocess and record pid
        # We start with Popen so we can get pid
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
        # Give a short time to allow mount to occur or fail
        time.sleep(0.1)
        # check if process is alive and mount succeeded
        if p.poll() is not None:
            # process exited -> error
            out, err = p.communicate()
            raise RuntimeError(f"mount_override helper failed: out={out} err={err}")
        self.mount_ns_pid = p.pid
        # note: keep handle to child by leaving it running; cleanup() will kill it
        return self.mount_ns_pid


# Global nodes registry for convenience
_nodes = {}


def create_link(node1: Node, node2: Node) -> Tuple[str, str]:
    """2ノード間に veth ペアを作成し、それぞれの Node にアタッチして UP にする。

    auto-generated iface names: <node>-ethX
    戻り値: (iface_on_node1, iface_on_node2)
    """
    iface1 = node1.add_iface()
    iface2 = node2.add_iface()
    # create veth
    _run(f"ip link add {shlex.quote(iface1)} type veth peer name {shlex.quote(iface2)}")
    # move to namespaces
    _run(f"ip link set {shlex.quote(iface1)} netns {shlex.quote(node1.name)}")
    _run(f"ip link set {shlex.quote(iface2)} netns {shlex.quote(node2.name)}")
    # bring interfaces up inside each namespace
    node1.cmd(f"ip link set {shlex.quote(iface1)} up")
    node2.cmd(f"ip link set {shlex.quote(iface2)} up")
    return iface1, iface2


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


atexit.register(cleanup)


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
