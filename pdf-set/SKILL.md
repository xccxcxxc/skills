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
- **OCR failure补漏（对OCR处理失败的内容查漏补缺）** → read `references/OCR查漏补缺.md`
- **Rough merge pages** → read `references/粗合并.md`
- **Split by一级标题/目录** → read `references/分割.md`
- **Layout cleanup** → read `references/排版.md`
- **Merge formatted files** → read `references/排版合并.md`
- **Translate formatted files** → read `references/翻译.md`
- **Merge translations** → read `references/翻译合并.md`

## Usage Rules
1. Identify the user's target stage (分图/OCR/合并/分割/排版/翻译).
2. Open only the matching subtask file(s).
3. Follow the steps in order; do not skip CRITICAL phases.
4. Keep outputs in the specified folders and naming formats.

## Notes
- Do not add extra guidance beyond the selected subtask.