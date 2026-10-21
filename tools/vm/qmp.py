#!/usr/bin/env python3
"""Send an explicit QMP command to a local VM socket (GPU test by default)."""
import argparse
import json
import socket

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--socket', default='/mnt/vm/images/macos-gpu-test/qmp.sock')
parser.add_argument('command')
parser.add_argument('arguments', nargs='?', default='{}')
args = parser.parse_args()
arguments = json.loads(args.arguments)
if not isinstance(arguments, dict):
    parser.error('arguments must be a JSON object')
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
    connection.settimeout(15)
    connection.connect(args.socket)
    stream = connection.makefile('rwb')
    greeting = json.loads(stream.readline())
    if 'QMP' not in greeting:
        raise RuntimeError('Not a QMP greeting')
    def execute(command, parameters):
        stream.write((json.dumps({'execute': command, 'arguments': parameters, 'id': command}) + '\n').encode())
        stream.flush()
        while True:
            line = stream.readline()
            if not line:
                raise RuntimeError('QMP disconnected before reply')
            response = json.loads(line)
            if response.get('id') == command:
                return response
    response = execute('qmp_capabilities', {})
    if 'error' not in response:
        response = execute(args.command, arguments)
    print(json.dumps(response))
    raise SystemExit(2 if 'error' in response else 0)
