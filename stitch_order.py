#!/usr/bin/env python3
"""Stitch Order.

Sets the order Ink/Stitch sews objects in without moving them in their
layers and groups. Each object (or group) gets a number, stored on it as
trlo:stitch_order. Preview and Export build a temporary copy of the
document with the objects rearranged into that order and hand the copy to
Ink/Stitch's own simulator or file export. The open document is never
rearranged.

How the copy is built: every object Ink/Stitch would sew is taken out of
its group and put, in the new order, inside fresh copies of the groups it
was in (same transforms, styles and clips), so it sits in exactly the same
place and looks the same. Objects next to each other in the new order that
came from the same group share one copy of that group.
"""

import copy
import json
import os
import subprocess
import tempfile
import time
import warnings

import inkex
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
INKSTITCH = os.path.join(HERE, '..', 'inkstitch', 'bin', 'inkstitch')

# Same namespace as Expanded Groups.
inkex.NSS['trlo'] = 'http://theroadlessordinary.com/namespace'
etree.register_namespace('trlo', inkex.NSS['trlo'])
inkex.NSS.setdefault('inkstitch', 'http://inkstitch.org/namespace')
ORDER_ATTR = inkex.addNS('stitch_order', 'trlo')
SVG_SUFFIX = ' - stitch order'

# After every change the full order (object ids) is written here, so an open
# Expanded Groups window can update its Stitch Order entry.
ORDER_RECORD_PATH = os.path.join(tempfile.gettempdir(), 'stitch_order_last.json')

# Expanded Groups writes a new order here (object ids, after a drag) just
# before running the hidden Reorder action. Ignored when older than
# PENDING_MAX_AGE seconds, so a run that never happened can't apply later.
ORDER_PENDING_PATH = os.path.join(tempfile.gettempdir(), 'stitch_order_pending.json')
PENDING_MAX_AGE = 30

SVG = inkex.NSS['svg']
EMBROIDERABLE = {f'{{{SVG}}}{t}' for t in
                 ('path', 'line', 'polyline', 'polygon', 'rect', 'ellipse', 'circle')}
USE_TAG = f'{{{SVG}}}use'
CONTAINERS = {f'{{{SVG}}}{t}' for t in ('g', 'a', 'switch', 'svg')}
KEEP_TAGS = {f'{{{SVG}}}{t}' for t in ('defs', 'metadata', 'style', 'title', 'desc')} | {
    inkex.addNS('namedview', 'sodipodi')}
SKIPPED = {f'{{{SVG}}}{t}' for t in ('defs', 'mask', 'clipPath', 'metadata')}
HREF = inkex.addNS('href', 'xlink')
CONN_START = inkex.addNS('connection-start', 'inkscape')
CONN_END = inkex.addNS('connection-end', 'inkscape')
GROUPMODE = inkex.addNS('groupmode', 'inkscape')
LABEL = inkex.addNS('label', 'inkscape')


# -- order tags ---------------------------------------------------------------

def doc_index(root):
    return {node: i for i, node in enumerate(root.iter())}


def tagged_in_order(root):
    """Tagged elements, by number, ties broken by document order."""
    index = doc_index(root)
    tagged = []
    for node in root.iter():
        value = node.get(ORDER_ATTR) if isinstance(node.tag, str) else None
        if value is None:
            continue
        try:
            number = float(value)
        except ValueError:
            continue
        tagged.append((number, index[node], node))
    return [node for _, _, node in sorted(tagged, key=lambda t: (t[0], t[1]))]


def write_order(nodes):
    for number, node in enumerate(nodes, start=1):
        node.set(ORDER_ATTR, str(number))


def describe(node):
    label = node.get(LABEL)
    name = f'{label} ({node.get_id()})' if label else node.get_id()
    if node.tag in CONTAINERS:
        count = sum(1 for n in node.iter() if n.tag in EMBROIDERABLE or n.tag == USE_TAG)
        kind = 'layer' if node.get(GROUPMODE) == 'layer' else 'group'
        name += f', {kind} of {count}'
    return name


# -- what gets moved -----------------------------------------------------------

def is_symbol_use(node):
    return node.tag == USE_TAG and (node.get(HREF) or '').startswith('#inkstitch_')


def sewn_objects(root):
    """Every object Ink/Stitch might sew, in document order: drawn shapes and
    clones outside defs, masks and clip paths, but not Ink/Stitch command
    symbols or their connectors. Whether each one is actually sewn (hidden,
    ignored) is left to Ink/Stitch: the copy keeps everything it reads."""
    found = []

    def walk(node):
        if not isinstance(node.tag, str) or node.tag in SKIPPED:
            return
        if node.get(CONN_START) is not None or node.get(CONN_END) is not None:
            return
        if node.tag in EMBROIDERABLE or (node.tag == USE_TAG and not is_symbol_use(node)):
            found.append(node)
        elif node.tag in CONTAINERS:
            for child in node:
                walk(child)

    for child in root:
        walk(child)
    return found


