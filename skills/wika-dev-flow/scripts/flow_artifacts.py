"""Read-only project checks and immutable release candidates. Python 3.8+."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def toolchain(profile):
    return {key: digest(profile['build'][key]) for key in ('qmake', 'sdk_env') if profile['build'].get(key)}


def inside(root, name):
    path = (Path(root) / name).resolve()
    path.relative_to(Path(root).resolve())
    return path


def inventory(root, entries):
    found = {}
    for entry in entries:
        path = inside(root, entry)
        if not path.exists():
            raise ValueError('Missing source: ' + entry)
        for item in ([path] if path.is_file() else sorted(path.rglob('*'))):
            parts = item.relative_to(Path(root).resolve()).parts
            if (not path.is_file() and (parts[0] == 'BIN' or parts[0].startswith('build-'))) or any(
                    p in ('.git', '.wika-flow', '.ui-index', '.ai-remote', '__pycache__') for p in parts):
                continue
            if item.is_file():
                inside(root, item)
                found[item.relative_to(Path(root).resolve()).as_posix()] = digest(item)
    if not found:
        raise ValueError('Empty source inventory')
    return found


def discover(root):
    root = Path(root).resolve()
    ignored = {'.git', '.ai-remote', '.ui-index', '.wika-flow', 'node_modules', 'BIN'}
    pros = [p for p in root.rglob('*.pro') if not any(
        part in ignored or part.startswith('build-') for part in p.relative_to(root).parts)]
    makefiles = sorted(p for p in root.glob('build*/Makefile') if p.is_file())
    qmakes = set()
    for path in makefiles:
        for line in path.read_text(errors='replace').splitlines():
            match = re.match(r'^QMAKE\s*=\s*(.+?)\s*$', line)
            if match and '$' not in match[1]:
                qmakes.add(match[1].strip('"'))
    return {'pro_files': sorted(p.relative_to(root).as_posix() for p in pros),
            'build_dirs': [p.parent.relative_to(root).as_posix() for p in makefiles],
            'qmake_candidates': sorted(qmakes),
            'bin_files': sorted(p.name for p in (root / 'BIN').glob('*') if p.is_file())}


def init_profile(root, pro=None):
    root = Path(root).resolve()
    found = discover(root)
    if pro is None:
        if len(found['pro_files']) != 1:
            raise ValueError('Choose --pro explicitly: ' + json.dumps(found['pro_files']))
        pro = found['pro_files'][0]
    text = inside(root, pro).read_text(errors='replace')
    matches = re.findall(r'^\s*TARGET\s*=\s*([\w.-]+)\s*$', text, re.M)
    name = matches[0] if len(set(matches)) == 1 else Path(pro).stem
    # Ambiguous/dynamic TARGET remains a value to confirm, never an execution decision.
    payload = {'/myapp': 'BIN/' + name}
    for entry in found['bin_files']:
        if entry.endswith(('.eds', '.var')) or re.fullmatch(r'can\d+\.h', entry) or entry in ('Database.db', 'logo.bin'):
            payload['/' + entry] = 'BIN/' + entry
    return {'schema': 1, 'project': name, 'pro': pro, 'confirmed': False,
            'build': {'directory': found['build_dirs'][0] if len(found['build_dirs']) == 1 else None,
                      'qmake': found['qmake_candidates'][0] if len(found['qmake_candidates']) == 1 else None,
                      'sdk_env': None},
            'artifact': {'executable': payload['/myapp'], 'version': None, 'payload': payload},
            'source_roots': [str(Path(pro).parent).replace('\\', '/')],
            'database_policy': 'preserve',
            'device': {'ssh': [], 'service': None, 'executable': None, 'resource_dir': '/apps',
                       'framebuffer': '/dev/fb0', 'touch': None}}


def probe_device(device, payload_names):
    """Only read system state; reuse the user's SSH config and pinned host keys."""
    if not device.get('ssh') or not device.get('service') or not device.get('executable'):
        raise ValueError('Complete device.ssh/service/executable before probing')
    script = '''import hashlib,json,os,subprocess,struct
from pathlib import Path
d=json.loads(CONFIG)
def run(args):
 p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True,timeout=5)
 return {'returncode':p.returncode,'output':p.stdout.strip()}
def sha(p):
 h=hashlib.sha256()
 with open(str(p),'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
service=run(['systemctl','show',d['service'],'-p','MainPID','-p','ActiveState'])
fields=dict(line.split('=',1) for line in service['output'].splitlines() if '=' in line)
pid=fields.get('MainPID','0'); exe=Path('/proc/'+pid+'/exe')
resources={}
for name in NAMES:
 p=Path(d['resource_dir'])/name.lstrip('/')
 resources[name]=sha(p) if p.is_file() else None
def read(p):
 return Path(p).read_text().strip() if Path(p).exists() else None
fb={}
try:
 import fcntl
 with open(d['framebuffer'],'rb',buffering=0) as stream:
  v=bytearray(160);fcntl.ioctl(stream.fileno(),0x4600,v,True);values=struct.unpack_from('20I',v)
  fb={'visible_size':list(values[:2]),'virtual_size':list(values[2:4]),'offset':list(values[4:6]),'bpp':values[6]}
except (OSError,KeyError) as error:fb={'error':str(error)}
print(json.dumps({'machine':os.uname().machine,'boot_id':read('/proc/sys/kernel/random/boot_id'),
 'service':fields,'exe':os.path.realpath(str(exe)),
 'program_sha256':sha(exe) if pid!='0' and exe.exists() else None,
 'resource_sha256':resources,'framebuffer':fb,
 'touch_exists':bool(d.get('touch') and Path(d['touch']).exists()),
 'input_devices':read('/proc/bus/input/devices')}))
'''.replace('CONFIG', repr(json.dumps(device))).replace('NAMES', repr(payload_names))
    command = list(device['ssh']) + ['python3 -']
    result = subprocess.run(command, input=script, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True, timeout=35)
    if result.returncode:
        raise ValueError('SSH probe failed: ' + result.stderr[-1500:])
    return json.loads(result.stdout)


