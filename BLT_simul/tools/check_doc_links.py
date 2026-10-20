# -*- coding: utf-8 -*-
"""Check every image path and every internal anchor in the repository's Markdown."""
import io
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else '.'
DOCS = []
for dp, dn, fn in os.walk(ROOT):
    if '.git' in dp:
        continue
    for f in fn:
        if f.endswith('.md'):
            DOCS.append(os.path.join(dp, f))


def slug(heading):
    s = heading.strip().lower()
    s = re.sub(r'[^\w\s-]', '', s, flags=re.UNICODE)
    s = re.sub(r'\s+', '-', s)
    return s


anchors = {}
for p in DOCS:
    text = io.open(p, encoding='utf-8').read()
    anchors[os.path.normpath(p)] = {slug(m.group(2))
                                    for m in re.finditer(r'^(#{1,6})\s+(.*)$', text, re.M)}

bad = []
for p in DOCS:
    base = os.path.dirname(p)
    text = io.open(p, encoding='utf-8').read()

    # <img src="..."> and ![](...)
    for m in re.finditer(r'<img\s+src="([^"]+)"', text):
        t = m.group(1)
        if t.startswith(('http://', 'https://')):
            continue
        if not os.path.isfile(os.path.join(base, t)):
            bad.append('%s: image not found -> %s' % (p, t))

    # [text](target)
    for m in re.finditer(r'\[[^\]]*\]\(([^)]+)\)', text):
        t = m.group(1)
        if t.startswith(('http://', 'https://', 'mailto:')):
            continue
        path, _, frag = t.partition('#')
        target = os.path.normpath(os.path.join(base, path)) if path else os.path.normpath(p)
        if path and not os.path.exists(target):
            bad.append('%s: link target missing -> %s' % (p, t))
            continue
        if frag:
            known = anchors.get(target)
            if known is None:
                continue          # not a markdown file; nothing to check
            if frag not in known:
                bad.append('%s: anchor not found -> %s' % (p, t))

if bad:
    print('%d problem(s):' % len(bad))
    for b in bad:
        print('  ' + b)
    raise SystemExit(1)
print('all image paths and internal anchors resolve (%d markdown files)' % len(DOCS))
