"""Select regressions, evaluate measured evidence, and render test reports."""
import argparse
import fnmatch
import hashlib
import json
import math
import sys
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def validate_suite(suite):
    ids = [case['id'] for case in suite['cases']]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Test IDs must be nonempty and unique')
    for case in suite['cases']:
        if not case.get('requirement') or not case.get('assertions') or not case.get('scope'):
            raise ValueError('Missing requirement/scope/assertions: ' + case['id'])


def select(suite, changed, mode, impact=()):
    validate_suite(suite)
    paths = sorted(set(p.replace('\\', '/') for p in list(changed) + list(impact)))
    paths = [p[2:] if p.startswith('./') else p for p in paths]
    all_ids = [case['id'] for case in suite['cases']]
    reason = 'release: complete suite'
    if mode == 'release':
        chosen = all_ids
    elif not paths:
        chosen, reason = all_ids, 'no change/impact inventory: complete suite'
    elif any(fnmatch.fnmatchcase(p, rule) for p in paths for rule in suite.get('shared_paths', [])):
        chosen, reason = all_ids, 'shared code/protocol changed: complete suite'
    elif any(not case.get('paths') for case in suite['cases']):
        chosen, reason = all_ids, 'incomplete test dependency mapping: complete suite'
    elif any(not any(fnmatch.fnmatchcase(p, rule) for case in suite['cases'] for rule in case['paths']) for p in paths):
        chosen, reason = all_ids, 'unmapped change: complete suite'
    else:
        chosen = [case['id'] for case in suite['cases'] if case.get('smoke') or any(
            fnmatch.fnmatchcase(p, rule) for p in paths for rule in case['paths'])]
        reason = 'mapped changes/impact plus smoke tests'
    return {'mode': mode, 'suite_id': canonical(suite), 'selected': chosen, 'reason': reason, 'paths': paths}


def value_at(data, path):
    for part in path.split('.'):
        data = data[int(part)] if isinstance(data, list) else data[part]
    return data


def same(actual, expected):
    # bool is not accepted as a measured integer, despite Python's True == 1.
    return type(actual) is type(expected) and json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)


def assertion_passed(rule, observations, frames):
    kind = rule['kind']
    if kind == 'equals':
        return same(value_at(observations, rule['path']), rule['value'])
    if kind == 'near':
        actual = value_at(observations, rule['path'])
        target, tolerance = rule['value'], rule['tolerance']
        return (type(actual) in (int, float) and math.isfinite(actual)
                and type(target) in (int, float) and math.isfinite(target)
                and type(tolerance) in (int, float) and math.isfinite(tolerance)
                and tolerance >= 0 and abs(actual - target) <= tolerance)
    if kind == 'frame':
        payload = bytes.fromhex(rule['data'])
        expected_id = int(str(rule['id']), 16)
        if rule['direction'] not in ('rx', 'tx') or type(rule['extended']) is not bool:
            raise ValueError('Invalid CAN direction or frame format')
        if not 0 <= expected_id <= (0x1fffffff if rule['extended'] else 0x7ff):
            raise ValueError('CAN identifier exceeds frame format')
        if len(payload) > 8 or len(payload) != rule['dlc']:
            raise ValueError('Expected classical CAN payload length differs from DLC')
        for frame in frames:
            if (frame['direction'] == rule['direction'] and frame['extended'] is rule['extended']
                    and frame['origin'] == rule['scope']
                    and int(str(frame['id']), 16) == expected_id and frame['dlc'] == len(payload)
                    and bytes.fromhex(frame['data']) == payload
                    and type(frame['t_ms']) in (int, float) and math.isfinite(frame['t_ms'])
                    and rule['after_ms'] <= frame['t_ms'] <= rule['before_ms']):
                return True
        return False
    raise ValueError('Unknown assertion kind: ' + kind)


