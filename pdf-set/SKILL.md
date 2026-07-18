---
name: "pdf-set"
description: "PDF 分图、视觉 OCR、表格/脚注处理、标题排版、翻译和 EPUB 导出；支持断点续跑、跨页表合并、严格页面与 EPUB 验收。用于 PDF→Markdown/EPUB、OCR 进度跟进及对照翻译。"
---

# pdf-set

按用户目标只读取必要 reference；PDF→EPUB 全流程使用状态机与所有门禁。

## Task Map
- 安装 → `references/安装前置组件.md`
- PDF 分图 → `references/分图.md`
- OCR → `references/OCR.md`
- OCR 进度 → `references/OCR进度检查.md`
- 粗合并/跨页表 → `references/粗合并.md`
- 标题分类 → `references/标题分类.md`
- 排版 → `references/排版成书.md`
- 翻译分割/排版/翻译/合并 → 对应 `references/翻译*.md`
- EPUB → `references/导出EPUB.md`

## 核心规则
1. 用户只要某一阶段时，不擅自进入其他阶段；**仅“PDF→EPUB”全书任务自动串联完整流水线**。
2. 不跳过 validation gate，不用“文件非空/文件数量”冒充完成。
3. 不静默删字、补文、改词；任何启发式修复必须显式 opt-in。
4. 密钥只读环境变量或 ignored 本地文件，绝不写入 prompt、日志、回复或 Git。
5. 工作目录与命令保持 minis/Linux/Windows 可替换，不把仓库绑定单机。

## PDF→EPUB 状态机

```bash
python scripts/pdf_to_epub.py \
  --pdf "书名.pdf" \
  --work-dir "书籍目录" \
  --profile primary
```

阶段：

```text
split → ocr → validate-pages → crop-figures → extract-table-notes → merge → heading-gate → typeset → epub → validate-epub
```

标题分类是语义 gate：首次运行生成 `merge-result/0.rough.md` 后停止；按 `references/标题分类.md` 整理，再运行：

```bash
python scripts/pdf_to_epub.py ... --headings-ready --title "书名" --author "作者"
```

状态写入 `pipeline-state.json`，失败后可恢复。

## OCR 完整性
- 每页：`N.md` + `N.meta.json`；失败：`N.fail.json`。
- `finish_reason=length/max_tokens`、空输出、HTML/GFM 结构错误都视为失败。
- 文件原子写；断点只跳过图片/prompt/输出 hash 匹配且 `validated=true` 的页。
- 单层/叙述表 → GFM；多级/密表 → 白名单 HTML `rowspan/colspan` + `table-dense`。
- 跨页表续页重复表头；粗合并仅在相邻表头 signature 完全一致时合并。
- 图文混排：正文 OCR + `🀄️页码.jpg` 标记图区；`crop_figures.py` 裁成 `figures/页-序号.jpg`，禁止整页文字+图当图。
- 脚注/表注：单元格只留①②③；注释正文在表外 `<sup>【①……】</sup>`。`extract_table_notes.py` 会把误入单元格的注释抽到表下。
- 扫描页码：`·12·` / `•6•` 等不进正文；`typeset_book.py` 会删除并压缩多余空行。
- OCR 后运行 `scripts/validate_ocr.py`；进度/ETA 用 `scripts/ocr_status.py`。

## EPUB 门禁
- 导出前处理所有 `🀄️/🈳`，消解 `⬆️/⬇️` 脚注续接。
- 默认离线 MathML，不使用远程 WebTeX。
- `rename_epub_chapters.py` 仅可选，不是必做。
- 发送前必须：

```bash
python scripts/validate_epub.py "书名.epub" --strict-footnote-arrows
```

校验 ZIP、全部 XML/XHTML、manifest/spine/nav、资源引用、封面与未解析标记。已知不通过的 EPUB 禁止交付。

## 进度通知（无条件）
凡 OCR / 导出任务都必须汇报，**不得**因页少、时长短、用户没口头要求而跳过：
- **短、当次能跑完**：结束立刻在当前会话汇报。
- **长、仍在后台跑**：`ocr_status.py` 的 `eta_local`（+10–15% 缓冲，≥5 分钟后）建 **1 个** once；到点 **App 内会话**汇报（`minis-scheduled --target new`）；未完成只续建下一次。
- 默认不要系统通知。OCR-only 完成 → `validate_ocr` 后停；PDF→EPUB → 继续导出。成功后删本书剩余 once。
- 细则：`references/OCR进度检查.md`。

## EPUB Acceptance Gate
生成并校验 EPUB 后仍需等待用户验收。验收前保留：原 PDF、images、ocr-result/meta、merge-result、标题/排版 Markdown、assets、EPUB 和状态文件；不要放在自动清理的临时目录。用户明确确认或授权清理后，才删除任务中间产物并报告清理内容。

## 开发质量
- 依赖：`requirements.txt` + Pandoc。
- 测试：`python -m unittest discover -s tests -v`
- 所有脚本先 `py_compile`；GitHub CI 覆盖 Python 3.10–3.12。