def preflight(root, profile, with_device=False):
    root = Path(root).resolve()
    checks = {'confirmed_profile': profile.get('confirmed') is True,
              'pro_exists': inside(root, profile['pro']).is_file(),
              'build_dir': bool(profile['build'].get('directory') and inside(root, profile['build']['directory']).is_dir()),
              'qmake_exists': bool(profile['build'].get('qmake') and Path(profile['build']['qmake']).is_file()),
              'make_available': shutil.which('make') is not None,
              'free_space_64mb': shutil.disk_usage(root).free >= 64 * 1024 * 1024,
              'database_policy': profile.get('database_policy') in ('preserve', 'migrate', 'initialize')}
    if profile['build'].get('sdk_env'):
        checks['sdk_env_exists'] = Path(profile['build']['sdk_env']).is_file()
    result = {'checks': checks}
    if with_device:
        try:
            runtime = probe_device(profile['device'], [n for n in profile['artifact']['payload']
                                   if n != '/myapp' and n != '/Database.db'])
            result['runtime'] = runtime
            checks['device_program_running'] = bool(runtime['program_sha256']) and runtime['service'].get('ActiveState') == 'active'
            checks['expected_program_path'] = runtime['exe'] == profile['device']['executable']
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            checks['device_reachable'] = False
            result['device_error'] = str(error)
    result['passed'] = all(checks.values())
    return result


