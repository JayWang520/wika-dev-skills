"""Temporary ICM7100 UI batching/readiness probe; no Qt source changes."""
from pathlib import Path
import json
import os
import struct
import sys
import time
import zlib


class Framebuffer:
    def __init__(self):
        import fcntl
        self.fcntl = fcntl
        self.fd = os.open('/dev/fb0', os.O_RDONLY)
        fix = bytearray(68)
        fcntl.ioctl(self.fd, 0x4602, fix, True)
        self.stride = struct.unpack_from('I', fix, 44)[0]
        var = self._var()
        self.width, self.height = var[:2]
        self.channels = [var[8:11], var[11:14], var[14:17]]
        assert var[6] == 32 and all(length == 8 and not reverse for _, length, reverse in self.channels)

    def _var(self):
        var = bytearray(160)
        self.fcntl.ioctl(self.fd, 0x4600, var, True)
        return struct.unpack_from('20I', var)

    def read(self):
        var = self._var()
        os.lseek(self.fd, var[5] * self.stride, os.SEEK_SET)
        blocks, remaining = [], self.height * self.stride
        while remaining:
            block = os.read(self.fd, remaining)
            if not block:
                raise RuntimeError('Incomplete framebuffer')
            blocks.append(block)
            remaining -= len(block)
        self.xoffset = var[4]
        return b''.join(blocks)

    def pixel(self, raw, x, y):
        start = y * self.stride + (self.xoffset + x) * 4
        return tuple(raw[start + offset // 8] for offset, _, _ in self.channels)

    def png(self, raw):
        pixels = bytearray()
        for y in range(self.height):
            start = y * self.stride + self.xoffset * 4
            row = raw[start:start + self.width * 4]
            rgb = bytearray(self.width * 3)
            for channel, (offset, _, _) in enumerate(self.channels):
                rgb[channel::3] = row[offset // 8::4]
            pixels.extend(b'\0')
            pixels.extend(rgb)
        def chunk(kind, data):
            return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
        return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', self.width, self.height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(pixels, 6)) + chunk(b'IEND', b'')

    def close(self):
        os.close(self.fd)


class Touch:
    def __init__(self, width, height):
        import fcntl
        self.fd = os.open('/dev/input/event1', os.O_RDWR | os.O_NONBLOCK)
        self.extents = (width - 1, height - 1)
        self.ranges = []
        self.contact = 31000
        for axis in (53, 54):
            data = bytearray(24)
            fcntl.ioctl(self.fd, 0x80184540 + axis, data, True)
            _, low, high, _, _, _ = struct.unpack('6i', data)
            self.ranges.append((low, high))

    def event(self, kind, code, value):
        now = time.time()
        os.write(self.fd, struct.pack('<llHHi', int(now), int(now % 1 * 1000000), kind, code, value))

    def release(self):
        for args in ((3, 47, 0), (3, 57, -1), (1, 330, 0), (0, 0, 0)):
            self.event(*args)

    def click(self, point):
        if len(point) != 2 or any(value < 0 or value > extent for value, extent in zip(point, self.extents)):
            raise ValueError('Click outside framebuffer coordinates')
        xy = [int(low + value / extent * (high - low)) for value, extent, (low, high) in zip(point, self.extents, self.ranges)]
        self.contact += 1
        for args in ((3, 47, 0), (3, 57, self.contact), (3, 48, 10), (3, 50, 10), (3, 53, xy[0]), (3, 54, xy[1]), (3, 0, xy[0]), (3, 1, xy[1]), (1, 330, 1), (0, 0, 0)):
            self.event(*args)
        time.sleep(0.12)
        self.release()

    def close(self):
        try:
            self.release()
        finally:
            os.close(self.fd)


def match_score(framebuffer, raw, marker):
    tolerance = marker.get('tolerance', 20)
    points = marker['points']
    good = sum(max(abs(a-b) for a, b in zip(framebuffer.pixel(raw, x, y), rgb)) <= tolerance for x, y, *rgb in points)
    return good / len(points)


def run_flow(plan, framebuffer, touch, output, fixed_wait=None, clock=time.monotonic, sleep=time.sleep):
    output.mkdir(parents=True, exist_ok=True)
    result = {'mode': 'fixed_wait' if fixed_wait is not None else 'page_readiness', 'steps': [], 'passed': False}
    if 'plan_id' in plan:
        result['plan_id'] = plan['plan_id']
    started = clock()
    try:
        assert (framebuffer.width, framebuffer.height) == tuple(plan['framebuffer_size'])
        initial = framebuffer.read()
        score = match_score(framebuffer, initial, plan['states'][plan['start_state']])
        result['initial_score'] = score
        if score < plan.get('threshold', 0.97):
            (output / 'unexpected-start.png').write_bytes(framebuffer.png(initial))
            raise RuntimeError('Unexpected start page; no touches sent')
        for number, step in enumerate(plan['steps']):
            row = {'name': step['name'], 'target': step['target']}
            result['steps'].append(row)
            step_start = clock()
            if 'guard' in step:
                before = framebuffer.read()
                row['guard_score'] = match_score(framebuffer, before, step['guard'])
                if row['guard_score'] < plan.get('threshold', 0.97):
                    (output / ('guard-failed-%02d.png' % number)).write_bytes(framebuffer.png(before))
                    raise RuntimeError('Expected control is not visible; remaining touches stopped')
                row['guard_ms'] = round((clock()-step_start)*1000, 2)
            touch_start = clock()
            touch.click(step['click'])
            released = clock()
            row['touch_ms'] = round((released-touch_start)*1000, 2)
            if fixed_wait is not None:
                sleep(fixed_wait)
            deadline = clock() + plan.get('timeout_s', 4)
            consecutive = 0
            while True:
                raw = framebuffer.read()
                row['score'] = match_score(framebuffer, raw, plan['states'][step['target']])
                if row['score'] >= plan.get('threshold', 0.97):
                    consecutive += 1
                else:
                    consecutive = 0
                if consecutive >= (1 if fixed_wait is not None else plan.get('stable_matches', 2)):
                    break
                if clock() >= deadline:
                    (output / ('failed-%02d.png' % number)).write_bytes(framebuffer.png(raw))
                    raise TimeoutError('Expected page not ready: '+step['target'])
                sleep(plan.get('poll_s', 0.05))
            row['ready_wait_ms'] = round((clock()-released)*1000, 2)
            capture_start = clock()
            filename = '%02d-%s.png' % (number, step['name'])
            (output / filename).write_bytes(framebuffer.png(raw))
            row['capture_ms'] = round((clock()-capture_start)*1000, 2)
            row['elapsed_ms'] = round((clock()-step_start)*1000, 2)
            row['screenshot'] = filename
        result['passed'] = True
    except Exception as error:
        result['error'] = repr(error)
    finally:
        result['elapsed_ms'] = round((clock()-started)*1000, 2)
        (output / 'result.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    plan_path = Path(sys.argv[1])
    plan = json.loads(plan_path.read_text())
    framebuffer = Framebuffer()
    touch = None
    try:
        touch = Touch(framebuffer.width, framebuffer.height)
        result = run_flow(plan, framebuffer, touch, plan_path.parent / sys.argv[2], fixed_wait=2.0 if len(sys.argv)>3 and sys.argv[3]=='fixed' else None)
        print(json.dumps(result))
        sys.exit(0 if result['passed'] else 1)
    finally:
        if touch is not None:
            touch.close()
        framebuffer.close()
