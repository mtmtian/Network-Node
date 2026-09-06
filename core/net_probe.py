"""Optional physical-interface probes, including DNS outside a local proxy TUN."""
import ipaddress
import json
import socket
import subprocess
import sys
import time
from urllib.parse import urlencode


def resolve_ipv4(host, interface, timeout):
    try:
        return [str(ipaddress.IPv4Address(host))]
    except ipaddress.AddressValueError:
        pass
    # Use the same domestic DoH provider as the client bootstrap, with explicit
    # routing and TLS verification. System DNS may return a Stash fake IP.
    url = 'https://dns.alidns.com/resolve?' + urlencode({'name': host, 'type': 'A'})
    try:
        result = subprocess.run(['curl', '--silent', '--show-error', '--fail', '--noproxy', '*',
                                 '--max-time', str(timeout), '--interface', interface,
                                 '--resolve', 'dns.alidns.com:443:223.5.5.5', url],
                                capture_output=True, text=True, timeout=timeout + 1)
        if result.returncode:
            raise ValueError()
        data = json.loads(result.stdout)
        if data.get('Status') != 0:
            raise ValueError()
        answers = list(dict.fromkeys(str(ipaddress.IPv4Address(row['data']))
                                     for row in data.get('Answer', []) if row.get('type') == 1))
        if not answers or any(not ipaddress.ip_address(ip).is_global for ip in answers):
            raise ValueError()
        return answers
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        raise ValueError('物理网卡 DoH 解析失败；未使用系统代理 DNS 或 fake IP 回退') from None


def connect(host, port, timeout, interface=''):
    if not interface:
        return socket.create_connection((host, port), timeout=timeout)
    index = socket.if_nametoindex(interface)
    deadline = time.monotonic() + timeout
    addresses = resolve_ipv4(host, interface, min(timeout, 10))
    for address in addresses:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform == 'darwin':
                # Darwin SDK netinet/in.h: IP_BOUND_IF = 25.
                sock.setsockopt(socket.IPPROTO_IP, 25, index)
            elif sys.platform.startswith('linux'):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode() + b'\x00')
            else:
                raise ValueError('当前平台不支持物理网卡绑定探测')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            sock.settimeout(min(remaining, 5))
            sock.connect((address, port))
            return sock
        except OSError:
            sock.close()
        except BaseException:
            sock.close()
            raise
    raise OSError('物理网卡连接失败')
