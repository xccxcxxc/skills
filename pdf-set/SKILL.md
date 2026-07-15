---
name: "pdf-set"
description: "PDF OCR/排版/EPUB；兼容 minis/Linux，含验收前保留中间产物与目录封面质量坑"
---

# pdf-set

Use the correct subtask file based on the user's request. Each subtask is a standalone procedure; do not mix steps across tasks unless asked.

## Task Map
- **Install prerequisites** → read `references/安装前置组件.md`
- **Split PDF to images** → read `references/分图.md`
- **OCR from images** → read `references/OCR.md`
- **OCR progress check (scheduled follow-up)** → read `references/OCR进度检查.md`
- **Rough merge pages** → read `references/粗合并.md`
- **Classify Markdown headings before split** → read `references/标题分类.md`
- **Typeset rough merge into final book** → read `references/排版成书.md`
- **Split for translation** → read `references/翻译分割.md`
- **Typeset translation** → read `references/翻译排版.md`
- **Translate formatted files** → read `references/翻译.md`
- **Merge translations** → read `references/翻译合并.md`
- **Export Markdown to EPUB** → read `references/导出EPUB.md`

## Usage Rules
1. Identify the user's target stage (分图/OCR/合并/标题分类/排版成书/翻译/导出EPUB/进度检查).
2. Open only the matching subtask file(s).
3. Follow the steps in order; do not skip CRITICAL phases.
4. Keep outputs in the specified folders and naming formats.
5. **Whenever a full-book OCR conversion starts**, also follow `references/OCR进度检查.md`:
   - estimate completion time;
   - create a once follow-up check job using the **scheduler available in the current environment**;
   - on completion continue merge → heading classify → typeset → EPUB;
   - **deliver the EPUB back to the user** (required);
   - never leak API keys in replies or job prompts.
6. This skill must stay portable for GitHub:
   - support **minis** paths/tools and **Linux/OpenClaw** paths/tools;
   - do not hardcode a single host path, single scheduler, or single notification channel.
7. Before sending any EPUB, run the quality checks in `references/导出EPUB.md` (TOC / cover / spine). Do not ship a known-bad EPUB.
8. For PDF→EPUB conversion or EPUB export, always enforce the EPUB Acceptance Gate below in addition to the selected subtask.

## EPUB Acceptance Gate

Generating, validating, or sending an EPUB does not complete the task's cleanup phase. The EPUB remains pending acceptance until the user explicitly confirms that the delivered file is correct or explicitly authorizes cleanup.

Before acceptance:
- Keep the original PDF or Markdown source, split page images, OCR outputs, rough merge, heading-classified and typeset Markdown, image assets, original and renamed EPUB files, backups, and the complete work directory.
- Do not delete, overwrite, compact away, or move acceptance-critical intermediates into an automatically cleaned temporary location.
- If the workflow started under `/tmp` or another ephemeral path, preserve the complete work directory in a durable acceptance-hold location before delivery.
- Reuse the retained work directory for corrections; do not reconstruct from the delivered EPUB when retained sources are available.
- Report the retained work-directory path when delivering the EPUB.
- If storage pressure is a concern, ask the user before deleting anything.

Cleanup is allowed only after the user explicitly confirms the EPUB is correct or explicitly asks to remove the retained files. Then remove task-only intermediates and report what was cleaned.

## OCR Profiles
- You may store multiple named model/account profiles, but OCR always runs **one profile at a time**.
- Preferred env vars:
  - `PDF_OCR_PROFILES=primary,backup`
  - `PDF_OCR_<NAME>_BASE_URL` / `PDF_OCR_<NAME>_API_KEY` / `PDF_OCR_<NAME>_MODEL`
  - `PDF_OCR_PROFILE=<name>` selects the only profile used for this run
- Legacy single-profile env still works: `PDF_OCR_BASE_URL` / `PDF_OCR_API_KEY` / `PDF_OCR_MODEL`
- OCR uses a single profile only. No auto profile switch.
- Concurrency is configurable via `PDF_OCR_BATCH_SIZE` (default 6). CLI `--batch-size` overrides the env var.
- On 503 / quota / temporary provider errors: fail immediately and exit.
- Manual switch for the next run: change `PDF_OCR_PROFILE` or pass `--profile backup`
- List profiles (no secrets): `python scripts/ocr.py --list-profiles`
- Details: `references/OCR.md`

## Notes
- Do not add extra guidance beyond the selected subtask, except for the mandatory EPUB Acceptance Gate.
- Never commit API keys; configure them via env vars or ignored local files only.
- Prefer a local venv / skill-local python when system packages are PEP-668 protected; otherwise use the environment's normal Python.
- Prefer `pandoc` from PATH; if only a skill-local wrapper exists, use that.
