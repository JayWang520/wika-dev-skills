"""Temporary on-device CAN loopback experiment; not a production simulator."""
from pathlib import Path
import ctypes
import json
import socket
import struct
import subprocess
import sys
import time

stage = Path(sys.argv[1])
result = {'mode': 'controller_internal_loopback', 'external_can_tool_used': False, 'samples': []}
lib = ctypes.CDLL('/usr/lib/libhsm.so')
for name, args in {
    'canopen_baud_rate': [ctypes.c_int, ctypes.c_int],
    'canopen_start': [ctypes.c_int, ctypes.c_int, ctypes.c_char_p],
    'canopen_j1939_mode': [ctypes.c_int, ctypes.c_int],
    'canopen_start_node': [ctypes.c_int, ctypes.c_int],
    'canopen_read_var_int': [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)],
    'canopen_read_int': [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)],
    'canopen_write_var_int': [ctypes.c_int, ctypes.c_int, ctypes.c_uint32],
    'canopen_send_pdo': [ctypes.c_int, ctypes.c_int],
}.items():
    fn = getattr(lib, name)
    fn.argtypes = args
    fn.restype = ctypes.c_int
lib.canopen_stop.argtypes = [ctypes.c_int]
lib.canopen_stop.restype = None

def interface_state():
    return subprocess.check_output(['/sbin/ip', '-details', '-statistics', 'link', 'show', 'can0']).decode()

def read_values():
    kind = ctypes.c_int()
    return {
        'variables': [lib.canopen_read_var_int(0, i, ctypes.byref(kind)) for i in range(8)],
        'objects': [lib.canopen_read_int(0, 0x2000, i + 1, ctypes.byref(kind)) for i in range(8)],
    }

sender = observer = None
started = False
try:
    rc = result['initialization'] = {'baud': lib.canopen_baud_rate(0, 250000)}
    rc['start'] = lib.canopen_start(0, 0x10, str(stage / 'can0.eds').encode())
    started = rc['start'] == 0
    rc['extended'] = lib.canopen_j1939_mode(0, 1)
    result['after_sdk_start'] = interface_state()
    if 'LOOPBACK' not in result['after_sdk_start']:
        for args in (['link', 'set', 'can0', 'down'], ['link', 'set', 'can0', 'type', 'can', 'loopback', 'on'], ['link', 'set', 'can0', 'up']):
            subprocess.run(['/sbin/ip'] + args, check=True)
    result['test_interface'] = interface_state()
    assert 'LOOPBACK' in result['test_interface'], 'Controller loopback is not active'
    rc['start_node'] = lib.canopen_start_node(0, 0x10)
    assert all(value == 0 for value in rc.values()), rc
    observer = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    filters = b''.join(struct.pack('=II', can_id | 0x80000000, 0xDFFFFFFF) for can_id in (0x18FA10EF, 0x18FFAAE5, 0x18FFABE5))
    observer.setsockopt(socket.SOL_CAN_RAW, 1, filters)
    observer.bind(('can0',))
    observer.settimeout(0.05)
    sender = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sender.bind(('can0',))

    def drain(duration):
        frames = []
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            try:
                raw, _, flags, _ = observer.recvmsg(16)
                can_id, length = struct.unpack_from('=IB', raw)
                frames.append({'id': '%08X' % (can_id & 0x1FFFFFFF), 'extended': bool(can_id & 0x80000000), 'dlc': length, 'data': raw[8:8+length].hex().upper(), 'message_flags': flags})
            except socket.timeout:
                pass
        return frames

    def send(can_id, payload):
        raw = struct.pack('=IB3x8s', can_id | 0x80000000, len(payload), payload)
        assert sender.send(raw) == 16

    result['baseline'] = read_values()
    drain(0.15)
    send(0x18FA10EF, bytes.fromhex('A1A2A3A4A5A6A7A8'))
    result['negative_frames'] = drain(0.4)
    result['after_old_id'] = read_values()
    assert any(frame['id'] == '18FA10EF' for frame in result['negative_frames'])
    assert result['after_old_id'] == result['baseline'], 'Old ID unexpectedly changed the mapped object'
    for hex_data in ('1122334455667788', 'DEADBEEF01234567'):
        payload = bytes.fromhex(hex_data)
        expected = list(payload)
        drain(0.1)
        send(0x18FFAAE5, payload)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            values = read_values()
            if values['variables'] == expected and values['objects'] == expected:
                break
            time.sleep(0.02)
        sample = {'payload': hex_data, 'received': values, 'input_frames': drain(0.15)}
        result['samples'].append(sample)
        assert values['variables'] == expected and values['objects'] == expected, sample
        sample['write_returns'] = [lib.canopen_write_var_int(0, 129 + i, value) for i, value in enumerate(payload)]
        sample['send_return'] = lib.canopen_send_pdo(0, 1)
        sample['output_frames'] = drain(0.4)
        assert all(code == 0 for code in sample['write_returns']) and sample['send_return'] == 0, sample
        assert any(frame['id'] == '18FFABE5' and frame['data'] == hex_data and frame['extended'] and frame['dlc'] == 8 for frame in sample['output_frames']), sample
    result['final_interface'] = interface_state()
    assert 'LOOPBACK' in result['final_interface']
    result['passed'] = True
except Exception as error:
    result['passed'] = False
    result['error'] = repr(error)
    raise
finally:
    if sender is not None:
        sender.close()
    if observer is not None:
        observer.close()
    if started:
        lib.canopen_stop(0)
    (stage / 'result.json').write_text(json.dumps(result, indent=2))
