#!/usr/bin/env python3
"""Persistent GPU boot-attempt latch. No GPU, display, service or power commands.

A pending/failed attempt blocks subsequent boots until a reviewed deployment
archives/resets the latch. Stable or orderly-stopped state permits one new attempt on a NEW boot.
Stopped records a SIGTERM interruption, not successful desktop validation.
"""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path


class Blocked(RuntimeError):
    pass


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def read(path):
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ValueError('State parent must be an existing real directory')
    parent = path.parent.stat()
    if parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
        raise ValueError('State parent ownership/permissions are unsafe')
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as stream:
        meta = os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid() or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_nlink != 1 or meta.st_size > 4096:
            raise ValueError('State file ownership/type/permissions/size are unsafe')
        data = json.load(stream)
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('phase') not in ('pending', 'stable', 'failed', 'stopped'):
        raise ValueError('Unknown boot-state schema/phase')
    if not isinstance(data.get('profile'), str) or not data['profile'] or not isinstance(data.get('boot'), str):
        raise ValueError('Missing profile/boot identity')
    uuid.UUID(data['boot'])
    return data


def write(path, data):
    # read() also validates the existing parent/file before atomic replacement.
    read(path)
    fd, temporary = tempfile.mkstemp(prefix='.boot-state-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def transaction(path):
    read(path)  # validate ownership and reject malformed state before creating a lock
    lock = path.with_name(path.name + '.lock')
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid() or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_nlink != 1:
            raise ValueError('Unsafe boot-state lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Blocked('Another GPU state transaction is running') from error
        yield
    finally:
        os.close(fd)


def serialized(function):
    def invoke(path, *args):
        with transaction(path):
            return function(path, *args)
    return invoke


@serialized
def begin(path, profile, boot):
    boot = str(uuid.UUID(boot))
    if not profile or len(profile) > 128:
        raise ValueError('Invalid profile')
    old = read(path)
    if old and old['phase'] not in ('stable', 'stopped'):
        raise Blocked('Previous GPU attempt is ' + old['phase'] + '; reviewed reset required')
    if old and old['boot'] == boot:
        raise Blocked('GPU activation already attempted in this boot')
    data = {'schema': 1, 'profile': profile, 'boot': boot, 'phase': 'pending', 'started': stamp()}
    write(path, data)
    return data


@serialized
def finish(path, profile, boot, phase, observation):
    boot = str(uuid.UUID(boot))
    old = read(path)
    if not old or old['profile'] != profile or old['boot'] != boot or old['phase'] != 'pending':
        raise Blocked('No matching pending GPU attempt')
    if phase not in ('stable', 'failed', 'stopped') or not observation or len(observation) > 256:
        raise ValueError('Invalid completion')
    data = dict(old, phase=phase, observation=observation, updated=stamp())
    write(path, data)
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('begin', 'stable', 'failed', 'stopped', 'status'))
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--profile', required=True)
    p.add_argument('--observation', default='')
    args = p.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Root required')
    try:
        if args.action == 'status':
            result = read(args.state)
        else:
            boot = subprocess.check_output(['sysctl', '-n', 'kern.bootsessionuuid'], text=True).strip()
            result = begin(args.state, args.profile, boot) if args.action == 'begin' else finish(args.state, args.profile, boot, args.action, args.observation)
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, RuntimeError) as error:
        p.exit(75, str(error) + '\n')


if __name__ == '__main__':
    main()
