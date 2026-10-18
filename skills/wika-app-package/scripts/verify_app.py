#!/usr/bin/env python3
"""Verify HIRSCHMANNIMAGE integrity and all frozen payload bytes."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile


def verify(app_path, bin_dir=None, program=None, manifest=None):
    data = Path(app_path).read_bytes()
    if data[:16] != b'HIRSCHMANNIMAGE\x00':
        raise ValueError('Invalid magic')
    records, pos = {}, 16
    while pos < len(data):
        if pos + 32 > len(data):
            raise ValueError('Truncated TLV header')
        tag = data[pos:pos+16].rstrip(b'\0').decode('ascii')
        length = int(data[pos+16:pos+32].rstrip(b'\0'))
        if length < 0 or pos + 32 + length > len(data) or tag in records:
            raise ValueError('Invalid TLV length or duplicate tag')
        records[tag] = data[pos+32:pos+32+length]
        if pos == 16 and (tag != 'MD5' or length != 32):
            raise ValueError('Invalid first MD5 record')
        pos += 32 + length
        if tag == 'USERAPP' and pos != len(data):
            raise ValueError('USERAPP must be last')
    required = {'MD5', 'PRODUCT', 'MODEL', 'BOARD', 'APP_VER', 'DATE', 'OEM', 'USERAPP'}
    if not required <= records.keys():
        raise ValueError('Missing metadata record')
    if records['MD5'] != hashlib.md5(data[:16] + data[80:]).hexdigest().encode():
        raise ValueError('Package MD5 mismatch')
    expected = manifest['files'] if manifest else None
    if manifest:
        body = {k: v for k, v in manifest.items() if k != 'candidate_id'}
        if hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() != manifest['candidate_id']:
            raise ValueError('Candidate manifest identity mismatch')
    with zipfile.ZipFile(io.BytesIO(records['USERAPP'])) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP member')
        for name in names:
            if not name.startswith('/') or name == '/' or '..' in PurePosixPath(name).parts or '\\' in name:
                raise ValueError('Invalid absolute payload member')
        if archive.testzip() is not None:
            raise ValueError('ZIP CRC mismatch')
        if not {'/myapp', '/app.info'} <= set(names):
            raise ValueError('Program or app.info missing')
        info = dict(line.split('=', 1) for line in archive.read('/app.info').decode().splitlines() if '=' in line)
        if (info.get('appname') != 'myapp' or info.get('appdate', '').encode() != records['DATE'].rstrip(b'\0')
                or info.get('appversion', '').encode() != records['APP_VER'].rstrip(b'\0')):
            raise ValueError('app.info name/date differs from package metadata')
        if expected is not None:
            if set(names) != set(expected) | {'/app.info'}:
                raise ValueError('Payload inventory differs from candidate')
            for name, sha in expected.items():
                if hashlib.sha256(archive.read(name)).hexdigest() != sha:
                    raise ValueError('Frozen payload mismatch: ' + name)
        if bin_dir is not None:
            directory = Path(bin_dir).resolve()
            candidates = [name for name in ('SDC190H', 'CoreApp', 'LW1200K', 'myapp') if (directory / name).is_file()]
            if not program:
                if len(candidates) != 1:
                    raise ValueError('Choose --program for this project: ' + str(candidates))
                program = candidates[0]
            for name in names:
                source = (directory / (program if name == '/myapp' else name.lstrip('/'))).resolve()
                source.relative_to(directory)
                if name == '/app.info' and not source.exists() and expected is not None and name not in expected:
                    continue
                if not source.is_file():
                    raise ValueError('Source payload file missing: ' + str(source))
                if source.read_bytes() != archive.read(name):
                    raise ValueError('Source payload differs: ' + name)
        return {'passed': True, 'files': sorted(names), 'package_sha256': hashlib.sha256(data).hexdigest()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('app', type=Path)
    ap.add_argument('--bin-dir', type=Path)
    ap.add_argument('--program', help='Explicit executable name under BIN, e.g. TZ956E')
    ap.add_argument('--manifest', type=Path, help='Frozen candidate manifest.json')
    a = ap.parse_args()
    try:
        manifest = json.loads(a.manifest.read_text(encoding='utf-8-sig')) if a.manifest else None
        result = verify(a.app, a.bin_dir, a.program, manifest)
        print(json.dumps(result))
        print('VERIFY PASS')
        return 0
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
        print('VERIFY FAIL: ' + str(error))
        return 1


if __name__ == '__main__':
    sys.exit(main())
