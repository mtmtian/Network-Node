#!/usr/bin/env python3
"""Publish verified Mihomo output; subscription tokens remain in macOS Keychain."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
CLOUD = ROOT / 'cloud/subscription'
WRANGLER = CLOUD / 'node_modules/wrangler/bin/wrangler.js'
SERVICE = 'Network-Node subscriptions'
from core.settings import NAME, load_settings


class PublishError(ValueError):
    """Messages in this exception are explicitly safe to show."""


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode:
        raise PublishError('外部命令失败；已隐藏可能包含凭据的输出')
    return result.stdout


def settings():
    if not (CLOUD / 'wrangler.jsonc').is_file() or not (CLOUD / 'endpoint.json').is_file():
        raise PublishError('请先复制 cloud/subscription 中的 example 配置并填写自己的账户、KV 和发布地址')
    data = json.loads((CLOUD / 'wrangler.jsonc').read_text())
    state = json.loads((CLOUD / 'endpoint.json').read_text())
    base = state['base_url']
    if not re.fullmatch(r'https://[a-z0-9-]+\.[a-z0-9-]+\.workers\.dev', base):
        raise PublishError('订阅地址必须是已确认的 HTTPS workers.dev 地址')
    return data, base


def keychain_token(account, *, create=False):
    result = subprocess.run(['security', 'find-generic-password', '-s', SERVICE,
                             '-a', account, '-w'], capture_output=True, text=True)
    if result.returncode == 0:
        token = result.stdout.strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise PublishError('钥匙串中的订阅令牌格式不正确')
        return token
    if not create or result.returncode != 44:
        raise PublishError('无法读取订阅令牌；请检查钥匙串访问权限或先运行 set-token')
    token = secrets.token_urlsafe(32)
    # Interactive input avoids placing the token in process arguments or files.
    instruction = f'add-generic-password -s "{SERVICE}" -a "{account}" -w "{token}"\n'
    run(['security', '-i'], input=instruction, text=True)
    if keychain_token(account) != token:
        raise PublishError('钥匙串令牌写入后校验失败')
    return token


def auth_token():
    raw = run(['node', str(WRANGLER), 'auth', 'token', '--json'], text=True,
              cwd=CLOUD, env=os.environ | {'WRANGLER_SEND_METRICS': 'false'})
    data = json.loads(raw)
    token = data.get('token')
    if not isinstance(token, str) or not token:
        raise PublishError('Wrangler 登录状态无效')
    return token


class Cloudflare:
    def __init__(self, token):
        self.token = token

    def request(self, path, *, method='GET', content=None, raw=False):
        request = urllib.request.Request('https://api.cloudflare.com/client/v4/' + path,
            method=method, data=content,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/octet-stream'})
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise PublishError(f'Cloudflare 操作失败（HTTP {code}）；响应内容已隐藏') from None
        if raw:
            return body
        result = json.loads(body)
        if not result.get('success'):
            raise PublishError('Cloudflare 未确认操作成功；响应内容已隐藏')
        return result.get('result')


def verified_file(profile, server=None):
    if not NAME.fullmatch(profile):
        raise PublishError('profile 名称无效')
    state = ROOT / 'profiles' / profile
    aggregate = (state / 'aggregate.json').is_file()
    cli = 'aggregate.py' if aggregate else 'node.py'
    prefix = output_name(profile, server)
    if not aggregate:
        config = load_settings(state)
        if config.get('CLIENT_CONFIG_ENABLE', 'true') == 'false':
            raise PublishError('已停用的 profile 不能发布旧配置')
        if server is not None:
            raise PublishError('--server 仅适用于汇总 profile')
        prefix = config.get('CLIENT_FILE_PREFIX', '').strip() or profile
        if not NAME.fullmatch(prefix):
            raise PublishError('CLIENT_FILE_PREFIX 无效')
    # Compare the exact bytes before and after source validation to detect a
    # concurrent render. Publish this snapshot, never re-read after validation.
    source = ROOT / 'clash-configs/mihomo' / (prefix + '.yaml')
    if source.is_symlink() or not source.is_file():
        raise PublishError('共享 Mihomo 成品不存在或是符号链接')
    manifest = source.parent / '.network-node-outputs.json'
    owners = json.loads(manifest.read_text())
    if source.name not in owners.get(profile, {}):
        raise PublishError('成品归属与当前 profile 不一致；请先 render')
    before = source.read_bytes()
    run([sys.executable, str(ROOT / cli), 'check', '--profile', profile, '--client', 'mihomo'])
    if source.read_bytes() != before:
        raise PublishError('校验期间成品改变；重新运行 publish')
    if len(before) > 1024 * 1024 or b'\nproxies:\n' not in before or b'\nrules:\n' not in before:
        raise PublishError('成品不符合发布限制')
    return before


def output_name(profile, server=None):
    if not NAME.fullmatch(profile) or (server is not None and not NAME.fullmatch(server)):
        raise PublishError('profile/server 名称无效')
    name = profile if server is None else profile + '-' + server
    if not NAME.fullmatch(name):
        raise PublishError('订阅名称超过长度限制')
    return name


def subscription_url(base, profile, token):
    if not NAME.fullmatch(profile):
        raise PublishError('profile 名称无效')
    return f'{base}/mihomo/{profile}.yaml?token={token}'


def fetch_subscription(url):
    # Do not follow redirects with a bearer URL. A redirect is a deployment error.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'clash-verge/2.5.5'})
        with urllib.request.build_opener(NoRedirect).open(request, timeout=35) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        return code, b'', {}
    except urllib.error.URLError:
        raise PublishError('订阅地址连接失败；URL 与令牌未输出') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('set-token', 'publish', 'verify', 'copy-link', 'import'))
    parser.add_argument('--profile', default='routing')
    parser.add_argument('--server', help='从主配置派生的单服务器别名')
    args = parser.parse_args()
    config, base = settings()
    account = config['account_id']
    if not re.fullmatch(r'[a-f0-9]{32}', account):
        raise PublishError('Cloudflare account_id 无效')
    token = keychain_token(account, create=args.action == 'set-token')
    if args.action == 'set-token':
        digest = hashlib.sha256(token.encode()).hexdigest()
        run(['node', str(WRANGLER), 'secret', 'put', 'TOKEN_SHA256'],
            input=digest + '\n', text=True, cwd=CLOUD,
            env=os.environ | {'WRANGLER_SEND_METRICS': 'false'})
        print('订阅令牌已保存到钥匙串，云端只保存 SHA256 校验值；未输出令牌。')
        return
    name = output_name(args.profile, args.server)
    url = subscription_url(base, name, token)
    if args.action == 'copy-link':
        run(['pbcopy'], input=url.encode())
        print('私有订阅链接已复制到剪贴板；请在 Verge 中导入 URL。')
        return
    if args.action == 'import':
        link = 'clash-verge://install-config?' + urllib.parse.urlencode({'url': url})
        # Send the private URI via stdin, never a process argument or file.
        script = 'ObjC.import("AppKit"); if (!$.NSWorkspace.sharedWorkspace.openURL($.NSURL.URLWithString(' + json.dumps(link) + '))) throw new Error("Verge URL handler unavailable");'
        run(['osascript', '-l', 'JavaScript', '-'], input=script, text=True)
        print('已向 Clash Verge 发送导入请求；请在客户端检查下载结果。')
        return
    content = verified_file(args.profile, args.server)
    if args.action == 'publish':
        namespace = next(item['id'] for item in config['kv_namespaces'] if item['binding'] == 'CONFIGS')
        if not re.fullmatch(r'[a-f0-9]{32}', namespace):
            raise PublishError('KV namespace id 无效')
        key = urllib.parse.quote('mihomo/' + name + '.yaml', safe='')
        path = f'accounts/{account}/storage/kv/namespaces/{namespace}/values/{key}'
        cf = Cloudflare(auth_token())
        cf.request(path, method='PUT', content=content)
        if cf.request(path, raw=True) != content:
            raise PublishError('KV 发布读回不一致；未确认端点生效')
        print('KV 发布并读回一致；正在核对 HTTPS 端点。')
    status, remote, headers = fetch_subscription(url)
    if status not in (200, 404):
        raise PublishError(f'订阅 HTTP {status}；尚未验证线上可用，请排查网络或 Cloudflare 边缘策略')
    if status != 200 or remote != content:
        raise PublishError('端点尚未返回当前版本（KV 跨区域同步可能延迟）；稍后运行 verify，不要重复写入')
    for candidate in (base + '/mihomo/' + name + '.yaml', subscription_url(base, name, 'A' * 43)):
        if fetch_subscription(candidate)[0] != 404:
            raise PublishError('端点未通过未授权访问检查')
    print(f'{name}: HTTPS 读回一致，缺少/错误令牌均拒绝；{len(content)} bytes。')


if __name__ == '__main__':
    try:
        main()
    except PublishError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError, KeyError, StopIteration, subprocess.SubprocessError):
        # Never dump exceptions/tracebacks containing remote URLs, bodies or tokens.
        print('操作未完成；请检查登录、钥匙串、源配置是否过期，或等待 KV 同步后运行 verify。', file=sys.stderr)
        sys.exit(1)
