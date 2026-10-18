"""Source/image UI index for the validated WIKA QML layout subset.

Host-side tool; Python 3.8+ and Pillow. Does not execute QML/JavaScript.
"""
from pathlib import Path
import argparse
import ast
import collections
import hashlib
import json
import math
import operator
import random
import re
import sys
import time
import xml.etree.ElementTree as ET

from PIL import Image

SCHEMA = 1
TOKEN = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_$][\w$]*|\d+(?:\.\d+)?|\n|[^\s]', re.UNICODE)


class Unresolved(ValueError):
    pass


def text(path):
    return path.read_text(encoding='utf-8-sig')


def digest(path):
    data = text(path).encode() if path.suffix.lower() in ('.qml', '.js', '.qrc', '.json', '.cpp', '.h') else path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


class Node:
    def __init__(self, kind, line, source, parent=None):
        self.kind, self.line, self.source, self.parent = kind, line, source, parent
        self.props, self.functions, self.handlers, self.children = {}, {}, {}, []

    @property
    def name(self):
        return self.props.get('id', self.kind + '@' + str(self.line))

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def parse_qml(content, source='<memory>'):
    masked = list(content)
    for match in TOKEN.finditer(content):
        if match.group().startswith(('//', '/*')):
            masked[match.start():match.end()] = ['\n' if c == '\n' else ' ' for c in match.group()]
    content = ''.join(masked)
    tokens = [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(content) if not m.group().startswith(('//', '/*'))]
    pairs, stack = {}, []
    for i, (value, _, _) in enumerate(tokens):
        if value in ('{', '[', '('):
            stack.append(i)
        elif value in ('}', ']', ')'):
            if not stack or tokens[stack[-1]][0] != {'}': '{', ']': '[', ')': '('}[value]:
                raise Unresolved('Unbalanced QML: ' + source)
            start = stack.pop()
            pairs[start] = i
    if stack:
        raise Unresolved('Unbalanced QML: ' + source)

    def skip(i):
        while i < len(tokens) and tokens[i][0] in ('\n', ';'):
            i += 1
        return i

    def expression(i, end):
        start = i
        while i < end and tokens[i][0] not in ('\n', ';'):
            i = pairs[i] + 1 if i in pairs else i + 1
        value = content[tokens[start][1]:tokens[i-1][2]].strip() if i > start else ''
        return value, i

    def body(kind, opening, parent=None):
        node = Node(kind, content.count('\n', 0, tokens[opening][1]) + 1, source, parent)
        i, end = opening + 1, pairs[opening]
        while (i := skip(i)) < end:
            value = tokens[i][0]
            if value == 'function':
                name = tokens[i+1][0]
                j = i + 2
                while j < end and tokens[j][0] != '(':
                    j += 1
                j = skip(pairs[j] + 1)
                if tokens[j][0] != '{':
                    raise Unresolved('Unsupported function body: ' + source)
                node.functions[name] = content[tokens[j][2]:tokens[pairs[j]][1]]
                i = pairs[j] + 1
                continue
            j = i + 1
            while j < end and tokens[j][0] == '\n':
                j += 1
            if re.match(r'^[A-Z]\w*$', value) and tokens[j][0] == '{':
                node.children.append(body(value, j, node))
                i = pairs[j] + 1
                continue
            if value in ('readonly', 'required'):
                i += 1
                value = tokens[i][0]
            if value == 'property':
                i += 2
            start = i
            while i < end and (re.match(r'^\w+$', tokens[i][0]) or tokens[i][0] == '.'):
                i += 1
            if i < end and tokens[i][0] == ':' and i > start:
                key = ''.join(t[0] for t in tokens[start:i])
                i += 1
                i = skip(i)
                if tokens[i][0] == '{':
                    node.handlers[key] = content[tokens[i][2]:tokens[pairs[i]][1]]
                    i = pairs[i] + 1
                else:
                    node.props[key], i = expression(i, end)
            else:
                i = start + 1
                while i < end and tokens[i][0] not in ('\n', ';'):
                    i = pairs[i] + 1 if i in pairs else i + 1
        return node

    for i in range(len(tokens)-1):
        if re.match(r'^[A-Z]\w*$', tokens[i][0]):
            j = i + 1
            while j < len(tokens) and tokens[j][0] == '\n':
                j += 1
            if j < len(tokens) and tokens[j][0] == '{':
                return body(tokens[i][0], j)
    raise Unresolved('QML root object not found: ' + source)


