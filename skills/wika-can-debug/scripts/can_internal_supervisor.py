"""Bound the temporary probe and restore the previous UI and CAN settings."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

stage = Path(sys.argv[1])

def run(args):
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=12)
        return {'args': args, 'return_code': p.returncode, 'output': p.stdout.decode(errors='replace')}
    except subprocess.TimeoutExpired:
        return {'args': args, 'return_code': 124, 'output': 'Command timed out'}
    except OSError as error:
        return {'args': args, 'return_code': 127, 'output': str(error)}

def hashes():
    return {name: hashlib.sha256((Path('/apps') / name).read_bytes()).hexdigest() for name in ('myapp', 'can0.eds', 'can0.h', 'can0.var', 'Database.db', 'logo.bin') if (Path('/apps') / name).is_file()}

before = {'can0': run(['/sbin/ip', '-details', 'link', 'show', 'can0'])['output'], 'hashes': hashes(), 'units': []}
assert 'LOOPBACK' not in before['can0'], 'Expected original CAN mode'
for unit in ('wika-app.service', 'buildlink-tz956e-v101-test.service'):
    if run(['systemctl', 'is-active', unit])['output'].strip() == 'active':
        before['units'].append(unit)
assert len(before['units']) == 1, before['units']
timing = re.search(r'tq (\d+) prop-seg (\d+) phase-seg1 (\d+) phase-seg2 (\d+) sjw (\d+)', before['can0'])
assert timing, before['can0']
timing_args = [value for pair in zip(('tq', 'prop-seg', 'phase-seg1', 'phase-seg2', 'sjw'), timing.groups()) for value in pair]
restart = re.search(r'restart-ms (\d+)', before['can0']).group(1)
queue = re.search(r'qlen (\d+)', before['can0']).group(1)
was_up = 'UP' in before['can0'].splitlines()[0].split('<', 1)[1].split('>', 1)[0].split(',')
(stage / 'before.json').write_text(json.dumps(before, indent=2))
child = None
out = {'commands': [], 'restore_commands': []}
try:
    for unit in before['units']:
        p = run(['systemctl', 'stop', unit])
        out['commands'].append(p)
        assert p['return_code'] == 0, p
    for args in (['link', 'set', 'can0', 'down'], ['link', 'set', 'can0', 'type', 'can', 'loopback', 'on'], ['link', 'set', 'can0', 'up']):
        p = run(['/sbin/ip'] + args)
        out['commands'].append(p)
        assert p['return_code'] == 0, p
    with (stage / 'probe.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, str(stage / 'can_internal_sdk_probe.py'), str(stage)], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        out['probe_exit_code'] = child.wait(timeout=40)
except Exception as error:
    out['error'] = repr(error)
finally:
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    restore = [
        ['/sbin/ip', 'link', 'set', 'can0', 'down'],
        ['/sbin/ip', 'link', 'set', 'can0', 'type', 'can', 'loopback', 'off'] + timing_args + ['restart-ms', restart],
        ['/sbin/ip', 'link', 'set', 'can0', 'txqueuelen', queue],
    ]
    if was_up:
        restore.append(['/sbin/ip', 'link', 'set', 'can0', 'up'])
    restore.extend(['systemctl', 'start', unit] for unit in before['units'])
    for args in restore:
        out['restore_commands'].append(run(args))
    out['after_can0'] = run(['/sbin/ip', '-details', 'link', 'show', 'can0'])['output']
    out['services'] = {unit: run(['systemctl', 'show', unit, '-p', 'MainPID', '-p', 'ActiveState', '-p', 'SubState']) for unit in before['units']}
    out['after_hashes'] = hashes()
    out['files_unchanged'] = out['after_hashes'] == before['hashes']
    (stage / 'restored.json').write_text(json.dumps(out, indent=2))
