"""Subscription transport must not forward a bearer URL through redirects."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest
import json
import tempfile
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subscription


class SubscriptionTransportTests(unittest.TestCase):
    def test_client_identity_and_redirect_refusal(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen.append((self.path, self.headers.get('User-Agent')))
                if self.path.startswith('/redirect'):
                    self.send_response(302)
                    self.send_header('Location', '/must-not-receive-token')
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'public test fixture')

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            status, body, _ = subscription.fetch_subscription(base + '/fixture')
            self.assertEqual((status, body), (200, b'public test fixture'))
            self.assertEqual(seen[-1][1], 'clash-verge/2.5.5')
            status, _, _ = subscription.fetch_subscription(base + '/redirect?token=public-test')
            self.assertEqual(status, 302)
            self.assertEqual(len(seen), 2)
            self.assertFalse(any(path.startswith('/must-not') for path, _ in seen))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_standalone_name_is_scoped_to_parent(self):
        self.assertEqual(subscription.output_name('routing', 'cstone'), 'routing-cstone')
        self.assertEqual(subscription.output_name('routing'), 'routing')
        for value in ('../dmit', '', 'cstone/Reality', 'x' * 64):
            with self.subTest(server=value), self.assertRaises(subscription.PublishError):
                subscription.output_name('routing', value)

    def test_retired_profile_cannot_publish_existing_yaml(self):
        # A disabled generator exits successfully without checking old output.
        # Publishing must independently refuse that stale retired artifact.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'profiles/retired'
            state.mkdir(parents=True)
            (state / 'deploy.conf').write_text('CLIENT_CONFIG_ENABLE=false\n')
            target = root / 'clash-configs/mihomo/retired.yaml'
            target.parent.mkdir(parents=True)
            target.write_text('mode: rule\nproxies:\n  []\nrules:\n  []\n')
            with mock.patch.object(subscription, 'ROOT', root):
                with self.assertRaisesRegex(subscription.PublishError, '停用'):
                    subscription.verified_file('retired')

    def test_custom_prefix_uses_owned_checked_snapshot(self):
        # The external generator checker is the boundary: it must succeed before
        # bytes are returned, and concurrent file changes must abort publication.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'profiles/server'
            state.mkdir(parents=True)
            (state / 'deploy.conf').write_text('CLIENT_FILE_PREFIX=custom\n')
            target = root / 'clash-configs/mihomo/custom.yaml'
            target.parent.mkdir(parents=True)
            content = b'mode: rule\nproxies:\n  []\nrules:\n  []\n'
            target.write_bytes(content)
            manifest = target.parent / '.network-node-outputs.json'
            manifest.write_text(json.dumps({'server': {'custom.yaml': 'fixture'}}))
            with mock.patch.object(subscription, 'ROOT', root):
                with mock.patch.object(subscription, 'run', return_value=b'') as check:
                    self.assertEqual(subscription.verified_file('server'), content)
                    self.assertIn('check', check.call_args.args[0])
                manifest.write_text('{}')
                with self.assertRaisesRegex(subscription.PublishError, '归属'):
                    subscription.verified_file('server')
                manifest.write_text(json.dumps({'server': {'custom.yaml': 'fixture'}}))
                with mock.patch.object(subscription, 'run', side_effect=lambda *a: target.write_text('changed')):
                    with self.assertRaisesRegex(subscription.PublishError, '改变'):
                        subscription.verified_file('server')

    def test_profile_cannot_change_url_path_or_query(self):
        for profile in ('../routing', 'routing?token=changed', 'routing/other', ''):
            with self.subTest(profile=profile), self.assertRaises(subscription.PublishError):
                subscription.subscription_url('https://fixture.example', profile, 'public-test')
