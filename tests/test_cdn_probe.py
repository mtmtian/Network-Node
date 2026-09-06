"""Protocol checks use synthetic frames and an in-memory TLS server, never CF."""
import base64
import hashlib
import io
from pathlib import Path
import ssl
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from cdn_probe import Vless, WebSocket, check_cdn, https_probe, websocket_handshake


class BytesSocket:
    def __init__(self, data=b''):
        self.incoming = io.BytesIO(data)
        self.sent = bytearray()

    def recv(self, size):
        return self.incoming.read(size)

    def sendall(self, data):
        self.sent.extend(data)


class CdnProbeTests(unittest.TestCase):
    def test_websocket_accept_is_verified(self):
        key = base64.b64encode(b'x' * 16).decode()
        accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        response = ('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                    f'Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n').encode()
        sock = BytesSocket(response)
        with patch('cdn_probe.os.urandom', return_value=b'x' * 16):
            websocket_handshake(sock, 'cdn.example.com', 'path')
            with self.assertRaisesRegex(ValueError, '校验失败'):
                websocket_handshake(BytesSocket(response.replace(accept.encode(), b'wrong')), 'cdn.example.com', 'path')
        self.assertIn(b'GET /path HTTP/1.1', sock.sent)

    def test_waf_challenge_is_not_success_and_body_is_not_logged(self):
        sock = BytesSocket(b'HTTP/1.1 403 Forbidden\r\n\r\nsecret-server-body')
        with self.assertRaisesRegex(ValueError, 'HTTP 403') as raised:
            websocket_handshake(sock, 'cdn.example.com', 'path')
        self.assertNotIn('secret-server-body', str(raised.exception))

    def test_ping_is_answered_and_split_vless_header_is_consumed(self):
        sock = BytesSocket(b'\x89\x02hi' + b'\x82\x01\x00' + b'\x82\x04\x00abc')
        stream = Vless(WebSocket(sock), '00000000-0000-4000-8000-000000000001', 'www.gstatic.com')
        self.assertEqual(stream.recv(3), b'abc')
        self.assertTrue(stream.response)
        self.assertEqual(sock.sent[0], 0x82)
        self.assertTrue(sock.sent[1] & 0x80)  # Client frames must be masked.
        self.assertIn(0x8a, sock.sent)  # Pong frame.

    def test_oversized_or_closed_frames_are_rejected(self):
        for frame in (b'\x82\x7f' + struct.pack('!Q', 1048577), b'\x88\x00'):
            with self.assertRaises(ValueError):
                WebSocket(BytesSocket(frame)).recv(1)

    def test_missing_configuration_fails_before_network(self):
        with patch('cdn_probe.connect') as connect:
            with self.assertRaisesRegex(ValueError, '未启用'):
                check_cdn({'CDN_ENABLE': 'false'})
            with self.assertRaisesRegex(ValueError, '凭据不完整'):
                check_cdn({'CDN_ENABLE': 'true', 'CDN_HOSTNAME': 'cdn.example.com',
                           'CDN_WS_PATH': 'path', 'DEVICES': 'mac'})
        connect.assert_not_called()

    def test_real_tls_handshake_http_status_and_certificate_validation(self):
        with tempfile.TemporaryDirectory() as td:
            cert, key = Path(td) / 'cert.pem', Path(td) / 'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-subj', '/CN=probe.test', '-addext', 'subjectAltName=DNS:probe.test',
                            '-keyout', str(key), '-out', str(cert)], capture_output=True, check=True)
            client_context = ssl.create_default_context(cafile=str(cert))
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.load_cert_chain(cert, key)

            class Server:
                def __init__(self, response=b'HTTP/1.1 204 No Content\r\n\r\n'):
                    self.incoming, self.outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
                    self.tls = server_context.wrap_bio(self.incoming, self.outgoing, server_side=True)
                    self.ready = False
                    self.request = b''
                    self.response = response

                def send(self, data):
                    self.incoming.write(data)
                    try:
                        if not self.ready:
                            self.tls.do_handshake()
                            self.ready = True
                        self.request += self.tls.read(16384)
                        if b'\r\n\r\n' in self.request:
                            self.tls.write(self.response)
                    except ssl.SSLWantReadError:
                        pass

                def recv(self, size):
                    return self.outgoing.read(size)

            with patch('cdn_probe.ssl.create_default_context', return_value=client_context):
                server = Server()
                https_probe(server, 'probe.test')
                self.assertIn(b'GET /generate_204', server.request)
                with self.assertRaisesRegex(ValueError, '204'):
                    https_probe(Server(b'HTTP/1.1 503 Unavailable\r\n\r\n'), 'probe.test')
                with self.assertRaises(ssl.SSLCertVerificationError):
                    https_probe(Server(), 'wrong-host.test')


if __name__ == '__main__':
    unittest.main()
