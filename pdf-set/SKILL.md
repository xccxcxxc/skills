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

## OCR Multi-profile
- OCR can use multiple model/account profiles at once.
- Preferred env vars:
  - `PDF_OCR_PROFILES=primary,backup`
  - `PDF_OCR_<NAME>_BASE_URL` / `PDF_OCR_<NAME>_API_KEY` / `PDF_OCR_<NAME>_MODEL`
  - optional `PDF_OCR_PROFILE=<name>` for the starting profile
- Legacy single-profile env still works: `PDF_OCR_BASE_URL` / `PDF_OCR_API_KEY` / `PDF_OCR_MODEL`
- On quota exhaustion or temporary 429/503-style errors, OCR auto-switches to the next profile.
- Manual switch: `python scripts/ocr.py --profile backup ...`
- List profiles (no secrets): `python scripts/ocr.py --list-profiles`
- Details: `references/OCR.md`

## Notes
- Do not add extra guidance beyond the selected subtask.
- Never commit API keys; configure them via env vars or ignored local files only.
