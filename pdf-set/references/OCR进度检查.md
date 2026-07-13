# OCR 进度检查

CRITICAL:
- 每次开始一本书的全量 OCR 转换时，必须先预估完成时间，并创建 **once** follow-up 定时检查。
- 检查到点后严格按本文执行；未完成则递归再排下一次检查。
- 回复要简洁；**绝不要泄露任何 API key / secrets**。
- 本 skill 要能提交 GitHub，并在 **minis** 与 **Linux/OpenClaw** 两类环境工作；调度器按当前环境选择，不要写死只支持一种。
- 完成后 **必须把 EPUB 发回用户**，并先通过 `references/导出EPUB.md` 的质量检查。

## 环境适配（先识别，再调度）

### A. minis 环境特征
- 书籍路径常见：`/var/minis/mounts/minis/<书名>`
- 日志常见：`ocr-run.log`
- 调度工具：`minis-scheduled`（once follow-up）
- 完成通知：优先 `android-notification`
- 会话回投：用户指定的 session id

### B. Linux / OpenClaw 环境特征
- 书籍路径常见：`~/.openclaw/workspace/books/<书名>` 或用户给定目录
- 日志常见：`ocr.log` / `ocr-run.log`
- 调度工具：OpenClaw `cron`（`schedule.kind=at` + `payload.kind=agentTurn` + `sessionTarget=current`）
- 完成通知：当前聊天渠道回传；`android-notification` 可用才用
- 文件回传：Telegram 优先 `MEDIA:<epub>`；失败再 Bot API / MTProto 文档发送

### 选择规则
1. 若用户明确给了 minis 路径或要求 `minis-scheduled` → 用 minis 方式。
2. 若当前是 OpenClaw/Telegram 会话且无 minis 工具 → 用 OpenClaw `cron`。
3. 两者都可用时：优先跟随用户指令/路径所在环境。
4. 不要在 skill 文档或 GitHub 内容里绑定单一机器的绝对路径。

## 适用场景
- 用户要求把 PDF 直接转成 EPUB，并在 OCR 期间自动跟进。
- 用户发来类似“检查《书名》OCR进度”的指令。
- OCR 已经后台跑起来，需要定时回查。

## 必要信息（检查提示里带齐）
- 书名 / label
- 书籍目录（按环境替换）
- 总页数 `total`
- OCR 输出目录：默认 `<book>/ocr-result/`
- 日志文件：`<book>/ocr.log` 或 `<book>/ocr-run.log`
- OCR profile：当前 `PDF_OCR_PROFILE`（只写名称，不写 key）
- 目标会话：当前用户会话 / 用户指定 session

## 阶段 A：开始全量 OCR 时（必做）
1. 确认书目录、`images/`、`total`、profile、日志路径。
2. 启动 / 确认 OCR 后台进程。
3. 预估完成时间；`eta` 不少于 5 分钟。
4. 当前会话简短回报进度与 ETA。
5. 创建 once follow-up 检查任务。

## 阶段 B：到点检查（严格执行）
检查提示模板：

```text
检查《书名》OCR进度。书籍目录：<BOOK_DIR>，总页数 <TOTAL>，输出在 ocr-result/，日志 <OCR_LOG>。

请严格按下面做：
1. 统计 ocr-result 中已完成页数 completed/<TOTAL>，并检查 ocr.py 进程是否仍在运行。
2. 若 completed>=<TOTAL> 且进程已结束：明确回复“OCR已完成”，并继续执行粗合并、标题整理、排版成书、导出EPUB（参考 pdf-set skill）。完成后把 EPUB 发回用户；若 android-notification 可用则再发一条通知。
3. 若未完成：
   - 基于最近完成页面的 mtime 估算剩余时间；
   - 在本会话回复当前进度、速度、预计完成时间；
   - 再创建一个 once follow-up 到本会话，时间设为预计完成时刻或至少 5 分钟后，label 仍用“书名OCR进度检查”，prompt 复用本指令，实现递归检查；
   - 若进程已停止且未完成，分析日志错误，尝试按当前 PDF_OCR_PROFILE 断点续跑，再重新估时并安排下一次检查。
4. 简洁回复，不要泄露任何 API key。
```

### B2. 若 OCR 已完成
1. 回复：`OCR已完成`。
2. 依次：粗合并 → 标题分类 → 排版成书 → 导出 EPUB。
3. **必须把最终 EPUB 发回用户**。
4. 导出前/发送前执行 `references/导出EPUB.md` 质量检查。
5. 不要再创建进度检查任务。

### B3/B4 未完成
- 进程在跑：估速、回报、再排 once。
- 进程已停：读日志、按当前 profile 断点续跑；额度/503/认证错误不要死循环。

## 定时任务实现
### minis
- `minis-scheduled` once follow-up + `android-notification`
### Linux/OpenClaw
- `cron` `at` + `agentTurn` + `sessionTarget=current` + `deleteAfterRun=true`

## 安全与 GitHub 提交
- secrets 只读 env 或本地 ignored 文件。
- prompt / 回复 / 通知绝不写 API key。
- 示例路径用占位：`/var/minis/mounts/minis/<书名>` 与 `~/books/<书名>`。