# -- the rearranged copy -------------------------------------------------------

def effective_number(node, root):
    """The object's own number, or the nearest numbered group above it."""
    while node is not None and node is not root:
        value = node.get(ORDER_ATTR)
        if value is not None:
            try:
                return float(value)
            except ValueError:
                pass
        node = node.getparent()
    return None


def ordered_copy(document, only_ordered=False):
    """A copy of the document rearranged into stitch order, plus how many
    objects it sews. Objects without a number are left out. With
    only_ordered, nothing else is kept either: no other layers or groups,
    no Ink/Stitch stitch plan or command symbols; only the numbered objects
    in copies of their groups, plus the document's defs and settings."""
    doc = copy.deepcopy(document)
    root = doc.getroot()
    objects = sewn_objects(root)

    numbered, loose = [], []
    for i, node in enumerate(objects):
        number = effective_number(node, root)
        (loose if number is None else numbered).append((number, i, node))
    numbered.sort(key=lambda t: (t[0], t[1]))
    numbered = [node for _, _, node in numbered]
    loose = [node for _, _, node in loose]

    for node in loose:
        node.getparent().remove(node)
    order = numbered

    # Ancestor chains are read before anything moves.
    chains = {}
    for node in order:
        chain = [a for a in node.iterancestors() if a is not root]
        chains[node] = list(reversed(chain))

    used_ids = {n.get('id') for n in root.iter() if isinstance(n.tag, str)}
    counter = [0]

    def unique(base):
        while True:
            counter[0] += 1
            new_id = f'{base}-so{counter[0]}'
            if new_id not in used_ids:
                used_ids.add(new_id)
                return new_id

    def wrapper_for(orig):
        w = root.makeelement(orig.tag, {k: v for k, v in orig.attrib.items()
                                        if k not in ('id', ORDER_ATTR)})
        new_id = unique(orig.get('id') or 'g')
        w.set('id', new_id)
        # An "ignore layer" command must sit inside the layer it ignores.
        if orig.get(GROUPMODE) == 'layer':
            for cmd in orig.iter(USE_TAG):
                if (cmd.get(HREF) or '') == '#inkstitch_ignore_layer':
                    dup = copy.deepcopy(cmd)
                    dup.set('id', unique(dup.get('id') or 'use'))
                    w.append(dup)
        return w

    first_new = len(root)   # everything appended after this is the new order
    stack = []  # (original ancestor, its copy), outermost first
    for node in order:
        chain = chains[node]
        keep = 0
        while keep < len(stack) and keep < len(chain) and stack[keep][0] is chain[keep]:
            keep += 1
        del stack[keep:]
        parent = stack[-1][1] if stack else root
        for orig in chain[keep:]:
            w = wrapper_for(orig)
            parent.append(w)
            stack.append((orig, w))
            parent = w
        parent.append(node)

    if only_ordered:
        for child in list(root)[:first_new]:
            if not isinstance(child.tag, str) or child.tag not in KEEP_TAGS:
                root.remove(child)

    return doc, len(order)


def spawn_detached(argv):
    """Start argv fully detached (double fork), so Inkscape does not wait for
    it and this script leaves no child process behind."""
    # Python warns about fork() in a multi-threaded process; Inkscape would
    # show that warning in a dialog in front of the simulator.
    warnings.simplefilter('ignore')
    pid = os.fork()
    if pid == 0:
        try:
            os.setsid()
            devnull = os.open(os.devnull, os.O_RDWR)
            for fd in (0, 1, 2):
                os.dup2(devnull, fd)
            if os.fork() == 0:
                os.execv(argv[0], argv)
        finally:
            os._exit(0)
    os.waitpid(pid, 0)


# -- the extension -------------------------------------------------------------

