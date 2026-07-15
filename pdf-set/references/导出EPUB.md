# 导出 EPUB

CRITICAL:
- 导出前必须完成标题分类与排版成书。
- **必须把 EPUB 发回用户**。
- 发送前必须做质量检查：目录、封面、内容文件数。

## 输入/输出
- 输入：`<书名>.md`，可选 `assets/cover.jpg`
- 输出：`<书名>.epub`

## 阶段 1：确认目标文件
1. 确认最终 Markdown 存在。
2. 统计 H1：`grep -E '^# ' 书名.md`
3. H1 数量应等于“期望进入目录的导航项”数量。

## 阶段 2：默认导出命令
导出前必须确认：
1. 全部 `🀄️页码.jpg` 已按插图规则处理。
2. **封面只通过 `--epub-cover-image` 提供一次**；Markdown 前置页不要重复嵌入同一封面。
3. 所有应进目录的章节是一级标题 `# `。

```bash
pandoc "书籍目录/书名.md" \
  --from markdown+tex_math_dollars+tex_math_single_backslash \
  --to epub3 \
  --css "path/to/上标.css" \
  --epub-cover-image "书籍目录/assets/cover.jpg" \
  --webtex="https://latex.codecogs.com/svg.image?" \
  --split-level=1 \
  --toc-depth=1 \
  --resource-path "书籍目录:." \
  --metadata title="书名" \
  --metadata author="作者" \
  --output "书籍目录/书名.epub"

python scripts/rename_epub_chapters.py \
  "书籍目录/书名.epub" \
  "书籍目录/书名.named.epub"
```

参数说明：
- `--epub-cover-image`：书架封面；只设这一次。
- `--split-level=1`：按一级标题切分内容文件。
- `--toc-depth=1`：目录只收一级标题。
- 因此 **想进目录的标题必须是 H1**。
- CSS（`assets/上标.css`）两种表：
  - **默认/叙述表**（如表5—6 GFM）：约 0.92rem，长文本单元格允许换行，保证可读。
  - **密表**（`table.table-dense`，多级统计表如表5—5）：约 0.72rem，单元格 `nowrap`；外包 `.table-wrap` 可横滑。**不要**对叙述表用 scale 缩小。
- 单层表：GFM pipe → pandoc HTML；多级表：OCR 直接输出 HTML `<table>`（rowspan/colspan）。
- 导出 from 默认 markdown 需保留 `pipe_tables` 与 raw HTML。

## 阶段 3：质量检查（发送前必做）

### 1) 目录是否完整
- 打开 `EPUB/nav.xhtml` / `toc.ncx`。
- TOC 条目数应 ≈ Markdown H1 数。
- 失败信号：TOC 只有书名 1 项，而正文其实有几十章。
- 根因通常是：章节被标成 `##`，但导出用了 `--toc-depth=1`。
- 修复：回到 `标题分类`，把导航章节升为 `# ` 后重导。

### 2) 封面是否只出现一次
- OPF 中有且仅有一个 `cover-image` / `--epub-cover-image`。
- 正文各 `ch*.xhtml` **不应再出现封面图**。
- 失败信号：阅读器首页封面后又在正文开头再嵌同一张或版权整页图。
- 修复：删除 Markdown 中的封面/重复前置图，只保留 `assets/cover.jpg` 给 pandoc。

### 3) “三章节 / 文件过少”异常
用户说“只有三章节”时，优先检查 spine，而不是只看正文标题：
- 常见错误 spine：
  1. `cover.xhtml`
  2. `title_page.xhtml`
  3. `ch001.xhtml`（整本书挤在一个内容文件）
- 这不是“只有三章正文”，而是 **导航/内容文件只切出 3 个入口**。
- 根因：
  - 只有 1 个 H1（书名），其余章节是 H2；
  - 或 `--split-level=1` 下没有足够 H1 可切分。
- 修复后期望：
  - `cover.xhtml` + `title_page.xhtml` + 多个 `chXXX.xhtml`；
  - TOC 列出全部导航章节。

### 4) 快速自检命令
```bash
python - <<'PY'
from zipfile import ZipFile
import re
p='书名.epub'
with ZipFile(p) as z:
  nav=z.read('EPUB/nav.xhtml').decode('utf-8','ignore')
  links=re.findall(r'<a href="text/[^"]+">([^<]+)</a>', nav)
  print('toc', len(links), links[:10], '...' if len(links)>10 else '')
  texts=[n for n in z.namelist() if n.startswith('EPUB/text/') and n.endswith('.xhtml')]
  print('text_files', sorted(texts))
  for n in sorted(texts):
    if n.endswith(('cover.xhtml','title_page.xhtml')): continue
    data=z.read(n).decode('utf-8','ignore')
    imgs=re.findall(r'<img[^>]+src="([^"]+)"', data)
    if imgs: print('body_images', n, imgs)
print('zip', ZipFile(p).testzip())
PY
```

通过标准：
1. TOC 含全部应导航章节；
2. 正文不再重复封面；
3. 内容文件数与 H1 数匹配，而不是只有 cover/title/单 ch001 三件套。

## 阶段 4：发送
1. 当前聊天附件 / `MEDIA:<epub>`
2. Telegram Bot API `sendDocument`
3. MTProto 大文件脚本
4. 都失败则给本地绝对路径

minis 环境额外：`android-notification` 提示完成。

## 阶段 5：常见失败复盘（写进执行习惯）
| 现象 | 根因 | 处理 |
|---|---|---|
| 目录只有书名 | 章节是 `##`，`--toc-depth=1` 不收录 | 章节升为 `# ` 后重导 |
| 封面出现两次 | `--epub-cover-image` + 正文又嵌封面/版权图 | 正文去封面图，只留 cover image |
| 看起来像“三章节” | spine 只有 cover/title/整书 ch001 | 增加导航 H1，让 split-level=1 切出多章 |
| 目录有章但阅读器仍怪 | 未跑 `rename_epub_chapters.py` 或 nav/opf 不一致 | 重跑 rename 与 nav 检查 |