def number(expression, lookup):
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
    def visit(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, bool)):
            return node.value
        if isinstance(node, (ast.Name, ast.Attribute)):
            parts = []
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if not isinstance(node, ast.Name):
                raise Unresolved('Unsupported reference')
            return lookup('.'.join([node.id] + list(reversed(parts))))
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            return operations[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        raise Unresolved('Dynamic/unsupported expression: ' + expression)
    try:
        return visit(ast.parse(expression, mode='eval').body)
    except (SyntaxError, KeyError, ZeroDivisionError) as error:
        raise Unresolved('Unresolved expression: ' + expression) from error


def literal_string(value):
    match = re.search(r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')', value or '')
    return ast.literal_eval(match.group()) if match else ''


def navigation_destination(callback):
    tokens = [m.group() for m in TOKEN.finditer(callback) if m.group() != '\n' and not m.group().startswith(('//','/*'))]
    if tokens[:4] != ['iMainWindow', '.', 'showpage', '(']:
        raise Unresolved('Callback is not a single literal navigation call')
    depth, close = 1, None
    for i in range(4, len(tokens)):
        if tokens[i] == '(':
            depth += 1
        elif tokens[i] == ')':
            depth -= 1
            if depth == 0:
                close = i
                break
    if close is None or tokens[close+1:] not in ([], [';']):
        raise Unresolved('Additional callback statements require explicit business testing')
    arguments = ''.join(json.dumps(ast.literal_eval(token),ensure_ascii=False) if token.startswith(('"',"'")) else token for token in tokens[4:close])
    try:
        values = json.loads('[' + arguments + ']')
    except ValueError as error:
        raise Unresolved('Navigation arguments require runtime evaluation') from error
    if not values or not isinstance(values[0], str) or not values[0].startswith('qrc:/'):
        raise Unresolved('Navigation target is not a literal resource URI')
    return values[0]


class Layout:
    """Conservative geometry for numeric bindings, sibling anchors, Row and Grid."""
    def __init__(self, root, frame, constants):
        self.root, self.frame, self.constants = root, frame, constants
        self.ids = {node.name: node for node in root.walk()}
        self.cache, self.active = {}, set()

    def value(self, node, expression):
        def lookup(name):
            if name in ('true', 'false'):
                return name == 'true'
            if name.startswith('CommData.'):
                return self.constants[name[9:]]
            parts = name.split('.')
            if len(parts) == 1 and name in node.props:
                return self.value(node, node.props[name])
            if len(parts) != 2:
                raise Unresolved('Unknown binding: ' + name)
            target = node.parent if parts[0] == 'parent' else self.ids.get(parts[0])
            if target is None:
                raise Unresolved('Unknown item: ' + name)
            value = self.prop(target, parts[1])
            if parts[1] in ('x', 'y'):
                value -= self.prop(target.parent, parts[1]) if target.parent is not None else self.frame[('x','y').index(parts[1])]
            return value
        return number(expression, lookup)

    def prop(self, node, key):
        token = (id(node), key)
        if token in self.cache:
            return self.cache[token]
        if token in self.active:
            raise Unresolved('Cyclic layout binding: ' + node.name + '.' + key)
        self.active.add(token)
        try:
            if node is self.root and key in ('x', 'y', 'width', 'height'):
                value = self.frame[('x', 'y', 'width', 'height').index(key)]
            elif key in ('left', 'top', 'right', 'bottom', 'horizontalCenter', 'verticalCenter'):
                axis, fraction = {'left': ('x', 0), 'right': ('x', 1), 'top': ('y', 0), 'bottom': ('y', 1), 'horizontalCenter': ('x', .5), 'verticalCenter': ('y', .5)}[key]
                value = self.prop(node, axis) + fraction * self.prop(node, 'width' if axis == 'x' else 'height')
            elif key in node.props:
                value = self.value(node, node.props[key])
            elif key in ('width', 'height') and 'anchors.fill' in node.props:
                if node.props['anchors.fill'] != 'parent':
                    raise Unresolved('Unsupported anchors.fill')
                value = self.prop(node.parent, key)
            elif key in ('width', 'height') and node.kind in ('Row', 'Grid'):
                sizes = [self.prop(child, key) for child in node.children]
                spacing = self.value(node, node.props.get('spacing', '0'))
                columns = len(sizes) if node.kind == 'Row' else int(self.value(node, node.props.get('columns', '0')))
                if not columns:
                    raise Unresolved('Grid requires columns')
                count = min(columns, len(sizes)) if key == 'width' else math.ceil(len(sizes)/columns)
                value = (max(sizes) if sizes else 0) * count + max(0, count-1) * spacing
            elif key in ('x', 'y'):
                parent, axis = node.parent, 'width' if key == 'x' else 'height'
                if parent is None:
                    raise Unresolved('Missing parent')
                if parent.kind in ('Row', 'Grid'):
                    if parent.props.get('layoutDirection', 'Qt.LeftToRight') != 'Qt.LeftToRight':
                        raise Unresolved('RTL positioner requires runtime calibration')
                    siblings = parent.children
                    index = siblings.index(node)
                    spacing = self.value(parent, parent.props.get('spacing', '0'))
                    columns = len(siblings) if parent.kind == 'Row' else int(self.value(parent, parent.props.get('columns', '0')))
                    if not columns:
                        raise Unresolved('Grid requires columns')
                    local = sum(self.prop(sibling, 'width') + spacing for sibling in siblings[(index//columns)*columns:index]) if key == 'x' else (index//columns)*(max(self.prop(sibling, 'height') for sibling in siblings)+spacing)
                    value = self.prop(parent, key) + local
                else:
                    start, finish, center = ('left', 'right', 'horizontalCenter') if key == 'x' else ('top', 'bottom', 'verticalCenter')
                    if 'anchors.' + start in node.props:
                        value = self.value(node, node.props['anchors.' + start]) + self.value(node, node.props.get('anchors.' + start + 'Margin', '0'))
                    elif 'anchors.' + finish in node.props:
                        value = self.value(node, node.props['anchors.' + finish]) - self.prop(node, axis) - self.value(node, node.props.get('anchors.' + finish + 'Margin', '0'))
                    elif 'anchors.' + center in node.props:
                        value = self.value(node, node.props['anchors.' + center]) - self.prop(node, axis)/2
                    elif node.props.get('anchors.centerIn') == 'parent':
                        value = self.prop(parent, key) + (self.prop(parent, axis)-self.prop(node, axis))/2
                    else:
                        value = self.prop(parent, key)
            else:
                raise Unresolved('Unknown geometry: ' + node.name + '.' + key)
            if key in ('x', 'y') and node is not self.root and key in node.props:
                value += self.prop(node.parent, key)
            self.cache[token] = value
            return value
        finally:
            self.active.remove(token)

    def rectangle(self, node):
        return [self.prop(node, key) for key in ('x', 'y', 'width', 'height')]

    def interactive(self, node):
        for ancestor in self.ancestors(node):
            for key in ('visible', 'enabled'):
                if not self.value(ancestor, ancestor.props.get(key, 'true')):
                    raise Unresolved('Hidden/disabled: ' + ancestor.name)
            for key, expected in (('scale', 1), ('rotation', 0)):
                if self.value(ancestor, ancestor.props.get(key, str(expected))) != expected:
                    raise Unresolved('Additional transform requires runtime calibration')

    @staticmethod
    def ancestors(node):
        while node is not None:
            yield node
            node = node.parent


class IndexBuilder:
    def __init__(self, root, profile_name='ui-index.json'):
        self.root = Path(root).resolve()
        self.dependencies, self.documents = {}, {}
        self.profile_name = profile_name
        self.profile = json.loads(self.read(profile_name))
        self.constants = {}
        common = re.sub(r'/\*[\s\S]*?\*/|//[^\n]*', '', self.read(self.profile['common']))
        for name, expression in re.findall(r'\bvar\s+(\w+)\s*=\s*([^;\n]+)', common):
            try:
                self.constants[name] = number(expression.strip(), self.constants.__getitem__)
            except Unresolved:
                pass
        self.fb = self.profile['framebuffer_size']
        entry = self.document(self.profile['entry'])
        viewport = next(node for node in entry.walk() if node.name == self.profile['viewport'])
        self.rotation = number(viewport.props.get('rotation', '0'), self.constants.__getitem__) % 360
        if self.rotation not in (0, 90, 180, 270) or viewport.props.get('anchors.centerIn') != 'parent':
            raise Unresolved('Only centered orthogonal viewport transforms are supported')
        self.canvas = list(reversed(self.fb)) if self.rotation in (90, 270) else list(self.fb)
        expected = ('parent.height', 'parent.width') if self.rotation in (90, 270) else ('parent.width', 'parent.height')
        if (viewport.props.get('width'), viewport.props.get('height')) != expected:
            raise Unresolved('Viewport dimensions require explicit runtime calibration')
        self.resources = {}
        self.qrc_files = sorted(p.relative_to(self.root).as_posix() for p in (self.root/self.profile['source_dir']).glob('*.qrc'))
        for name in self.qrc_files:
            xml = ET.fromstring(self.read(name))
            for group in xml.findall('qresource'):
                for node in group.findall('file'):
                    key = 'qrc:/' + '/'.join([group.get('prefix', '').strip('/'), node.get('alias', node.text)]).strip('/')
                    self.resources[key] = str(Path(name).parent/node.text)
        self.references, self.preview = {}, {}
        for page, config in self.profile['pages'].items():
            raw = [self.image(name).convert('RGB') for name in config['captures']]
            if len(raw) < 2 or any(list(im.size) != self.fb for im in raw):
                raise Unresolved('Each page requires two framebuffer-sized captures: ' + page)
            self.references[page] = raw
            self.preview[page] = [im.rotate(self.rotation, expand=True) for im in raw]

    def path(self, name):
        path = (self.root/name).resolve()
        if self.root != path and self.root not in path.parents:
            raise Unresolved('Input outside project root: ' + name)
        return path

    def track(self, name):
        path = self.path(name)
        self.dependencies[path.relative_to(self.root).as_posix()] = digest(path)
        return path

    def read(self, name):
        return text(self.track(name))

    def image(self, name):
        with Image.open(self.track(name)) as image:
            return image.convert('RGBA')

    def document(self, name):
        if name not in self.documents:
            self.documents[name] = parse_qml(self.read(name), name)
        return self.documents[name]

    def to_raw(self, x, y):
        width, height = self.fb
        return {0: (x, y), 90: (width-1-y, x), 180: (width-1-x, height-1-y), 270: (y, height-1-x)}[self.rotation]

    def template(self, page, uri, image_rect):
        if uri not in self.resources:
            raise Unresolved('Resource not found: ' + uri)
        image = self.image(self.resources[uri])
        x, y, width, height = map(int, image_rect)
        if image.size != (width, height):
            raise Unresolved('Scaled image requires runtime calibration: ' + uri)
        pixels = [(px, py, image.getpixel((px, py))) for py in range(0, height, 2) for px in range(0, width, 2)]
        foreground = [(px, py, rgba) for px, py, rgba in pixels if rgba[3] >= 32]
        if len(foreground) < 24:
            raise Unresolved('Insufficient visible resource pixels')
        scores, stable = [], []
        for screenshot in self.preview[page]:
            background = [screenshot.getpixel((x+px, y+py)) for px, py, rgba in pixels if rgba[3] == 0]
            bg = tuple(sorted(p[channel] for p in background)[len(background)//2] for channel in range(3)) if background else (0, 0, 0)
            good = 0
            for px, py, rgba in foreground:
                actual = screenshot.getpixel((x+px, y+py))
                expected = tuple(round((c*rgba[3]+b*(255-rgba[3]))/255) for c, b in zip(rgba[:3], bg))
                good += max(abs(a-b) for a, b in zip(actual, expected)) <= 20
            scores.append(good/len(foreground))
        for px, py, _ in foreground:
            colors = [im.getpixel((x+px, y+py)) for im in self.preview[page]]
            if max(colors[0]) > 40 and all(max(abs(a-b) for a, b in zip(colors[0], rgb)) <= 6 for rgb in colors[1:]):
                rx, ry = self.to_raw(x+px, y+py)
                stable.append([int(rx), int(ry), *colors[0]])
        if min(scores) < .9 or len(stable) < 24:
            raise Unresolved('Source image does not confirm predicted position: scores=' + repr(scores))
        return {'resource': uri, 'scores': scores}, {'points': random.Random(17).sample(stable, min(128, len(stable))), 'tolerance': 20}

    def markers(self, content_top, content_height):
        states = {}
        for page, captures in self.preview.items():
            stable = []
            for y in range(int(content_top+40), int(content_top+content_height-40), 4):
                for x in range(30, self.canvas[0]-30, 4):
                    rgb = captures[0].getpixel((x, y))
                    if max(rgb) <= 40 or any(max(abs(a-b) for a, b in zip(rgb, image.getpixel((x, y)))) > 6 for image in captures[1:]):
                        continue
                    if all(max(abs(a-b) for a, b in zip(rgb, images[0].getpixel((x, y)))) > 50 for name, images in self.preview.items() if name != page):
                        rx, ry = self.to_raw(x, y)
                        stable.append([int(rx), int(ry), *rgb])
            if len(stable) < 256:
                raise Unresolved('Insufficient page-discriminating features: ' + page)
            states[page] = {'points': random.Random(32).sample(stable, 256), 'tolerance': 20}
        return states

    def build(self):
        roles = self.profile['roles']
        base, bar, status = [self.document(roles[key]) for key in ('base', 'bar', 'status')]
        for name in self.profile.get('binding_sources', []):
            self.read(name)
        value = lambda expr: number(expr, lambda key: self.constants[key[9:] if key.startswith('CommData.') else key])
        top = value(status.props['height'])
        content_height, content_width = value(base.props['height']), value(base.props['width'])
        bar_height = value(bar.props['height'])
        if (content_width != self.canvas[0] or top+content_height+bar_height != self.canvas[1]):
            raise Unresolved('Declared page/status/button sizes do not fit calibrated viewport')
        entry = self.document(self.profile['entry'])
        loader = next(n for n in entry.walk() if n.name == self.profile['page_container'])
        bar_instance = next(n for n in entry.walk() if n.name == self.profile['bar_instance'])
        status_instance = next(n for n in entry.walk() if n.kind == 'StatusBar')
        if loader.props.get('anchors.top') != status_instance.name+'.bottom' or bar_instance.props.get('anchors.top') != loader.name+'.bottom':
            raise Unresolved('Page/button anchors require runtime calibration')
        entries = []
        targets = {config['uri']: name for name, config in self.profile['pages'].items()}
        for page, config in self.profile['pages'].items():
            source = self.document(config['source'])
            form = self.document(config.get('form', config['source']))
            if form.kind != 'FormBase':
                raise Unresolved('Configured page form must derive from FormBase')
            if source is not form:
                instances = [n for n in source.walk() if n.kind == Path(config['form']).stem]
                if len(instances) != 1:
                    raise Unresolved('Configured form is not instantiated by page source')
                wrapper = Layout(source, [0, top, content_width, content_height], self.constants)
                wrapper.interactive(instances[0])
                if wrapper.rectangle(instances[0]) != [0, top, content_width, content_height]:
                    raise Unresolved('Page wrapper needs runtime calibration')
                for ancestor in Layout.ancestors(instances[0]):
                    if ancestor.kind == 'SwipeView' and (len(ancestor.children) != 1 or ancestor.props.get('currentIndex', '0') != '0'):
                        raise Unresolved('Dynamic SwipeView page requires runtime calibration')
                self.read(config['form'])
            functions = dict(base.functions, **form.functions)
            for scope, tree, frame in (('content', form, [0, top, content_width, content_height]), ('bar', bar, [0, top+content_height, self.canvas[0], bar_height])):
                layout = Layout(tree, frame, self.constants)
                for node in tree.walk():
                    if node.kind not in self.profile['controls']:
                        continue
                    component = self.document(self.profile['controls'][node.kind])
                    row = {'key': page+'/'+scope+'/'+node.name, 'page': page, 'id': node.name, 'source': node.source, 'line': node.line, 'kind': node.kind, 'status': 'unresolved'}
                    entries.append(row)
                    try:
                        if 'anchors.fill' in node.props and any(key.startswith('anchors.') and key.endswith(('Margin','margins')) for key in node.props):
                            raise Unresolved('Fill margins require runtime calibration')
                        areas = [n for n in component.walk() if n.kind == 'MouseArea']
                        if len(areas) != 1 or areas[0].props.get('anchors.fill') != 'parent' or 'onBtnRelease()' not in areas[0].handlers.get('onReleased', ''):
                            raise Unresolved('Unsupported component touch area/event contract')
                        if any(areas[0].props.get(key, 'true') != 'true' for key in ('visible', 'enabled')):
                            raise Unresolved('Touch area state requires runtime calibration')
                        layout.interactive(node)
                        for key in ('visible', 'enabled', 'scale', 'rotation'):
                            expected = 'true' if key in ('visible', 'enabled') else ('1' if key == 'scale' else '0')
                            if component.props.get(key, expected) != expected:
                                raise Unresolved('Component runtime state requires calibration')
                        rectangle = layout.rectangle(node)
                        x, y, width, height = rectangle
                        if min(x, y, width, height) < 0 or x+width > self.canvas[0] or y+height > self.canvas[1] or not width*height:
                            raise Unresolved('Touch rectangle is outside the visible canvas')
                        callback = node.functions.get('onBtnRelease', '')
                        if scope == 'bar':
                            signal_match = re.search(r'\bsend_F(\d+)_release\s*\(', callback)
                            if not signal_match:
                                raise Unresolved('Button release signal not found')
                            slot = int(signal_match.group(1))
                            if not re.search(r'send_F%d_release\.connect\(adv_F%d_release\)' % (slot, slot), base.functions.get('initializeButtonsFunc', '')):
                                raise Unresolved('Page release connection not found')
                            callback = functions.get('adv_F%d_release' % slot, '')
                            if functions.get('adv_F%d_press' % slot, '').strip():
                                raise Unresolved('Press callback requires explicit business testing')
                            styles = re.findall(r'setButtonPic\(\s*(\d+)\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"', functions.get('initializeButtons', ''))
                            style = next((release for index, _, release in styles if int(index) == slot-1), '')
                            image_rect = rectangle
                        else:
                            if node.functions.get('onBtnPress', component.functions.get('onBtnPress','')).strip():
                                raise Unresolved('Press callback requires explicit business testing')
                            style = literal_string(node.props.get('releaseImage', ''))
                            image_rect = [x, y, layout.value(component, component.props['widthlen']), layout.value(component, component.props['heightlen'])]
                        destination = navigation_destination(callback)
                        row.update(target_uri=destination, target=targets.get(destination), label=literal_string(node.props.get('textbtn.text', '')) or self.profile['pages'].get(targets.get(destination), {}).get('title', destination), callback=callback.strip())
                        if not style:
                            raise Unresolved('No active release image for this page')
                        visual, guard = self.template(page, style, image_rect)
                        click = [int(round(v)) for v in self.to_raw(x+width/2, y+height/2)]
                        row.update(rect=rectangle, click=click, image=visual, guard=guard, status='image_confirmed')
                    except (Unresolved, KeyError, StopIteration, IndexError) as error:
                        row['reason'] = str(error)
        states = self.markers(top, content_height)
        result = {'schema': SCHEMA, 'profile': self.profile_name, 'framebuffer_size': self.fb, 'canvas_size': self.canvas, 'rotation': self.rotation, 'program': self.profile['program'], 'pages': self.profile['pages'], 'controls': entries, 'states': states, 'qrc_files': self.qrc_files, 'dependencies': self.dependencies, 'tool_sha256': digest(Path(__file__).resolve())}
        result['generation_id'] = json_hash(result)
        return result


def freshness(root, index):
    root = Path(root)
    changes = []
    if index.get('schema') != SCHEMA or index.get('tool_sha256') != digest(Path(__file__).resolve()):
        changes.append('indexer version changed')
    for name, expected in index['dependencies'].items():
        path = root/name
        if not path.is_file() or digest(path) != expected:
            changes.append(name)
    profile = json.loads(text(root/index['profile']))
    inventory = sorted(p.relative_to(root).as_posix() for p in (root/profile['source_dir']).glob('*.qrc'))
    if inventory != index['qrc_files']:
        changes.append('resource inventory changed')
    return changes


def make_plan(index, route):
    graph = collections.defaultdict(list)
    for control in sorted(index['controls'], key=lambda row: row['key']):
        if control['status'] == 'image_confirmed' and control.get('target') in index['pages']:
            graph[control['page']].append(control)
    actions = []
    for start, target in zip(route, route[1:]):
        if start not in index['pages'] or target not in index['pages']:
            raise Unresolved('Route uses an unindexed page')
        queue, visited = collections.deque([(start, [])]), {start}
        found = None
        while queue:
            page, path = queue.popleft()
            if page == target:
                found = path
                break
            for edge in graph[page]:
                if edge['target'] not in visited:
                    visited.add(edge['target'])
                    queue.append((edge['target'], path+[edge]))
        if found is None:
            raise Unresolved('No image-confirmed navigation path: '+start+' -> '+target)
        actions.extend(found)
    if not actions:
        raise Unresolved('Route must include an action')
    captures = {name for page in index['pages'].values() for name in page['captures']}
    sources = {name: value for name, value in index['dependencies'].items() if name != index['profile'] and name not in captures}
    result = {'framebuffer_size': index['framebuffer_size'], 'states': index['states'], 'start_state': route[0], 'threshold': .97, 'stable_matches': 2, 'poll_s': .05, 'timeout_s': 4, 'program': index['program'], 'generation_id': index['generation_id'], 'source_sha256': sources, 'steps': [{'name': '%02d-%s' % (i, row['id']), 'control': row['key'], 'from': row['page'], 'target': row['target'], 'click': row['click'], 'guard': row['guard']} for i, row in enumerate(actions)]}
    result['plan_id'] = json_hash(result)
    return result


def record_result(index, plan, result, evidence):
    content = dict(plan)
    identity = content.pop('plan_id')
    if json_hash(content) != identity or plan['generation_id'] != index['generation_id']:
        raise Unresolved('Plan is modified or belongs to another index generation')
    run = result.get('experiment', {}).get('indexed', {})
    if not result.get('passed') or not run.get('passed') or run.get('plan_id') != identity or result.get('test_sha256') != index['program']['sha256']:
        raise Unresolved('Completed live verification for this exact plan/program is required')
    if len(run['steps']) != len(plan['steps']):
        raise Unresolved('Incomplete live step evidence')
    rows = {row['key']: row for row in index['controls']}
    for action, observed in zip(plan['steps'], run['steps']):
        if action['name'] != observed['name'] or observed.get('score', 0) < plan['threshold'] or observed.get('guard_score', 0) < plan['threshold']:
            raise Unresolved('Step identity or guard/page evidence is missing')
        rows[action['control']]['live_verification'] = {'plan_id': identity, 'program_sha256': result['test_sha256'], 'device_stage': result['stage'], 'boot_id': result.get('boot_id'), 'evidence': str(evidence), 'step': action['name'], 'page_score': observed['score'], 'guard_score': observed['guard_score']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'status', 'search', 'plan', 'record'))
    parser.add_argument('root', type=Path)
    parser.add_argument('--profile', default='ui-index.json')
    parser.add_argument('--query', default='')
    parser.add_argument('--page')
    parser.add_argument('--route')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--result', type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    index_path = root/'.ui-index/index.json'
    started = time.perf_counter()
    try:
        old = json.loads(text(index_path)) if index_path.exists() else None
        if args.command == 'build':
            cached = old is not None and old['profile'] == args.profile and not freshness(root, old)
            index = old if cached else IndexBuilder(root, args.profile).build()
            if not cached:
                write_json(index_path, index)
            print(json.dumps({'index': str(index_path), 'cached': cached, 'generation_id': index['generation_id'], 'controls': len(index['controls']), 'image_confirmed': sum(row['status']=='image_confirmed' for row in index['controls']), 'elapsed_ms': round((time.perf_counter()-started)*1000, 2)}, ensure_ascii=False))
            return 0
        if old is None:
            raise Unresolved('Index missing; run build first')
        changes = freshness(root, old)
        if args.command == 'status':
            print(json.dumps({'fresh': not changes, 'changed': changes, 'generation_id': old['generation_id']}, ensure_ascii=False))
            return 1 if changes else 0
        if changes:
            raise Unresolved('Index stale; rebuild before querying coordinates: '+repr(changes))
        if args.command == 'search':
            rows = [row for row in old['controls'] if (not args.page or row['page']==args.page) and args.query.lower() in json.dumps({key: row.get(key) for key in ('key','label','target_uri')}, ensure_ascii=False).lower()]
            print(json.dumps({'matches': [{key: value for key, value in row.items() if key != 'guard'} for row in rows[:20]], 'total': len(rows)}, ensure_ascii=False))
        elif args.command == 'plan':
            if not args.route or args.output is None:
                raise Unresolved('plan requires --route and --output')
            plan = make_plan(old, args.route.split(','))
            write_json(args.output, plan)
            print(json.dumps({'plan_id': plan['plan_id'], 'steps': [{key: value for key, value in row.items() if key != 'guard'} for row in plan['steps']], 'output': str(args.output), 'elapsed_ms': round((time.perf_counter()-started)*1000, 2)}, ensure_ascii=False))
        elif args.command == 'record':
            if args.plan is None or args.result is None:
                raise Unresolved('record requires --plan and --result')
            record_result(old, json.loads(text(args.plan)), json.loads(text(args.result)), args.result.resolve())
            write_json(index_path, old)
            print(json.dumps({'recorded': True, 'live_verified_controls': sum('live_verification' in row for row in old['controls'])}))
        return 0
    except (Unresolved, OSError, ValueError, StopIteration) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
