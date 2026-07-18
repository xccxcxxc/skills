# OCR

## 输入/输出
- 输入：`<book>/images/` 中按数字命名的图片；支持 jpg/jpeg/png/bmp/tif/tiff/webp。
- 输出：`<book>/ocr-result/N.md` + `N.meta.json`。
- 失败：`N.fail.json`；截断、结构错误、API 失败均不得冒充正式页。
- 单页：`--input-file`，可配 `--output-file`。

## 配置
推荐环境变量：

```text
PDF_OCR_PROFILES=primary,backup
PDF_OCR_PRIMARY_BASE_URL=...
PDF_OCR_PRIMARY_API_KEY=...
PDF_OCR_PRIMARY_MODEL=...
PDF_OCR_PROFILE=primary
```

旧单组变量仍兼容：

```text
PDF_OCR_BASE_URL / PDF_OCR_API_KEY / PDF_OCR_MODEL
```

本地 ignored 的 `assets/secrets_openai.txt` 仅作兼容，不得提交真实密钥。

查看 profile（不输出 key）：

```bash
python scripts/ocr.py --list-profiles
```

运行时仅使用 `--profile` / `PDF_OCR_PROFILE` 指定的一组，不自动切换。

## 执行

```bash
python scripts/ocr.py --base-dir "书籍目录" --profile primary
```

单页：

```bash
python scripts/ocr.py --base-dir "书籍目录" --input-file "书籍目录/images/20.jpg" --profile primary
```

可选参数：
- `--start` / `--end`：数字图片索引开区间/闭区间；可只给一个。
- `--max-tokens`：单页输出上限，默认 8192。
- `--trust-existing`：一次性迁移旧版非空 `N.md`；仅结构校验通过才写入 sidecar。之后不要再依赖此参数。
- `--batch-size`：废弃兼容参数；页面始终顺序处理，以支持续表。
- `--prompt-file`、`--profile` 及 `*-from` 路径参数。

## 强完整性规则
1. `finish_reason=length/max_tokens/max_output_tokens` 视为失败，不写正式页。
2. 模型生成的 HTML 表只允许 table 白名单标签/属性；标签和表格网格必须通过校验。
3. 写入顺序：原子写 `N.md`，再原子写 `N.meta.json`。
4. 断点续跑仅跳过：图片 hash、prompt hash、输出 hash 匹配且 `validated=true` 的页。
5. API/结构错误写 `N.fail.json` 并退出；修复后重跑即可。
6. OCR 完成后必须执行：

```bash
python scripts/validate_ocr.py --base-dir "书籍目录"
```

严格禁止残留图片占位时：

```bash
python scripts/validate_ocr.py --base-dir "书籍目录" --strict-placeholders
```

## 表格
- 混排页可输出「正文 + 表题 + 表格 + 正文」，不要整页图片化。
- 单层/叙述表：GFM，长文本显示可自动换行。
- 多级/统计密表：白名单 HTML + `table-wrap` + `table-dense`，保留 rowspan/colspan。
- **注释不进单元格**：表内只留①②③；注释正文在表下 `  <sup>【①……】</sup>`。
- 后处理：`scripts/extract_table_notes.py` 自动抽出误入单元格的 `<sup>【…】</sup>`。
- 续页重复表头供单页读取；`merge_rough.py` 会在表头 signature 完全一致时保守合并。

## 图文混排
- OCR：正文照常输出；图区只写 `🀄️页码.jpg`，**不要**把整页文字+图一起当图。
- 后处理：`scripts/crop_figures.py` 裁切到 `figures/页-序号.jpg`，并把占位改成 `🀄️figures/页-序号.jpg`。
- 合并：`merge_rough.py` 物化为 `![](assets/figures/...)`。
- 手动：

```bash
python scripts/crop_figures.py --base-dir "书籍目录"
```

详见 `assets/ocr_prompt.md`。

## 全书任务
- 若用户只要求 OCR：停在 OCR + `validate_ocr.py`，不要擅自导 EPUB。
- 若用户要求 PDF→EPUB：使用 `scripts/pdf_to_epub.py` 和 `references/OCR进度检查.md`。
- 进度统一读取：

```bash
python scripts/ocr_status.py --base-dir "书籍目录" --json
```

多页 OCR 默认建 ETA 进度跟进（App 内会话，不必用户每次要求）；只保留一个 once，未完成重算后再建下一个。详见 `OCR进度检查.md`。
仅当用户目标是 PDF→EPUB 时，OCR 完成后才继续 merge/导出；只要 OCR 则 `validate_ocr` 后停止。

## 本地 env 示例
仓库提供 `scripts/ocr_env.example.sh` 作为双 profile 注入模板：复制后填入自己的 endpoint/key/model，`source` 后再跑 `ocr.py` / `pdf_to_epub.py`。默认可用 `PDF_OCR_PROFILE=backup`。不要把真实密钥提交进 Git。
