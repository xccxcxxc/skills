# 导出 EPUB

前置：标题分类、排版、图片占位处理已完成。

## 默认导出
默认使用 EPUB3 MathML，不把公式发送给第三方 WebTeX：

```bash
pandoc "书籍目录/书名.md" \
  --from markdown+tex_math_dollars+tex_math_single_backslash \
  --to epub3 \
  --css "pdf-set/assets/上标.css" \
  --epub-cover-image "书籍目录/assets/cover.jpg" \
  --split-level=1 \
  --toc-depth=1 \
  --resource-path "书籍目录:书籍目录/images:." \
  --metadata title="书名" \
  --metadata author="作者" \
  --output "书籍目录/书名.epub"
```

不要默认使用远程 `--webtex`；公式图片化应采用本地工具。

`rename_epub_chapters.py` 不是必需步骤。Pandoc 的 `chNNN.xhtml` 正常且兼容性更好；仅在明确需要易读内部文件名时使用重命名工具，并重跑严格校验。

## 表格模式
- 默认/叙述表：正常可读字号，长文本允许自动折行。
- `table-dense`：密表单元格 nowrap、字号略小，超宽时依赖阅读器横滑。
- reflowable EPUB 无法在所有屏幕同时保证“不换行、大字、一页完整”。需要原页视觉一致时，应另选 fixed-layout EPUB 或表格 SVG/图片模式。

## 严格验收（发送前必做）

```bash
python scripts/validate_epub.py "书籍目录/书名.epub" \
  --strict-footnote-arrows
```

校验包括：
1. ZIP CRC；
2. `mimetype` 第一项且 STORE；
3. 所有 XHTML/XML/OPF/NCX/SVG 可严格解析；
4. manifest、spine、nav、图片和 CSS 引用存在；
5. cover-image 不重复；
6. 禁止残留 `🀄️`、`🈳`、`__PROHIBITED_CONTENT__`；
7. `⬆️/⬇️` 在 `--strict-footnote-arrows` 下视为失败。

如用户明确暂时接受未处理图片占位，只能在非最终预览使用：

```bash
--allow-markers
```

最终交付不应使用。

## 目录/封面/spine 检查
- Markdown H1 数应接近 nav 目录条目数；
- `--split-level=1` 下必须有足够 H1，不能整本挤进一个内容文件；
- 封面只由 `--epub-cover-image` 提供一次，正文不重复；
- 严格 validator 通过后，仍建议在目标阅读器抽检密表、叙述表、脚注、目录和封面。

## 回传与验收保留
- 将 EPUB 作为附件/可点击文件回传；路径作为兜底。
- 用户明确验收前保留 PDF、images、ocr-result、merge-result、typeset、assets、最终 Markdown 和 EPUB。
- 用户验收后才清理任务专用中间产物。
