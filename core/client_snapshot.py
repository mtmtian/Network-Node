"""Migrate an existing client file into private, client-neutral node state."""
import json
from pathlib import Path
import re

from client_output import atomic_write
from settings import NAME


def load_yaml(path):
    try:
        import yaml
    except ImportError:
        raise ValueError('首次导入需要 PyYAML；使用 uv run --with PyYAML==6.0.2 python aggregate.py import ...') from None
    try:
        value = yaml.safe_load(Path(path).read_text())
    except Exception:
        raise ValueError('无法解析源 YAML（未显示文件内容）') from None
    if not isinstance(value, dict):
        raise ValueError('源 YAML 必须是配置对象')
    return value


def validate_nodes(nodes):
    if not isinstance(nodes, list) or not nodes:
        raise ValueError('节点快照必须为非空列表')
    names = set()
    for node in nodes:
        if not isinstance(node, dict) or node.get('type') not in ('vless', 'hysteria2', 'anytls'):
            raise ValueError('快照仅接受已有 VLESS、HY2、AnyTLS 节点')
        name = node.get('name')
        if not isinstance(name, str) or not name or name in names:
            raise ValueError('节点名称缺失或重复')
        if not isinstance(node.get('server'), str) or not node['server']:
            raise ValueError('节点缺少服务器地址')
        port = node.get('port')
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError('节点端口无效')
        credential = 'uuid' if node['type'] == 'vless' else 'password'
        if not isinstance(node.get(credential), str) or not node[credential]:
            raise ValueError('节点缺少认证字段')
        if node.get('dialer-proxy'):
            raise ValueError('暂不支持带外部 dialer-proxy 引用的快照')
        names.add(name)
    return names


def import_snapshot(root, profile, source):
    if not NAME.fullmatch(profile):
        raise ValueError('汇总 profile 名称无效')
    data = load_yaml(source)
    nodes = data.get('proxies')
    if not isinstance(nodes, list) or data.get('proxy-providers'):
        raise ValueError('只导入完整内嵌节点；不接受外部节点 provider')
    # Store canonical Mihomo credential names. JSON is also YAML-compatible.
    try:
        nodes = json.loads(json.dumps(nodes))
        for node in nodes:
            node.pop('benchmark-url', None)
            node.pop('benchmark-timeout', None)
            if node.get('type') == 'hysteria2':
                for old, new in (('auth', 'password'), ('server-cert-fingerprint', 'fingerprint'),
                                 ('up-speed', 'up'), ('down-speed', 'down')):
                    if old in node:
                        if new in node and node[new] != node[old]:
                            raise ValueError('conflicting fields')
                        node[new] = node.pop(old)
        names = validate_nodes(nodes)
        groups = data.get('proxy-groups', [])
        sensitive = next(g['proxies'] for g in groups if g['name'] == '🛡 敏感服务' and g['type'] == 'fallback')
        if not sensitive or len(set(sensitive)) != len(sensitive) or any(n not in names for n in sensitive):
            raise ValueError('missing sensitive node')
        if any(next(n for n in nodes if n['name'] == name).get('udp') is not True
               or next(n for n in nodes if n['name'] == name)['type'] != 'vless' for name in sensitive):
            raise ValueError('sensitive nodes must support VLESS UDP')
    except Exception:
        raise ValueError('源节点或敏感主备不符合导入契约（未显示内容）') from None
    state = Path(root) / 'profiles' / profile
    if state.is_symlink() or state.exists():
        raise ValueError('目标 profile 已存在；导入不会覆盖现有私有状态')
    state.mkdir(parents=True, mode=0o700)
    try:
        atomic_write(state / 'nodes.json', json.dumps(nodes, ensure_ascii=False, indent=2) + '\n')
        atomic_write(state / 'aggregate.json', json.dumps(
            {'snapshot': 'nodes.json', 'sensitive': sensitive}, ensure_ascii=False, indent=2) + '\n')
    except BaseException:
        # Only remove the fresh files owned by this failed import.
        for name in ('nodes.json', 'aggregate.json'):
            (state / name).unlink(missing_ok=True)
        state.rmdir()
        raise
    print(f'已导入 {len(nodes)} 个节点到私有共享快照；未输出凭据、未改服务器。')
    return 0


def snapshot_nodes(root, profile, target, sensitive):
    path = Path(root) / 'profiles' / profile / 'nodes.json'
    if path.is_symlink():
        raise ValueError('节点快照不能是符号链接')
    try:
        nodes = json.loads(path.read_text())
        names = validate_nodes(nodes)
        by_name = {node['name']: node for node in nodes}
        if any(name not in names or by_name[name].get('udp') is not True
               or by_name[name]['type'] != 'vless' for name in sensitive):
            raise ValueError('missing sensitive node')
    except Exception:
        raise ValueError('节点快照无效或缺少敏感主备（未显示内容）') from None
    rendered = {}
    for node in nodes:
        if target == 'stash':
            node['benchmark-url'] = 'http://www.gstatic.com/generate_204'
            node['benchmark-timeout'] = 5
            if node['type'] == 'hysteria2':
                node['auth'] = node.pop('password')
                if 'fingerprint' in node:
                    node['server-cert-fingerprint'] = node.pop('fingerprint')
                for key in ('up', 'down'):
                    if key in node:
                        match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*([kmg]?bps)?', str(node.pop(key)), re.I)
                        if not match:
                            raise ValueError('HY2 带宽无法转换为 Stash Mbps 数值')
                        unit = (match[2] or 'mbps').lower()
                        node[key + '-speed'] = float(match[1]) * {'bps': .000001, 'kbps': .001, 'mbps': 1, 'gbps': 1000}[unit]
        rendered[node['name']] = '  - ' + json.dumps(node, ensure_ascii=False) + '\n'
    return {'shared': rendered}
