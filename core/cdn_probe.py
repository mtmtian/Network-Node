"""Direct TLS → WebSocket → VLESS → verified HTTPS probe using the standard library.

This deliberately ignores HTTP proxy environment variables. Set PROBE_INTERFACE
to bind both DNS and proxy traffic to a physical interface outside a local TUN.
"""
import base64
import hashlib
import os
from pathlib import Path
import ssl
import struct
import sys
import time
import uuid

from settings import load_settings, validate
from net_probe import connect


def exact(stream, size):
    result = bytearray()
    while len(result) < size:
        block = stream.recv(size - len(result))
        if not block:
            raise ValueError('CDN 连接提前关闭')
        result.extend(block)
    return bytes(result)


def websocket_handshake(sock, host, path):
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((f'GET /{path.lstrip("/")} HTTP/1.1\r\nHost: {host}\r\n'
                  'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                  f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
    head = bytearray()
    while not head.endswith(b'\r\n\r\n'):
        if len(head) >= 16384:
            raise ValueError('CDN 握手响应过大')
        head.extend(exact(sock, 1))
    lines = head.decode('iso-8859-1').split('\r\n')
    fields = lines[0].split()
    if len(fields) < 2 or fields[1] != '101':
        status = fields[1] if len(fields) > 1 and fields[1].isdigit() else 'unknown'
        raise ValueError(f'CDN WebSocket 握手失败（HTTP {status}）；检查 Tunnel、路径及 WAF')
    headers = dict((k.lower(), v.strip()) for k, v in (line.split(':', 1) for line in lines[1:] if ':' in line))
    expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
    if (headers.get('sec-websocket-accept') != expected or headers.get('upgrade', '').lower() != 'websocket'
            or 'upgrade' not in [token.strip() for token in headers.get('connection', '').lower().split(',')]):
        raise ValueError('CDN WebSocket 握手校验失败')


class WebSocket:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = b''

    def send(self, data, opcode=2):
        mask = os.urandom(4)
        size = len(data)
        if size < 126:
            length = bytes([size | 128])
        elif size < 65536:
            length = bytes([126 | 128]) + struct.pack('!H', size)
        else:
            length = bytes([127 | 128]) + struct.pack('!Q', size)
        payload = bytes(value ^ mask[i % 4] for i, value in enumerate(data))
        self.sock.sendall(bytes([128 | opcode]) + length + mask + payload)

    def recv(self, size):
        while not self.buffer:
            first, second = exact(self.sock, 2)
            opcode, length = first & 15, second & 127
            if first & 112 or second & 128:
                raise ValueError('CDN WebSocket 帧格式错误')
            if length == 126:
                length = struct.unpack('!H', exact(self.sock, 2))[0]
            elif length == 127:
                length = struct.unpack('!Q', exact(self.sock, 8))[0]
            if length > 1048576:
                raise ValueError('CDN WebSocket 帧过大')
            data = exact(self.sock, length)
            if opcode == 9:
                self.send(data, opcode=10)
            elif opcode == 10:
                continue
            elif opcode in (0, 2):
                self.buffer = data
            else:
                raise ValueError('CDN WebSocket 关闭或返回非二进制数据')
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data


class Vless:
    def __init__(self, websocket, device_uuid, target):
        self.ws = websocket
        self.response = False
        host = target.encode('idna')
        # Version, UUID, empty addons, TCP command, port, domain address type.
        self.ws.send(b'\x00' + uuid.UUID(device_uuid).bytes + b'\x00\x01'
                     + struct.pack('!H', 443) + b'\x02' + bytes([len(host)]) + host)

    def send(self, data):
        self.ws.send(data)

    def recv(self, size):
        if not self.response:
            version, addons = exact(self.ws, 2)
            if version != 0:
                raise ValueError('VLESS 响应版本错误')
            exact(self.ws, addons)
            self.response = True
        return self.ws.recv(size)


def https_probe(transport, target):
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    tls = ssl.create_default_context().wrap_bio(incoming, outgoing, server_hostname=target)

    def flush():
        while outgoing.pending:
            transport.send(outgoing.read())

    def exchange(operation):
        while True:
            try:
                result = operation()
                flush()
                return result
            except ssl.SSLWantReadError:
                flush()
                data = transport.recv(16384)
                if not data:
                    raise ValueError('HTTPS 探测连接提前关闭')
                incoming.write(data)

    exchange(tls.do_handshake)
    request = f'GET /generate_204 HTTP/1.1\r\nHost: {target}\r\nConnection: close\r\n\r\n'.encode()
    while request:
        request = request[exchange(lambda: tls.write(request)):]
    head = bytearray()
    while b'\r\n' not in head:
        if len(head) > 16384:
            raise ValueError('HTTPS 探测响应过大')
        block = exchange(lambda: tls.read(4096))
        if not block:
            raise ValueError('HTTPS 探测连接提前关闭')
        head.extend(block)
    status = bytes(head).split(b'\r\n', 1)[0].split()
    if len(status) < 2 or status[1] != b'204':
        raise ValueError('CDN 已建立连接，但 HTTPS 探测未返回预期的 204')


class DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def arm(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        self.sock.settimeout(remaining)

    def sendall(self, data):
        self.arm()
        self.sock.sendall(data)

    def recv(self, size):
        self.arm()
        return self.sock.recv(size)


def check_cdn(settings, timeout=20):
    validate(settings)
    required = ('CDN_HOSTNAME', 'CDN_WS_PATH')
    devices = settings.get('DEVICES', '').split()
    if settings.get('CDN_ENABLE') != 'true' or any(not settings.get(k) for k in required) or not devices:
        raise ValueError('CDN 未启用或连接参数不完整')
    for device in devices:
        if not settings.get('CDN_UUID_' + device):
            raise ValueError('CDN 设备凭据不完整')
        try:
            device_uuid = str(uuid.UUID(settings['CDN_UUID_' + device]))
        except ValueError:
            raise ValueError('CDN 设备 UUID 格式无效') from None
        host = settings['CDN_HOSTNAME']
        deadline = time.monotonic() + timeout
        try:
            with connect(host, 443, timeout, settings.get('PROBE_INTERFACE', '')) as raw:
                with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as secured:
                    sock = DeadlineSocket(secured, deadline)
                    websocket_handshake(sock, host, settings['CDN_WS_PATH'])
                    transport = Vless(WebSocket(sock), device_uuid, 'www.gstatic.com')
                    https_probe(transport, 'www.gstatic.com')
        except (OSError, ssl.SSLError):
            raise ValueError('CDN DNS、TLS 或网络连接失败/超时；未输出地址和凭据') from None


if __name__ == '__main__':
    try:
        check_cdn(load_settings(Path(sys.argv[1])))
        print('CDN 所有设备的 TLS / WebSocket / VLESS / HTTPS 请求通过')
    except (ValueError, OSError) as exc:
        sys.exit(str(exc))
