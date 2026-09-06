import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
from net_probe import connect, resolve_ipv4


class PhysicalProbeTests(unittest.TestCase):
    def test_doh_bypasses_proxy_environment_and_system_fake_ip(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'Status': 0, 'Answer': [
            {'type': 1, 'data': '1.1.1.1'}]}), '')
        with patch('net_probe.subprocess.run', return_value=result) as run:
            self.assertEqual(resolve_ipv4('cdn.example.com', 'en0', 10), ['1.1.1.1'])
        args = run.call_args.args[0]
        self.assertEqual(args[args.index('--interface') + 1], 'en0')
        self.assertEqual(args[args.index('--noproxy') + 1], '*')
        self.assertIn('--resolve', args)
        self.assertNotIn('--insecure', args)

    def test_fake_or_private_dns_answers_are_rejected(self):
        for address in ('198.18.0.1', '127.0.0.1', '10.0.0.1'):
            result = subprocess.CompletedProcess([], 0, json.dumps({'Status': 0, 'Answer': [
                {'type': 1, 'data': address}]}), '')
            with patch('net_probe.subprocess.run', return_value=result):
                with self.assertRaisesRegex(ValueError, '未使用系统'):
                    resolve_ipv4('cdn.example.com', 'en0', 10)

    def test_darwin_socket_is_bound_before_connection(self):
        sock = Mock()
        with patch('net_probe.sys.platform', 'darwin'), patch('net_probe.socket.if_nametoindex', return_value=4), \
                patch('net_probe.socket.socket', return_value=sock), patch('net_probe.resolve_ipv4', return_value=['1.1.1.1']):
            self.assertIs(connect('cdn.example.com', 443, 20, 'en0'), sock)
        self.assertEqual(sock.method_calls[0].args[1:], (25, 4))
        sock.connect.assert_called_once_with(('1.1.1.1', 443))


if __name__ == '__main__':
    unittest.main()
