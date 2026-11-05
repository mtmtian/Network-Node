"""Opt-in live TUN acceptance; only serves a fixed marker, never filesystem data.

Run with --expect reachable before applying the guard, then --expect blocked.
Does not change proxy settings, read credentials or contact existing local services.
"""
import argparse
import http.server
import json
from pathlib import Path
import subprocess
import threading
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expect', choices=('reachable', 'blocked'), required=True)
    parser.add_argument('--public', action='store_true', help='Also check a public JS page')
    args = parser.parse_args()
    marker = 'network-node-acceptance-' + uuid.uuid4().hex
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            body = marker.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    wrapper = Path.home() / '.agents/skills/lightpanda/scripts/lightpanda-safe'
    results = {}
    with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_port
            for host in ('127.0.0.1', 'localhost', 'localhost.ptlogin2.qq.com',
                         'localhost.weixin.qq.com'):
                path = '/lightpanda-' + uuid.uuid4().hex
                result = subprocess.run(
                    [str(wrapper), 'fetch', f'http://{host}:{port}{path}',
                     '--json', '--dump', 'markdown', '--log-level', 'error'],
                    capture_output=True, text=True, timeout=35)
                data = json.loads(result.stdout)
                if 'results' in data:
                    data = data['results'][0]
                results[host] = {
                    'http_status': data.get('http_status'), 'error': data.get('error'),
                    'marker_received': marker in result.stdout,
                    'server_received_request': path in hits,
                }
            path = '/curl-' + uuid.uuid4().hex
            result = subprocess.run(
                ['curl', '--noproxy', '*', '--silent', '--show-error', '--max-time', '15',
                 '--write-out', '\n%{http_code}',
                 f'http://localhost.weixin.qq.com:{port}{path}'],
                capture_output=True, text=True, timeout=20)
            results['curl_same_domain'] = {
                'http_200': result.stdout.endswith('\n200'),
                'marker_received': marker in result.stdout,
                'server_received_request': path in hits,
            }
        finally:
            server.shutdown()
            thread.join(timeout=5)
    target = results['localhost.weixin.qq.com']
    reachable = target['marker_received'] and target['server_received_request']
    blocked = (target['error'] is not None and not target['marker_received']
               and not target['server_received_request'])
    passed = (reachable if args.expect == 'reachable' else blocked)
    passed = passed and all(results['curl_same_domain'].values())
    passed = passed and all(not results[h]['server_received_request'] and results[h]['error']
                            for h in ('127.0.0.1', 'localhost', 'localhost.ptlogin2.qq.com'))
    if args.public:
        result = subprocess.run(
            [str(wrapper), 'fetch', 'https://quotes.toscrape.com/js/', '--json',
             '--dump', 'markdown', '--log-level', 'error'],
            capture_output=True, text=True, timeout=45)
        data = json.loads(result.stdout)
        if 'results' in data:
            data = data['results'][0]
        results['public_js'] = {'http_status': data.get('http_status'),
                                'has_rendered_quote': 'Albert Einstein' in result.stdout,
                                'error': data.get('error')}
        passed = passed and data.get('http_status') == 200 and results['public_js']['has_rendered_quote']
    print(json.dumps({'expected': args.expect, 'passed': bool(passed),
                      'results': results, 'server_closed': True}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