class StitchOrder(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument('--action', default='list')
        pars.add_argument('--place', default='position')
        pars.add_argument('--position', type=int, default=1)
        pars.add_argument('--format', default='dst')
        pars.add_argument('--output_path', default='')
        pars.add_argument('--sel_order', default='document')

    def selected(self, click_order=False):
        nodes = [n for n in self.svg.selection.values() if n is not self.svg]
        if not nodes:
            raise inkex.AbortExtension('Select the objects or groups first.')
        if click_order:
            return nodes  # the order Inkscape passed them: click order
        # Document order, not click order.
        index = doc_index(self.document.getroot())
        nodes.sort(key=lambda n: index.get(n, len(index)))
        return nodes

    def effect(self):
        action = self.options.action
        root = self.document.getroot()
        if action == 'add':
            sel = self.selected(click_order=self.options.sel_order == 'click')
            write_order([n for n in tagged_in_order(root) if n not in sel] + sel)
        elif action == 'insert':
            sel = self.selected()
            rest = [n for n in tagged_in_order(root) if n not in sel]
            if self.options.place == 'start':
                at = 0
            elif self.options.place == 'end':
                at = len(rest)
            else:
                at = max(0, min(self.options.position - 1, len(rest)))
            write_order(rest[:at] + sel + rest[at:])
        elif action == 'remove':
            sel = self.selected()
            for node in sel:
                node.attrib.pop(ORDER_ATTR, None)
            write_order(tagged_in_order(root))
        elif action == 'clear':
            for node in tagged_in_order(root):
                node.attrib.pop(ORDER_ATTR, None)
        elif action == 'reorder':
            self.reorder(root)
        elif action == 'list':
            self.list_order(root)
        elif action == 'preview':
            self.preview()
        elif action == 'export':
            self.export()
        else:
            raise inkex.AbortExtension(f'Unknown action: {action}')
        if action in ('add', 'insert', 'remove', 'clear', 'reorder'):
            self.record_order(root)

    def reorder(self, root):
        """Renumber in the order Expanded Groups left in ORDER_PENDING_PATH.
        Numbered objects missing from that list keep their order, after it."""
        try:
            with open(ORDER_PENDING_PATH) as f:
                rec = json.load(f)
            os.remove(ORDER_PENDING_PATH)
        except (OSError, ValueError):
            raise inkex.AbortExtension('No new stitch order was given.')
        if time.time() - rec.get('time', 0) > PENDING_MAX_AGE:
            raise inkex.AbortExtension('The new stitch order arrived too late; drag again.')
        current = tagged_in_order(root)
        by_id = {n.get_id(): n for n in current}
        first = [by_id[i] for i in rec.get('ids', []) if i in by_id]
        write_order(first + [n for n in current if n not in first])

    @staticmethod
    def record_order(root):
        nodes = tagged_in_order(root)
        ids = [n.get_id() for n in nodes]
        labels = {n.get_id(): n.get(LABEL) for n in nodes if n.get(LABEL)}
        try:
            with open(ORDER_RECORD_PATH, 'w') as f:
                json.dump({'ids': ids, 'labels': labels, 'time': time.time()}, f)
        except OSError:
            pass

    def list_order(self, root):
        nodes = tagged_in_order(root)
        if not nodes:
            self.msg('No objects have a stitch order yet.')
            return
        lines = [f'{n.get(ORDER_ATTR)}. {describe(n)}' for n in nodes]
        self.msg('Stitch order (objects without a number are not sewn):\n\n'
                 + '\n'.join(lines))

    def build(self, only_ordered=False):
        doc, count = ordered_copy(self.document, only_ordered)
        if count == 0:
            raise inkex.AbortExtension('Nothing is numbered in the stitch order, so nothing would be sewn.')
        return doc

    def preview(self):
        path = os.path.join(tempfile.gettempdir(), 'stitch_order_preview.svg')
        self.build().write(path)
        if not os.path.exists(INKSTITCH):
            raise inkex.AbortExtension(f'Ink/Stitch was not found at {os.path.normpath(INKSTITCH)}')
        spawn_detached([INKSTITCH, '--extension=simulator', path])

    def output_path(self):
        fmt = self.options.format.lower()
        path = (self.options.output_path or '').strip()
        # An SVG gets its own name so it never replaces the document itself.
        suffix = SVG_SUFFIX if fmt == 'svg' else ''
        if not path:
            doc_path = self.document_path()
            if not doc_path:
                raise inkex.AbortExtension(
                    'Save the SVG first, or choose where to save the file.')
            path = os.path.splitext(doc_path)[0] + suffix + '.' + fmt
        elif os.path.isdir(path):
            doc_path = self.document_path() or 'embroidery.svg'
            name = os.path.splitext(os.path.basename(doc_path))[0]
            path = os.path.join(path, f'{name}{suffix}.{fmt}')
        elif not path.lower().endswith('.' + fmt):
            path += '.' + fmt
        doc_path = self.document_path()
        if doc_path and os.path.abspath(path) == os.path.abspath(doc_path):
            raise inkex.AbortExtension('That would replace the document itself. Choose another name.')
        return path

    def export(self):
        fmt = self.options.format.lower()
        out = self.output_path()
        if fmt == 'svg':
            # Replaces an earlier export of the same name without asking.
            self.build(only_ordered=True).write(out)
            return
        src = os.path.join(tempfile.gettempdir(), 'stitch_order_export.svg')
        self.build().write(src)
        try:
            result = subprocess.run([INKSTITCH, '--extension=output', f'--format={fmt}', src],
                                    capture_output=True, timeout=1800)
        except FileNotFoundError:
            raise inkex.AbortExtension(f'Ink/Stitch was not found at {os.path.normpath(INKSTITCH)}')
        if result.returncode != 0 or not result.stdout:
            detail = result.stderr.decode('utf-8', 'replace').strip().splitlines()
            raise inkex.AbortExtension('Ink/Stitch did not write the file.'
                                       + (f'\n\n{detail[-1]}' if detail else ''))
        with open(out, 'wb') as f:
            f.write(result.stdout)
        self.msg(f'Saved {out}')


if __name__ == '__main__':
    StitchOrder().run()
