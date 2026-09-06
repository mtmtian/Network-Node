"""GCP IPv4 consistency and recoverable replacement; never display profile values."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from client_output import atomic_write
from settings import load_kv, load_settings
from net_probe import connect


class CloudError(ValueError):
    pass


class Gcp:
    def __init__(self, settings):
        self.s = settings
        for key in ('GCP_ACCOUNT', 'PROJECT_ID', 'ZONE', 'REGION', 'INSTANCE_NAME', 'IP_NAME'):
            if not settings.get(key):
                raise ValueError(f'缺少 {key}')
        if settings['ZONE'].rsplit('-', 1)[0] != settings['REGION']:
            raise ValueError('ZONE 与 REGION 不一致')
        self.env = os.environ.copy()
        if settings.get('GCP_HTTP_PROXY'):
            self.env.update(HTTPS_PROXY=settings['GCP_HTTP_PROXY'], HTTP_PROXY=settings['GCP_HTTP_PROXY'])

    def call(self, *args, read=False):
        command = ['gcloud', '--account', self.s['GCP_ACCOUNT'], '--project',
                   self.s['PROJECT_ID'], '--quiet', *args, '--format=json']
        for attempt in range(3 if read else 1):
            try:
                result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=30 if read else 180)
                if result.returncode == 0:
                    return json.loads(result.stdout or 'null')
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
                pass
            if read and attempt < 2:
                time.sleep(2 ** attempt)
        # CLI diagnostics can contain identifiers or account information.
        raise CloudError('GCP 请求失败或超时；未输出账号、地址或凭据，请检查登录、权限及管理网络')

    def vm(self, optional=False):
        rows = self.call('compute', 'instances', 'list', '--zones', self.s['ZONE'],
                         '--filter', 'name=' + self.s['INSTANCE_NAME'], read=True)
        rows = [row for row in rows if row.get('name') == self.s['INSTANCE_NAME']]
        if not rows and optional:
            return None
        if len(rows) != 1:
            raise ValueError('未找到唯一的目标 VM；已停止操作')
        return rows[0]

    def address(self, name):
        rows = self.call('compute', 'addresses', 'list', '--regions', self.s['REGION'],
                         '--filter', 'name=' + name, read=True)
        rows = [row for row in rows if row.get('name') == name]
        if len(rows) > 1:
            raise ValueError('预留地址不唯一')
        return rows[0] if rows else None

    def idle(self, vm):
        operations = self.call('compute', 'operations', 'list', '--zones', self.s['ZONE'],
                               '--filter', 'status!=DONE', read=True)
        if any(op.get('targetLink') == vm['selfLink'] and op.get('status') != 'DONE' for op in operations):
            raise ValueError('VM 仍有未完成的云端操作；请稍后重试，暂不反向修改地址')


def binding(vm):
    nics = vm.get('networkInterfaces', [])
    if len(nics) != 1:
        raise ValueError('当前工具只支持单网卡 VM；已停止操作')
    configs = nics[0].get('accessConfigs', [])
    if len(configs) > 1:
        raise ValueError('存在多个外部地址配置；已停止操作')
    return nics[0]['name'], configs[0] if configs else None


def verified_address(client, vm, name):
    address = client.address(name)
    _, access = binding(vm)
    if not address or not access or address.get('address') != access.get('natIP'):
        raise ValueError('预留 IP 与 VM 实际绑定不一致；未更新本地地址，请先处理云端绑定')
    if (address.get('status') != 'IN_USE' or vm['selfLink'] not in address.get('users', [])
            or address.get('networkTier') != access.get('networkTier')
            or address.get('networkTier') != client.s.get('NETWORK_TIER', 'PREMIUM')):
        raise ValueError('预留 IP 的归属、使用状态或网络等级不一致')
    return address


def update_kv(path, changes):
    """Preserve comments and unrelated settings, replacing literal assignments atomically."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError('配置文件不能是符号链接')
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [line for line in lines if line.partition('=')[0].strip() not in changes]
    lines += [key + '=' + shlex.quote(value) for key, value in changes.items()]
    atomic_write(path, '\n'.join(lines) + '\n')


def save_binding(state, name, ip):
    update_kv(state / 'deploy.conf', {'IP_NAME': name})
    # A legacy STATIC_IP in deploy.conf would otherwise override generated state.
    if 'STATIC_IP' in load_kv(state / 'deploy.conf'):
        update_kv(state / 'deploy.conf', {'STATIC_IP': ip})
    update_kv(state / '.secrets.env', {'STATIC_IP': ip})


