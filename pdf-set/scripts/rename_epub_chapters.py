import os, re, sys, shutil, tempfile
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

src, dst = sys.argv[1], sys.argv[2]
tmp = tempfile.mkdtemp(prefix='epub-rename-')
with ZipFile(src) as z:
    z.extractall(tmp)

text_dir = os.path.join(tmp, 'EPUB', 'text')
nav_path = os.path.join(tmp, 'EPUB', 'nav.xhtml')
ncx_path = os.path.join(tmp, 'EPUB', 'toc.ncx')
opf_path = os.path.join(tmp, 'EPUB', 'content.opf')
nav = open(nav_path, encoding='utf-8').read()

def safe_name(title, used):
    title = re.sub(r'<[^>]+>', '', title)
    title = re.sub(r'[\\/:*?"<>|]', '', title).strip()
    title = re.sub(r'\s+', ' ', title)[:48] or '章节'
    base = title
    n = 2
    while title in used:
        title = f'{base}-{n}'
        n += 1
    used.add(title)
    return title + '.xhtml'

mapping, used = {}, set()
for old, label in re.findall(r'href="text/(ch\d+\.xhtml)#[^"]*">(.*?)</a>', nav):
    if old not in mapping:
        mapping[old] = safe_name(label, used)

for old, new in mapping.items():
    old_path = os.path.join(text_dir, old)
    if os.path.exists(old_path):
        os.rename(old_path, os.path.join(text_dir, new))

for path in (nav_path, ncx_path, opf_path):
    if not os.path.exists(path):
        continue
    text = open(path, encoding='utf-8').read()
    for old, new in mapping.items():
        text = text.replace('text/' + old, 'text/' + new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)

with ZipFile(dst, 'w') as out:
    mimetype = os.path.join(tmp, 'mimetype')
    if os.path.exists(mimetype):
        out.write(mimetype, 'mimetype', compress_type=ZIP_STORED)
    for root, _, files in os.walk(tmp):
        for fn in files:
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, tmp).replace(os.sep, '/')
            if rel != 'mimetype':
                out.write(path, rel, compress_type=ZIP_DEFLATED)

for old, new in mapping.items():
    print(f'{old} -> {new}')
shutil.rmtree(tmp)
