# OCR 进度检查

仅在用户要求**全书 PDF→EPUB 且需要后台自动跟进**时使用。用户只要求 OCR 时，OCR 完成后停在 `validate_ocr.py`。

## 状态来源
不要用 `ls *.md | wc -l`，因为 fail/partial/旧结果可能冒充完成。
统一执行：

```bash
python scripts/ocr_status.py --base-dir "书籍目录" --json
```

只有 `N.meta.json` 为 `status=ok, validated=true` 的页算完成。

## 定时任务（强制）
- 一次只保留 **1 个** 本书 once 检查；时间 = 当前 ETA（可加 10–15% 缓冲，不少于 5 分钟后）。
- 禁止一次创建多个固定间隔检查。
- 到点：
  - 未完成：读取新状态；进程停止则先查 `*.fail.json`/日志并修复或续跑；重算 ETA，再建下一个唯一 once。
  - OCR 完成：执行 validate → merge → heading gate → typeset → EPUB → validate_epub；全流程成功后删除本书剩余 once。
- 未完成时不得只删检查而不创建下一次 ETA。
- API 配额/认证/结构错误不得死循环重试；报告错误并等待处理。

## 推荐调度 prompt

```text
检查《书名》PDF→EPUB 流水线。
工作目录：<BOOK_DIR>
状态：运行 python scripts/ocr_status.py --base-dir <BOOK_DIR> --json。
若 remaining>0：确认 OCR 进程；如进程因可恢复原因停止则断点续跑；按 eta_local 创建唯一下一次 once。
若 complete=true：运行 validate_ocr.py，然后 merge_rough.py；进入标题分类 gate；标题已确认后 typeset、pandoc、validate_epub.py。全部成功后回传 EPUB 并删除本书剩余 once。
不得用文件数量冒充有效页数；不得堆叠多个检查；不得泄露密钥。
```

## 环境选择
- minis：`minis-scheduled` once follow-up；通知可选 `android-notification`。
- Linux/OpenClaw：使用当前环境可靠的 one-shot scheduler/cron agentTurn。
- 调度 prompt 只写 profile 名称，不写 API key。

## 生命周期
- EPUB 生成并严格校验成功：清理未执行定时任务；保留工作目录等待用户验收。
- 用户验收后：按 EPUB Acceptance Gate 清理中间产物。
