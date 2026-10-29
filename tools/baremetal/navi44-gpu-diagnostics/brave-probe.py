#!/usr/bin/env python3
"""Measure a visible Brave test window with an isolated, temporary profile.

No existing Brave process or profile is controlled. Run during an idle desktop;
the target site is contacted and the window stays visible for the measurement.
"""
import argparse
import base64
import json
import secrets
import socket
import struct
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

BRAVE = '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'
PROBE = Path(__file__).with_name('browser-frame-probe.js')


class CDP:
    def __init__(self, url):
        u = urllib.parse.urlsplit(url)
        if u.scheme != 'ws' or u.hostname != '127.0.0.1':
            raise ValueError('Only loopback debugging endpoints are accepted')
        self.sock = socket.create_connection((u.hostname, u.port), timeout=10)
        self.sock.settimeout(30)
        nonce = base64.b64encode(secrets.token_bytes(16)).decode()
        request = ('GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\n'
                   'Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n'
                   'Sec-WebSocket-Version: 13\r\n\r\n') % (u.path, u.port, nonce)
        self.sock.sendall(request.encode())
        # Read only through the header, retaining any subsequent frame bytes.
        header = b''
        while not header.endswith(b'\r\n\r\n'):
            chunk = self.sock.recv(1)
            if not chunk: raise EOFError('WebSocket handshake closed')
            header += chunk
            if len(header) > 8192: raise ValueError('Bad WebSocket handshake')
        if not header.startswith(b'HTTP/1.1 101 '): raise ValueError('WebSocket upgrade failed')
        self.ident = 0

    def read(self, size):
        result = b''
        while len(result) < size:
            part = self.sock.recv(size-len(result))
            if not part: raise EOFError('WebSocket closed')
            result += part
        return result

    def send(self, payload, opcode=1):
        data = payload if isinstance(payload, bytes) else payload.encode()
        n = len(data)
        head = bytes([0x80 | opcode]) + (bytes([0x80 | n]) if n < 126 else
                bytes([0xfe]) + struct.pack('!H', n) if n < 65536 else
                bytes([0xff]) + struct.pack('!Q', n))
        mask = secrets.token_bytes(4)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def receive(self):
        while True:
            first, second = self.read(2)
            if not first & 0x80 or second & 0x80: raise ValueError('Unsupported WebSocket frame')
            length = second & 127
            if length == 126: length = struct.unpack('!H', self.read(2))[0]
            elif length == 127: length = struct.unpack('!Q', self.read(8))[0]
            if length > 16 * 1024 * 1024: raise ValueError('WebSocket frame too large')
            payload = self.read(length)
            opcode = first & 15
            if opcode == 9: self.send(payload, 10); continue
            if opcode == 8: raise EOFError('WebSocket closed')
            if opcode == 1: return json.loads(payload)

    def call(self, method, **params):
        self.ident += 1
        ident = self.ident
        self.send(json.dumps({'id':ident, 'method':method, 'params':params}))
        while True:
            response = self.receive()
            if response.get('id') != ident: continue
            if 'error' in response: raise RuntimeError(str(response['error']))
            return response.get('result', {})

    def close(self): self.sock.close()


def endpoint(port, path):
    with urllib.request.urlopen('http://127.0.0.1:%d%s' % (port, path), timeout=3) as f:
        return json.load(f)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', default='https://vorssaint.com')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--diagnostic-log', type=Path, help='Keep stderr from this isolated profile for diagnosis')
    p.add_argument('--disable-graphite', action='store_true', help='Disable Skia Graphite only for this isolated test')
    args = p.parse_args()
    if urllib.parse.urlsplit(args.url).scheme not in ('http', 'https'): p.error('Use an HTTP(S) URL')
    if args.output.exists(): p.error('Output already exists')
    if args.diagnostic_log and args.diagnostic_log.exists(): p.error('Diagnostic log already exists')
    with tempfile.TemporaryDirectory(prefix='navi44-brave-probe-') as profile:
        log = Path(profile) / 'brave.log'
        with log.open('wb') as stderr:
            proc = subprocess.Popen([BRAVE, '--user-data-dir='+profile, '--no-first-run',
                '--no-default-browser-check', '--remote-debugging-address=127.0.0.1',
                '--remote-debugging-port=0'] + (['--enable-logging=stderr'] if args.diagnostic_log else []) + (['--disable-features=SkiaGraphite'] if args.disable_graphite else []) + [args.url], stdout=subprocess.DEVNULL, stderr=stderr)
            browser = page = None
            try:
                deadline = time.monotonic() + 25
                portfile = Path(profile) / 'DevToolsActivePort'
                while not portfile.exists() and time.monotonic() < deadline and proc.poll() is None:
                    time.sleep(.1)
                if not portfile.exists(): raise RuntimeError('Brave debugging endpoint not ready')
                port, browserpath = portfile.read_text().splitlines()[:2]
                port = int(port)
                browser = CDP('ws://127.0.0.1:%d%s' % (port, browserpath))
                info = browser.call('SystemInfo.getInfo')
                pages = endpoint(port, '/json/list')
                target = next((x for x in pages if x.get('type') == 'page' and x.get('url','').startswith(('http:', 'https:'))), None)
                if not target: raise RuntimeError('No test page available')
                page = CDP(target['webSocketDebuggerUrl'])
                # Let navigation and site initialization settle before measuring.
                time.sleep(8)
                page_state = page.call('Runtime.evaluate',
                    expression='({url: location.href, ready: document.readyState, '
                               'width: innerWidth, height: innerHeight, dpr: devicePixelRatio})',
                    returnByValue=True).get('result', {}).get('value')
                if not isinstance(page_state, dict) or page_state.get('ready') != 'complete':
                    raise RuntimeError('Page did not finish loading; measurement is not comparable')
                if urllib.parse.urlsplit(page_state.get('url', '')).scheme not in ('http', 'https'):
                    raise RuntimeError('Browser is not displaying an HTTP(S) page')
                value = page.call('Runtime.evaluate', expression=PROBE.read_text(), awaitPromise=True,
                                  returnByValue=True, timeout=25000)
                if value.get('exceptionDetails'): raise RuntimeError(str(value['exceptionDetails']))
                frame = value.get('result', {}).get('value')
                if not isinstance(frame, dict): raise RuntimeError('Frame probe returned no value')
                info_after = browser.call('SystemInfo.getInfo')
                # The full CDP response contains command-line/profile details. Retain
                # only the GPU status and timing metrics needed for this comparison.
                result = {'url': args.url, 'page': page_state,
                          'gpu_feature_status_before': info.get('gpu',{}).get('featureStatus',{}),
                          'gpu_feature_status_after': info_after.get('gpu',{}).get('featureStatus',{}),
                          'frame_probe': frame, 'disable_graphite': args.disable_graphite, 'note':'Isolated profile; session contention can differ from normal use.'}
                args.output.write_text(json.dumps(result, indent=2)+'\n')
                print(json.dumps(result, indent=2))
            finally:
                if page: page.close()
                if browser:
                    try: browser.call('Browser.close')
                    except (OSError, EOFError): pass
                    browser.close()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                if args.diagnostic_log:
                    stderr.flush()
                    args.diagnostic_log.write_bytes(log.read_bytes())


if __name__ == '__main__': main()
