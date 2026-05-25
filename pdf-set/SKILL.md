---
name: pdf-set
description: A toolbox for OCR PDF
---
# pdf-set

Use the correct subtask file based on the user's request. Each subtask is a standalone procedure; do not mix steps across tasks unless asked.

## Task Map
- **Install prerequisites** → read `references/安装前置组件.md`
- **Split PDF to images** → read `references/分图.md`
- **OCR from images** → read `references/OCR.md`
- **Rough merge pages** → read `references/粗合并.md`
- **Classify Markdown headings before split** → read `references/标题分类.md`
- **Typeset rough merge into final book** → read `references/排版成书.md`
- **Split for translation** → read `references/翻译分割.md`
- **Typeset translation** → read `references/翻译排版.md`
- **Translate formatted files** → read `references/翻译.md`
- **Merge translations** → read `references/翻译合并.md`
- **Export Markdown to EPUB** → read `references/导出EPUB.md`

## Usage Rules
1. Identify the user's target stage (分图/OCR/合并/标题分类/排版成书/翻译/导出EPUB).
2. Open only the matching subtask file(s).
3. Follow the steps in order; do not skip CRITICAL phases.
4. Keep outputs in the specified folders and naming formats.

## Notes
- Do not add extra guidance beyond the selected subtask.