def freeze(root, profile, output, build_result):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not profile.get('confirmed') or not profile['artifact'].get('version'):
        raise ValueError('Confirm profile and final version before freezing')
    program = inside(root, profile['artifact']['executable'])
    if not build_result.get('passed') or build_result.get('program_sha256') != digest(program):
        raise ValueError('Build did not pass or program changed since build')
    if build_result.get('profile_sha256') != hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest():
        raise ValueError('Build profile changed since build')
    if build_result.get('toolchain') != toolchain(profile):
        raise ValueError('qmake/SDK environment changed since build')
    data = program.read_bytes()
    if (data[:6] != b'\x7fELF\x01\x01' or int.from_bytes(data[18:20], 'little') != 40
            or int.from_bytes(data[16:18], 'little') not in (2, 3)):
        raise ValueError('Expected ARM ELF32 little-endian runtime executable')
    version = profile['artifact']['version']
    if version.encode() not in data and version.encode('utf-16-le') not in data:
        raise ValueError('Final version absent from program')
    payload = profile['artifact']['payload']
    if payload.get('/myapp') != profile['artifact']['executable']:
        raise ValueError('/myapp must refer to artifact.executable')
    for name in payload:
        if not name.startswith('/') or name == '/' or '..' in Path(name).parts:
            raise ValueError('Invalid package member: ' + name)
    for name in payload:
        if name.endswith('.eds'):
            base = name[:-4]
            if any(base + suffix not in payload for suffix in ('.h', '.var')):
                raise ValueError('Incomplete EDS group: ' + name)
    sources = inventory(root, profile['source_roots'])
    if build_result.get('sources') != sources:
        raise ValueError('Sources changed since build')
    hashes = {name: digest(inside(root, path)) for name, path in payload.items()}
    output.mkdir(parents=True, exist_ok=False)
    for name, source in payload.items():
        target = inside(output / 'payload', name.lstrip('/'))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inside(root, source), target)
        if digest(target) != hashes[name]:
            raise ValueError('Payload changed during freeze: ' + name)
    if inventory(root, profile['source_roots']) != sources:
        raise ValueError('Sources changed during freeze')
    manifest = {'schema': 1, 'project': profile['project'], 'version': version,
                'profile': profile, 'sources': sources, 'files': hashes,
                'program_sha256': hashes['/myapp'], 'build': build_result}
    manifest['candidate_id'] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    save(output / 'manifest.json', manifest)
    return manifest


def verify(root, profile, snapshot, runtime=None, test_result=None):
    snapshot = Path(snapshot)
    manifest = load(snapshot / 'manifest.json')
    body = {k: v for k, v in manifest.items() if k != 'candidate_id'}
    errors = []
    if hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() != manifest['candidate_id']:
        errors.append('Manifest identity mismatch')
    if profile != manifest['profile']:
        errors.append('Profile changed')
    if toolchain(profile) != manifest['build'].get('toolchain'):
        errors.append('qmake/SDK environment changed')
    if inventory(root, profile['source_roots']) != manifest['sources']:
        errors.append('Sources changed: build and test a new candidate')
    for name, expected in manifest['files'].items():
        for path in (inside(snapshot / 'payload', name.lstrip('/')),
                     inside(root, profile['artifact']['payload'][name])):
            if not path.is_file() or digest(path) != expected:
                errors.append('Payload changed: ' + str(path))
    if runtime is not None:
        if runtime.get('program_sha256') != manifest['program_sha256']:
            errors.append('Running executable differs from candidate')
        for name, expected in manifest['files'].items():
            if name not in ('/myapp', '/Database.db', '/app.info') and runtime.get('resource_sha256', {}).get(name) != expected:
                errors.append('Running resource differs: ' + name)
    if test_result is not None:
        if (test_result.get('candidate_id') != manifest['candidate_id']
                or test_result.get('program_sha256') != manifest['program_sha256']
                or test_result.get('mode') != 'release' or test_result.get('execution') != 'live'
                or not test_result.get('release_ready') or not test_result.get('cases')
                or any(row.get('status') != '通过' for row in test_result['cases'])):
            errors.append('Complete live acceptance for this candidate is missing')
    return {'passed': not errors, 'candidate_id': manifest['candidate_id'], 'errors': errors}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=('discover', 'init', 'preflight', 'freeze', 'verify'))
    ap.add_argument('root', type=Path)
    ap.add_argument('--profile', type=Path)
    ap.add_argument('--pro')
    ap.add_argument('--output', type=Path)
    ap.add_argument('--device', action='store_true')
    ap.add_argument('--build-result', type=Path)
    ap.add_argument('--snapshot', type=Path)
    ap.add_argument('--runtime', type=Path)
    ap.add_argument('--test-result', type=Path)
    a = ap.parse_args()
    try:
        if a.command == 'discover':
            result = discover(a.root)
        elif a.command == 'init':
            result = init_profile(a.root, a.pro)
        else:
            profile = load(a.profile or a.root / 'wika-project.json')
            if a.command == 'preflight':
                result = preflight(a.root, profile, a.device)
            elif a.command == 'freeze':
                result = freeze(a.root, profile, a.snapshot, load(a.build_result))
            else:
                result = verify(a.root, profile, a.snapshot, load(a.runtime) if a.runtime else None,
                                load(a.test_result) if a.test_result else None)
        if a.output:
            if a.command == 'init' and a.output.exists():
                raise ValueError('Existing profile preserved; choose a new output')
            save(a.output, result)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('passed', True) else 1
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'passed': False, 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
