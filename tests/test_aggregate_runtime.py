"""Real Mihomo routing against loopback origins; no TUN/system proxy changes.

Acceptance: sensitive domains beat ordinary/CN membership, CN and LAN go
DIRECT; only explicit ordinary services use AUTO; unknown domains stay sensitive.
External nodes and downloaded rule sets are replaced by deterministic fixtures.
"""
import http.client
import http.server
import json
import os
from pathlib import Path
import selectors
import shutil
import socket
import socketserver
import subprocess
import threading
import time
import unittest

import test_aggregate as fixtures


class AggregateRuntimeTest(unittest.TestCase):
    maxDiff = None
    def test_real_engine_routes_requests_and_detects_wrong_fallback(self):
        binary = os.environ.get('MIHOMO_BIN')
        assets = os.environ.get('MIHOMO_DATA_DIR')
        if not binary or not assets or not fixtures.yaml:
            self.skipTest('Requires MIHOMO_BIN, MIHOMO_DATA_DIR and PyYAML')
        fixture = fixtures.AggregateTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.shared_plan()
        fixture.generate(target='mihomo')
        root = fixture.root
        data = fixtures.yaml.safe_load(fixture.output().read_text())
        for name in ('geoip.dat', 'geosite.dat', 'ASN.mmdb', 'Country.mmdb'):
            shutil.copyfile(Path(assets) / name, root / name)

        def server(marker):
            class Handler(http.server.BaseHTTPRequestHandler):
                def handle(self):
                    try:
                        super().handle()
                    except (BrokenPipeError, ConnectionResetError):
                        # Mihomo cancels concurrent health probes on selection
                        # and shutdown. Foreground responses remain asserted.
                        pass

                def do_CONNECT(self):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.flush()
                    self.raw_requestline = self.rfile.readline(65537)
                    if self.raw_requestline and self.parse_request():
                        self.do_GET()

                def do_GET(self):
                    body = marker.encode()
                    status = 503 if self.path == '/auto-health' and marker == 'PRIMARY' else 200
                    self.send_response(404 if self.path == '/missing-rules' else status)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *args):
                    pass
            instance = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            threading.Thread(target=instance.serve_forever, daemon=True).start()
            self.addCleanup(instance.server_close)
            self.addCleanup(instance.shutdown)
            return instance.server_port

        direct_port, primary_port, backup_port = [server(s) for s in ('DIRECT', 'PRIMARY', 'BACKUP')]
        for group in data['proxy-groups']:
            if group['type'] == 'fallback':
                group['url'] = f'http://127.0.0.1:{direct_port}/health'
            elif group['type'] == 'url-test':
                group['url'] = f'http://127.0.0.1:{direct_port}/auto-health'
                group['expected-status'] = '200'
        for node in data['proxies']:
            name = node['name']
            node.clear()
            node.update(name=name, type='http', server='127.0.0.1',
                        port=primary_port if name.startswith('cstone/') else backup_port)
        for name, provider in data['rule-providers'].items():
            if name.startswith('ordinary-'):
                service = name.removeprefix('ordinary-')
                cache = os.environ.get('ORDINARY_RULESET_DIR')
                if cache:
                    # Final acceptance uses the complete pinned upstream data,
                    # rather than mocking which domains a service contains.
                    source = Path(cache) / (service + '.mrs')
                    rule_format = 'mrs'
                    if not source.exists():
                        source = Path(cache) / (service + '.list')
                        rule_format = 'text'
                    self.assertTrue(source.is_file(), str(source))
                    destination = root / source.name
                    shutil.copyfile(source, destination)
                    provider.clear()
                    provider.update(type='file', behavior='domain', format=rule_format, path=str(destination))
                    continue
                # Offline fixture for the routing boundary; upstream content is
                # independently verified with ORDINARY_RULESET_DIR in acceptance.
                domains = {'steam': ['steampowered.com'], 'disney': ['disneyplus.com'],
                           'reuters': ['reuters.com'], 'python': ['pypi.org'],
                           'coursera': ['coursera.org'], 'threads': ['threads.net', 'threads.com'],
                           'discord': ['discord.com']}.get(service, ['unused.invalid'])
                path = root / f'{name}.yaml'
                path.write_text(fixtures.yaml.safe_dump({'payload': ['+.' + d for d in domains]}))
                provider.clear()
                provider.update(type='file', behavior='domain', format='yaml', path=str(path))
                continue
            domains = {'cn': ['baidu.com', 'openai.com', 'reddit.com', 'tiktokshop.com'],
                       'ai': ['openai.com', 'netflix.com'],
                       'apple-cn': ['apple.cn'], 'ads-lite': ['ads.test']}.get(name, ['unused.invalid'])
            path = root / f'{name}.yaml'
            path.write_text(fixtures.yaml.safe_dump({'payload': ['DOMAIN-SUFFIX,' + d for d in domains]}))
            provider.clear()
            provider.update(type='file', behavior='classical', format='yaml', path=str(path))
        # DNS/origin connectivity is outside this boundary. NXDOMAIN makes
        # DIRECT attempts observable without contacting any public origin.
        class DNS(socketserver.BaseRequestHandler):
            def handle(self):
                packet, sock = self.request
                response = packet[:2] + b'\x81\x83' + packet[4:6] + b'\x00\x00' * 3 + packet[12:]
                sock.sendto(response, self.client_address)
        dns = socketserver.ThreadingUDPServer(('127.0.0.1', 0), DNS)
        threading.Thread(target=dns.serve_forever, daemon=True).start()
        self.addCleanup(dns.server_close)
        self.addCleanup(dns.shutdown)
        resolver = f'127.0.0.1:{dns.server_address[1]}'
        ordinary = ['youtube.com', 'nflxvideo.net', 'telegram.org', 'ibkr.com', 'interactivebrokers.com',
                    'tradingview.com', 'spotify.com', 'twitch.tv', 'wikipedia.org',
                    'steampowered.com', 'disneyplus.com', 'reuters.com', 'pypi.org',
                    'coursera.org', 'threads.net', 'threads.com', 'discord.com']
        domains = ['baidu.com', 'openai.com', 'unknown.example', 'unlisted.cn', 'apple.cn',
                   'netflix.com', 'reddit.com', 'accounts.google.com', 'gemini.google.com',
                   'unknown-ai.googleapis.com', 'youtube.com.attacker.example', 'notyoutube.com',
                   'ads.google.com', 'business.facebook.com', 'seller.tiktokshop.com',
                   'seller.tiktokglobalshop.com', 'ads.tiktok.com', 'x.com', 'grok.com',
                   'manager.line.biz', 'brightline.tv', 'future-service.bbc',
                   'api.anthropic.com', 'platform.claude.com', 'bridge.claudeusercontent.com',
                   'assets-proxy.anthropic.com', 'a.livepreview.claude.app',
                   'http-intake.logs.us5.datadoghq.com', 'cdnjs.cloudflare.com',
                   'cdn.jsdelivr.net', 'cdn.tailwindcss.com', 'code.jquery.com',
                   'unpkg.com', 'fonts.googleapis.com', 'fonts.gstatic.com'] + ordinary
        data['dns']['use-system-hosts'] = False
        data['dns']['listen'] = '127.0.0.1:0'
        for key in ('default-nameserver', 'nameserver', 'proxy-server-nameserver'):
            data['dns'][key] = [resolver]
        data['dns']['nameserver-policy'] = {key: [resolver] for key in data['dns']['nameserver-policy']}
        data['tun']['enable'] = False
        data['allow-lan'] = False
        data['log-level'] = 'info'
        data['profile'] = {'store-selected': False}
        data.pop('external-controller', None)

        runtime_logs = []
        def exercise(config):
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
                with socket.socket() as control:
                    control.bind(('127.0.0.1', 0))
                    control_port = control.getsockname()[1]
            config['mixed-port'] = port
            config['external-controller'] = f'127.0.0.1:{control_port}'
            path = root / 'runtime.yaml'
            path.write_text(fixtures.yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
            process = subprocess.Popen([binary, '-d', str(root), '-f', str(path)],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    deadline = time.monotonic() + 20
                    logs = b''
                    while b'Mixed(http+socks) proxy listening' not in logs:
                        remaining = deadline - time.monotonic()
                        self.assertGreater(remaining, 0, logs.decode(errors='replace'))
                        self.assertIsNone(process.poll(), logs.decode(errors='replace'))
                        if selector.select(remaining):
                            logs += os.read(process.stdout.fileno(), 65536)
                def request(host):
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                    try:
                        connection.request('GET', f'http://{host}:{direct_port}/probe')
                        response = connection.getresponse()
                        return response.status, response.read().decode()
                    finally:
                        connection.close()
                # Listener creation precedes tunnel/provider readiness. Wait on
                # the observed local response, never a fixed startup sleep.
                deadline = time.monotonic() + 10
                while request('127.0.0.1') != (200, 'DIRECT'):
                    self.assertLess(time.monotonic(), deadline, 'Mihomo readiness timed out')
                # The ordinary pool has healthy BACKUP exits; PRIMARY rejects
                # only the AUTO probe while remaining healthy for sensitive fallback.
                deadline = time.monotonic() + 10
                while request('youtube.com') != (200, 'BACKUP'):
                    self.assertLess(time.monotonic(), deadline, 'AUTO health selection timed out')
                results = {host: request(host) for host in ['127.0.0.1'] + domains}
                connection = http.client.HTTPConnection('127.0.0.1', control_port, timeout=5)
                try:
                    connection.request('GET', '/providers/rules')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    registry = json.loads(response.read())['providers']
                finally:
                    connection.close()
                for name, provider in config['rule-providers'].items():
                    if name.startswith('ordinary-') and provider['type'] == 'file':
                        self.assertGreater(registry[name]['ruleCount'], 0, name)
                return results
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                runtime_logs.append((logs + process.stdout.read()).decode(errors='replace'))
                process.stdout.close()

        result = exercise(data)
        expected = {host: (200, 'PRIMARY') for host in domains}
        expected.update({'127.0.0.1': (200, 'DIRECT'), 'baidu.com': (502, ''),
                         'apple.cn': (502, ''), 'reddit.com': (502, '')})
        expected.update({host: (200, 'BACKUP') for host in ordinary})
        self.assertEqual(result, expected, '\n'.join(runtime_logs))
        self.assertIn('dial 🇨🇳 国内流量 (match RuleSet/cn)', runtime_logs[0])
        self.assertIn('dial 🇨🇳 国内流量 (match RuleSet/apple-cn)', runtime_logs[0])
        # Real HTTP 404 with no provider cache must leave this ordinary service
        # on the sensitive fallback, never DIRECT or an unrelated AUTO category.
        original = data['rule-providers']['ordinary-steam']
        data['rule-providers']['ordinary-steam'] = dict(
            type='http', behavior='domain', format='text', interval=86400,
            path=str(root / 'uncached-steam.list'), proxy='DIRECT',
            url=f'http://127.0.0.1:{direct_port}/missing-rules')
        unavailable = exercise(data)
        self.assertEqual(unavailable['steampowered.com'], (200, 'PRIMARY'), '\n'.join(runtime_logs))
        data['rule-providers']['ordinary-steam'] = original
        # Negative control: reverting the privacy fallback must be detectable.
        data['rules'][-1] = 'MATCH,DIRECT'
        wrong = exercise(data)
        self.assertEqual(wrong['unknown.example'], (502, ''))
        self.assertNotEqual(wrong['unknown.example'], expected['unknown.example'])


if __name__ == '__main__':
    unittest.main()