def check(state, *, optional=False, persist=False):
    journal = Path(state) / 'ip-rotation.json'
    if journal.exists() and json.loads(journal.read_text()).get('phase') not in ('complete', 'rolled-back'):
        raise ValueError('存在未完成的换 IP 操作；先运行 ip-rollback，不能继续部署或同步')
    settings = load_settings(state)
    client = Gcp(settings)
    vm = client.vm(optional=optional)
    if vm is None:
        return
    address = verified_address(client, vm, settings['IP_NAME'])
    if persist:
        save_binding(Path(state), settings['IP_NAME'], address['address'])
    elif not optional and settings.get('STATIC_IP') != address['address']:
        raise ValueError('VM 绑定正常，但本地 STATIC_IP 已过期；使用 ip-sync 同步')


def render(state):
    env = os.environ | {'NETWORK_NODE_ROOT': str(ROOT), 'NETWORK_NODE_STATE_DIR': str(state),
                        'NETWORK_NODE_PROFILE': state.name}
    result = subprocess.run([sys.executable, str(ROOT / 'core/gen-clash.py')],
                            env=env, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError('客户端生成失败；原始配置与凭据未输出')


def tcp_probe(ip, port, interface=''):
    for attempt in range(6):
        try:
            with connect(ip, port, 3, interface):
                return
        except OSError:
            if attempt < 5:
                time.sleep(2)
    raise ValueError('从本机到新 IP 的 Reality TCP 端口不可达；尚未验证代理协议')


class Rotation:
    def __init__(self, state, *, client=None, probe=None, renderer=render):
        self.state = Path(state)
        self.s = load_settings(state)
        self.client = client or Gcp(self.s)
        self.probe = probe or (lambda ip, port: tcp_probe(ip, port, self.s.get('PROBE_INTERFACE', '')))
        self.renderer = renderer
        self.path = self.state / 'ip-rotation.json'
        if self.path.is_symlink():
            raise ValueError('恢复记录不能是符号链接')

    def write(self, journal, phase):
        journal['phase'] = phase
        atomic_write(self.path, json.dumps(journal, indent=2) + '\n')

    def journal(self):
        if not self.path.exists():
            raise ValueError('没有待恢复的 IP 操作')
        journal = json.loads(self.path.read_text())
        if journal['identity'] != {k: self.s[k] for k in ('GCP_ACCOUNT', 'PROJECT_ID', 'ZONE', 'INSTANCE_NAME')}:
            raise ValueError('profile 已指向其他账号或 VM，不能使用旧恢复记录')
        return journal

    def switch(self, journal, target):
        vm = self.client.vm()
        if vm.get('id') != journal['vm_id']:
            raise ValueError('VM 已重建，拒绝使用旧恢复记录')
        self.client.idle(vm)
        nic, current = binding(vm)
        if nic != journal['nic']:
            raise ValueError('网卡已改变')
        if current and current.get('natIP') == target['ip']:
            return
        if current and current.get('natIP') not in (journal['old']['ip'], journal['new'].get('ip')):
            raise ValueError('检测到第三方地址变更，已停止覆盖')
        address = self.client.address(target['name'])
        if not address or address.get('address') != target['ip'] or address.get('users'):
            raise ValueError('目标预留地址不存在、已变化或已被占用')
        if current:
            self.client.call('compute', 'instances', 'delete-access-config', self.s['INSTANCE_NAME'],
                             '--zone', self.s['ZONE'], '--network-interface', nic,
                             '--access-config-name', current['name'])
        self.client.call('compute', 'instances', 'add-access-config', self.s['INSTANCE_NAME'],
                         '--zone', self.s['ZONE'], '--network-interface', nic,
                         '--access-config-name', journal['access_name'], '--address', target['ip'],
                         '--network-tier', journal['tier'])

    def commit(self, journal, target):
        address = verified_address(self.client, self.client.vm(), target['name'])
        save_binding(self.state, target['name'], address['address'])
        self.renderer(self.state)

    def rotate(self, apply=False):
        if self.path.exists():
            raise ValueError('已有换 IP 记录；先 ip-rollback 恢复或 ip-finalize 释放保留地址')
        if self.s.get('CDN_ONLY') == 'true' or self.s.get('CLIENT_CONFIG_ENABLE') == 'false':
            raise ValueError('换 IP 工具要求启用直连入口及客户端输出')
        vm = self.client.vm()
        self.client.idle(vm)
        old = verified_address(self.client, vm, self.s['IP_NAME'])
        if vm.get('status') != 'RUNNING':
            raise ValueError('VM 未运行，不能进行连接验收')
        if not apply:
            print('计划：保留旧静态 IP → 申请新 IP → 更换绑定 → TCP 验收 → 同步 YAML；使用 --apply 执行')
            return
        # Ensure client generation works before disconnecting anything.
        if self.s.get('STATIC_IP') != old['address']:
            raise ValueError('本地地址已过期；先 ip-sync，再更换地址')
        self.renderer(self.state)
        nic, access = binding(vm)
        journal = {'identity': {k: self.s[k] for k in ('GCP_ACCOUNT', 'PROJECT_ID', 'ZONE', 'INSTANCE_NAME')},
                   'vm_id': vm['id'], 'nic': nic, 'access_name': access['name'],
                   'tier': access['networkTier'], 'old': {'name': self.s['IP_NAME'], 'ip': old['address']},
                   'new': {'name': 'network-node-' + uuid.uuid4().hex[:20]}}
        self.write(journal, 'allocating')
        try:
            self.client.call('compute', 'addresses', 'create', journal['new']['name'],
                             '--region', self.s['REGION'], '--network-tier', journal['tier'])
            new = self.client.address(journal['new']['name'])
            if not new or new.get('users') or new.get('networkTier') != journal['tier']:
                raise ValueError('新 IP 预留状态异常')
            journal['new']['ip'] = new['address']
            self.write(journal, 'switching')
            self.switch(journal, journal['new'])
            verified_address(self.client, self.client.vm(), journal['new']['name'])
            self.probe(journal['new']['ip'], int(self.s.get('REALITY_PORT', '443')))
            self.write(journal, 'publishing')
            self.commit(journal, journal['new'])
            self.write(journal, 'complete')
        except (ValueError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            try:
                self.rollback(apply=True)
            except (ValueError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
                raise ValueError('换 IP 未完成，自动恢复也未完成；保留了恢复记录，请稍后 ip-rollback --apply') from None
            raise ValueError('换 IP 未完成，已恢复原地址和本地 YAML；保留新预留资源，使用 ip-finalize 清理') from exc
        print('新 IP 绑定、TCP 端口和本地 YAML 已验证；旧 IP 保留待回滚。请同步设备并验证实际代理流量')

    def rollback(self, apply=False):
        journal = self.journal()
        if not apply:
            print('计划：恢复原静态 IP 和 YAML，保留新预留地址；使用 --apply 执行')
            return
        self.write(journal, 'rolling-back')
        self.switch(journal, journal['old'])
        self.commit(journal, journal['old'])
        self.write(journal, 'rolled-back')

    def finalize(self, apply=False):
        journal = self.journal()
        if journal['phase'] not in ('complete', 'rolled-back'):
            raise ValueError('操作未完成；先 ip-rollback 恢复，不能释放地址')
        active, unused = ((journal['new'], journal['old']) if journal['phase'] == 'complete'
                          else (journal['old'], journal['new']))
        vm = self.client.vm()
        if vm.get('id') != journal['vm_id']:
            raise ValueError('VM 已重建，不能使用旧记录释放地址')
        self.client.idle(vm)
        verified_address(self.client, vm, active['name'])
        if self.s.get('IP_NAME') != active['name'] or self.s.get('STATIC_IP') != active['ip']:
            raise ValueError('本地状态与当前绑定不一致；不能释放恢复地址')
        address = self.client.address(unused['name'])
        if address and (address.get('users') or (unused.get('ip') and address['address'] != unused['ip'])):
            raise ValueError('待释放地址已变化或仍被使用，已停止')
        if not apply:
            print('计划：永久释放未使用的保留 IP 并删除恢复记录；设备验证完成后使用 --apply 执行')
            return
        if address:
            self.client.call('compute', 'addresses', 'delete', unused['name'], '--region', self.s['REGION'])
        self.path.unlink()
        print('未使用的保留地址已释放；此次换 IP 不再支持回滚')


if __name__ == '__main__':
    try:
        action, state = sys.argv[1:]
        check(Path(state), optional=action == 'preflight', persist=action == 'persist')
    except (ValueError, OSError) as exc:
        sys.exit(str(exc))
