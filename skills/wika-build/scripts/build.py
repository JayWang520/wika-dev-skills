#!/usr/bin/env python3
"""Build WIKA projects, preserving command exit codes and full logs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def find_pro(root):
    pros = sorted((root / 'Program').glob('*.pro'))
    if len(pros) != 1:
        raise ValueError('Choose pro/build/qmake in wika-project.json; candidates: ' + str(pros))
    return pros[0]


def run_logged(command, directory, log, sdk_env=None):
    argv = list(command)
    if sdk_env:
        argv = ['bash', '-c', 'source "$1" && shift && exec "$@"', 'wika-build', sdk_env] + argv
    log.write(('\n>> ' + repr(argv) + '\n').encode())
    log.flush()
    completed = subprocess.run(argv, cwd=str(directory), stdout=log, stderr=subprocess.STDOUT)
    return {'argv': argv, 'returncode': completed.returncode}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('root', type=Path)
    ap.add_argument('--clean', action='store_true', help='Regenerate Makefile, without deleting files')
    ap.add_argument('--sdk', default='2.8.13')
    ap.add_argument('--profile', type=Path)
    a = ap.parse_args()
    root = a.root.resolve()
    result = {'passed': False, 'commands': []}
    result_path = None
    try:
        profile = None
        if a.profile:
            profile = json.loads(a.profile.read_text(encoding='utf-8-sig'))
            if profile.get('confirmed') is not True:
                raise ValueError('Confirm project profile before building')
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'wika-dev-flow/scripts'))
            from flow_artifacts import inventory, inside, toolchain
            pro = inside(root, profile['pro'])
            directory = inside(root, profile['build']['directory'])
            qmake = profile['build']['qmake']
            sdk_env = profile['build'].get('sdk_env')
            program = inside(root, profile['artifact']['executable'])
            sources_before = inventory(root, profile['source_roots'])
            result['profile_sha256'] = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
        else:
            pro = find_pro(root)
            directory = root / ('build-' + pro.stem + '-IMX6-Release')
            qmake = '/opt/wika-display/' + a.sdk + '/sysroots/x86_64-pokysdk-linux/usr/bin/qmake'
            sdk_env = None
            program = root / 'BIN' / pro.stem
            sources_before = None
        directory.mkdir(parents=True, exist_ok=True)
        result_path = directory / 'build-result.json'
        result.update(program=str(program), log=str(directory / 'build.log'))
        if not qmake or not Path(qmake).is_file():
            raise ValueError('qmake unavailable: ' + str(qmake))
        if sdk_env and not Path(sdk_env).is_file():
            raise ValueError('SDK environment unavailable: ' + sdk_env)
        if profile:
            result['toolchain'] = toolchain(profile)
        with (directory / 'build.log').open('wb') as log:
            commands = []
            if a.clean or not (directory / 'Makefile').exists():
                commands.append([qmake, '-o', 'Makefile', os.path.relpath(pro, directory),
                                 '-spec', 'devices/linux-oe-generic-g++', 'CONFIG+=qtquickcompiler'])
            commands += [['make', '-j' + str(os.cpu_count() or 4)], ['make']]
            for command in commands:
                print('>> ' + ' '.join(command), flush=True)
                row = run_logged(command, directory, log, sdk_env)
                result['commands'].append(row)
                if row['returncode'] != 0:
                    raise ValueError('Build command failed, rc=' + str(row['returncode']))
        data = program.read_bytes()
        if (data[:6] != b'\x7fELF\x01\x01' or int.from_bytes(data[18:20], 'little') != 40
                or int.from_bytes(data[16:18], 'little') not in (2, 3)):
            raise ValueError('Output is not an ARM ELF32 little-endian runtime executable')
        if profile:
            version = profile['artifact'].get('version')
            if not version or (version.encode() not in data and version.encode('utf-16-le') not in data):
                raise ValueError('Expected final version absent from executable')
            sources_after = inventory(root, profile['source_roots'])
            if sources_before != sources_after:
                raise ValueError('Sources changed during build')
            if toolchain(profile) != result['toolchain']:
                raise ValueError('qmake/SDK environment changed during build')
            result['sources'] = sources_after
        result.update(passed=True, program_sha256=hashlib.sha256(data).hexdigest())
    except (ValueError, OSError, TypeError, KeyError) as error:
        result['error'] = str(error)
    finally:
        if result_path:
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
