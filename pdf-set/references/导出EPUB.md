# 导出 EPUB

CRITICAL: 按顺序执行以下阶段，勿跳步。

## 输入/输出
- 输入：书籍目录中的最终 Markdown 文件，通常是 `书籍名.md` 或 `书籍名(对照翻译).md`。
- 输出：同目录下同名 `.epub` 文件。
- CSS：必须加入 `assets/上标.css`，用于上标渲染。

## 脚本参考

使用 `pandoc` 直接导出。

## 阶段 1：确认目标文件
1. 若用户指定文件，使用该 Markdown 文件。
2. 若用户未指定，优先选择书籍目录中的 `书籍名(对照翻译).md`；不存在时选择 `书籍名.md`。
3. 输出文件与输入文件同名，仅扩展名改为 `.epub`。

## 阶段 2：默认导出命令

导出前必须确认已按 `references/排版成书.md` 的“原书插图处理”规则处理全部 `🀄️页码.jpg` 占位符：重要的封面、封底、书影、图版和正文配图使用 `assets/` 中的实际图片嵌入；纯目录页、章节装饰页与空白页的占位符必须删除。封面图若已通过 `--epub-cover-image` 声明为 EPUB 封面，不应再在 Markdown 前置页重复嵌入同一张封面图片；前置内容保留一个一级标题（书名），其下以二级标题组织书名作者、图书在版编目等信息。然后使用 `pandoc` 直接导出。

```bash
pandoc "书籍目录/书籍名(对照翻译).md" \
  --from markdown+tex_math_dollars+tex_math_single_backslash \
  --to epub3 \
  --css "skills/pdf-set/assets/上标.css" \
  --epub-cover-image "书籍目录/assets/cover.jpg" \
  --webtex="https://latex.codecogs.com/svg.image?" \
  --split-level=1 \
  --toc-depth=1 \
  --resource-path "书籍目录:." \
  --metadata title="书籍名(对照翻译)" \
  --output "书籍目录/书籍名(对照翻译).epub"

python3 skills/pdf-set/scripts/rename_epub_chapters.py \
  "书籍目录/书籍名(对照翻译).epub" \
  "书籍目录/书籍名(对照翻译).named.epub"
```

参数要求：
- `+tex_math_dollars`：识别 `$...$` 和 `$$...$$` 公式。
- `+tex_math_single_backslash`：识别 `\(...\)` 公式。
- `--webtex="https://latex.codecogs.com/svg.image?"`：直接渲染 `\cancel` 等 Pandoc MathML 不支持的宏。
- `--epub-cover-image`：指向从原书封面复制到 `assets/cover.jpg` 的图片，使阅读器书架显示正确封面。
- `--split-level=1`：仅按一级 Markdown 标题切分 EPUB 内容文件；不要按所有子标题拆成大量 `chxxx.xhtml`。
- `--toc-depth=1`：目录只列出一级章节（序言、正文篇章、附录）；OCR 误识别的子标题或长段落不得进入目录。
- `rename_epub_chapters.py`：Pandoc 导出后执行；它把 `ch001.xhtml` 等通用文件名和 `nav.xhtml`、`toc.ncx`、`content.opf` 中的引用统一改为安全的章节标题。
- `--resource-path "书籍目录:."`：让 Markdown 中的 `./assets/...` 能从书籍目录解析并打包。
- `--css "skills/pdf-set/assets/上标.css"`：加入上标样式。

## 阶段 3：不要优先使用的方案

不要优先使用 `--mathjax`：
- 很多 EPUB 阅读器不会执行 MathJax JavaScript，公式可能显示为源码。

不要优先使用 `--mathml`：
- Pandoc 的 MathML 转换器不支持 `\cancel{...}`，会警告并残留 TeX 文本。
- 只有在文档没有 `\cancel` 等不支持宏，且用户明确要求 MathML 时才使用。

## 阶段 4：输出检查
1. EPUB 文件存在且大小合理。
2. 检查 EPUB 内部已打包 CSS。
3. 若文档含图片，检查 `EPUB/media/` 中已打包图片资源。
4. 若文档含公式，检查 `EPUB/media/` 中存在 `.svg` 或 `.svgz` 公式资源。
5. 若文档含 `\cancel`，检查 EPUB 的 XHTML 中存在类似 `alt="\cancel{A}"` 的公式图片引用。

检查示例：

```bash
python3 - <<'PY'
from zipfile import ZipFile
p = "书籍目录/书籍名(对照翻译).epub"
with ZipFile(p) as z:
    names = z.namelist()
    media = [n for n in names if n.startswith("EPUB/media/")]
    css = [n for n in names if n.endswith(".css")]
    formulas = [n for n in media if n.endswith((".svg", ".svgz"))]
    xhtml = "\n".join(
        z.read(n).decode("utf-8", "ignore")
        for n in names
        if n.endswith((".xhtml", ".html"))
    )
    print("css", css)
    print("media", len(media))
    print("formula_svg", len(formulas))
    print("contains_cancel_alt", "\\cancel" in xhtml)
PY
```