def evaluate(suite, evidence, selection, expected_program, evidence_dir, expected_candidate=None):
    validate_suite(suite)
    evidence_dir = Path(evidence_dir).resolve()
    if (not expected_program or len(expected_program) != 64 or not evidence.get('run_id')
            or evidence.get('program_sha256') != expected_program):
        raise ValueError('Missing run ID or wrong program fingerprint')
    if evidence.get('suite_id') != canonical(suite):
        raise ValueError('Evidence belongs to a different test suite')
    if expected_candidate is not None and evidence.get('candidate_id') != expected_candidate:
        raise ValueError('Evidence belongs to a different candidate/configuration')
    if evidence.get('execution') not in ('live', 'replay'):
        raise ValueError('Declare execution as live or replay')
    if selection['suite_id'] != canonical(suite):
        raise ValueError('Test suite changed since selection')
    selected = selection['selected']
    if not selected or not set(selected) <= {case['id'] for case in suite['cases']}:
        raise ValueError('Invalid selected test IDs')
    if selection['mode'] == 'release' and set(selected) != {case['id'] for case in suite['cases']}:
        raise ValueError('Release selection must cover the complete suite')
    sources = evidence.get('sources', {})
    for label, source in sources.items():
        path = (evidence_dir / source['path']).resolve()
        path.relative_to(evidence_dir)
        if sha(path) != source['sha256']:
            raise ValueError('Evidence source changed: ' + label)
    rows = []
    for case in suite['cases']:
        if case['id'] not in selected:
            rows.append({'id': case['id'], 'requirement': case['requirement'], 'status': '未测', 'reason': '未选入本轮开发回归'})
            continue
        measured = evidence.get('cases', {}).get(case['id'])
        row = {'id': case['id'], 'requirement': case['requirement'], 'scope': case['scope'], 'status': '未测'}
        rows.append(row)
        if measured is None:
            row['reason'] = '缺少本轮实测数据'
            continue
        row['sources'] = measured.get('sources', [])
        if measured.get('scope') != case['scope'] or not row['sources'] or any(label not in sources for label in row['sources']):
            row['reason'] = '验证层级或原始证据不完整'
            continue
        try:
            checks = [assertion_passed(dict(rule, scope=case['scope']), measured.get('observations', {}), measured.get('frames', []))
                      for rule in case['assertions']]
            row.update(status='通过' if all(checks) else '未通过', checks=checks)
        except (ValueError, TypeError, KeyError, IndexError) as error:
            row.update(status='未通过', reason=str(error))
    passed = all(row['status'] == '通过' for row in rows if row['id'] in selected)
    release_ready = (expected_candidate is not None and evidence['execution'] == 'live'
                     and selection['mode'] == 'release' and all(row['status'] == '通过' for row in rows))
    return {'run_id': evidence['run_id'], 'program_sha256': expected_program,
            'candidate_id': expected_candidate, 'suite_id': selection['suite_id'],
            'mode': selection['mode'], 'execution': evidence['execution'], 'passed': passed,
            'release_ready': release_ready, 'cases': rows, 'sources': sources,
            'timings_ms': evidence.get('timings_ms', {})}


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def report(result):
    lines = ['# 自动测试记录', '', '- 运行编号：' + result['run_id'],
             '- 程序 SHA256：' + result['program_sha256'], '- 回归模式：' + result['mode'],
             '- 可交付：' + ('是' if result['release_ready'] else '否'), '',
             '| 测试项 | 需求 | 验证范围 | 结果 | 原因/证据 |', '| --- | --- | --- | --- | --- |']
    for row in result['cases']:
        evidence = ', '.join(result['sources'][name]['path'] for name in row.get('sources', []))
        lines.append('| ' + ' | '.join(cell(x) for x in (row['id'], row['requirement'], row.get('scope', ''),
                     row['status'], row.get('reason', evidence))) + ' |')
    lines += ['', '## 分阶段计时（毫秒）', '']
    lines += ['- ' + cell(name) + ': ' + cell(value) for name, value in result.get('timings_ms', {}).items()]
    return '\n'.join(lines) + '\n'


def update_doc(path, result):
    path = Path(path)
    rows = {row['id']: row for row in result['cases']}
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith('|'):
            columns = [part.strip() for part in line.strip().strip('|').split('|')]
            if len(columns) == 7 and columns[0] in rows:
                row = rows[columns[0]]
                columns[5] = row['status']
                # Preserve the human's notes and append evidence instead of replacing them.
                note = 'run=' + result['run_id'] + '; ' + row.get('reason', ', '.join(row.get('sources', [])))
                if note not in columns[6]:
                    columns[6] = (columns[6] + '; ' + cell(note)).strip('; ')
                lines[i] = '| ' + ' | '.join(columns) + ' |'
    marker = '<!-- wika-flow-run:' + result['run_id'] + ' -->'
    if marker not in lines:
        lines += ['', marker, report(result)]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def previews(evidence_dir, output, names):
    from PIL import Image, ImageOps
    evidence_dir, output = Path(evidence_dir).resolve(), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for i, name in enumerate(names):
        original = (evidence_dir / name).resolve()
        original.relative_to(evidence_dir)
        target = output / ('%03d.jpg' % i)
        with Image.open(original) as image:
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((320, 320))
            image.save(target, quality=80)
        entries.append({'original': name, 'original_sha256': sha(original), 'original_bytes': original.stat().st_size,
                        'preview': target.name, 'preview_sha256': sha(target), 'preview_bytes': target.stat().st_size})
    index = {'files': entries, 'original_bytes': sum(x['original_bytes'] for x in entries),
             'preview_bytes': sum(x['preview_bytes'] for x in entries)}
    (output / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
    return index


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=('select', 'evaluate', 'report', 'previews'))
    ap.add_argument('--suite', type=Path)
    ap.add_argument('--mode', choices=('dev', 'release'), default='dev')
    ap.add_argument('--changed', nargs='*', default=[])
    ap.add_argument('--impact', nargs='*', default=[])
    ap.add_argument('--selection', type=Path)
    ap.add_argument('--evidence', type=Path)
    ap.add_argument('--program-sha256')
    ap.add_argument('--manifest', type=Path)
    ap.add_argument('--result', type=Path)
    ap.add_argument('--update-doc', type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--images', nargs='*', default=[])
    a = ap.parse_args()
    try:
        if a.command == 'select':
            result = select(load(a.suite), a.changed, a.mode, a.impact)
        elif a.command == 'evaluate':
            manifest = load(a.manifest) if a.manifest else {}
            result = evaluate(load(a.suite), load(a.evidence), load(a.selection),
                              manifest.get('program_sha256', a.program_sha256), a.evidence.parent, manifest.get('candidate_id'))
        elif a.command == 'report':
            result = load(a.result)
            a.output.write_text(report(result), encoding='utf-8')
            if a.update_doc:
                update_doc(a.update_doc, result)
            print(json.dumps({'report': str(a.output), 'release_ready': result['release_ready']}))
            return 0
        else:
            result = previews(a.evidence, a.output, a.images)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
        success = result.get('passed', True)
        if a.command == 'evaluate' and result.get('mode') == 'release':
            success = success and result.get('release_ready', False)
        return 0 if success else 1
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'passed': False, 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
