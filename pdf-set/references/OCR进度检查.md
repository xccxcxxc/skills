# OCR 进度检查

## 何时启用（默认开启）
对**多页 / 耗时**的 OCR 任务，**默认**建立 ETA 进度跟进，**不要求**用户每次口头说「后台跟进 / 到点通知」。

包括但不限于：
- 全书 PDF→EPUB 流水线中的 OCR；
- 用户只要求 OCR / 识别 / 转写多页图片或整书扫描。

可跳过定时的情况（仍应在会话里说明进度）：
- 单页或极少页（例如 ≤3 页）且预计很快结束；
- 用户明确说「不用跟进 / 不要定时 / 我自己看」。

## OCR-only vs 全书导出
| 用户目标 | OCR 进行中 | OCR 完成后 |
|---|---|---|
| 只要 OCR | App 内 ETA 进度汇报 | `validate_ocr.py` 后**停止**；汇报完成，不自动 merge/EPUB |
| PDF→EPUB | 同上 | validate → crop_figures → extract_table_notes → merge → 标题 gate → typeset → EPUB → validate_epub |

## 状态来源
不要用 `ls *.md | wc -l`（fail/partial/旧结果会冒充完成）。统一：

```bash
python scripts/ocr_status.py --base-dir "书籍目录" --json
```

完成页：`N.meta.json` 且 `status=ok` + `validated=true`。

关注：`total` / `validated` / `remaining` / `seconds_per_page_median` / `eta_local` / `complete`。

## ETA 怎么定
1. 优先用 `ocr_status.py` 的 `eta_local`。
2. 调度时间 = ETA + **10–15% 缓冲**；距现在不足 **5 分钟**则排到至少 5 分钟后。
3. 刚启动样本不足：等至少 **3～5 页** validated 再算 ETA 并建定时；不要拍脑袋固定扫间隔。
4. 每次检查后用**最新**速度重算；不得沿用过期 ETA。

## 定时任务（强制）
- 同一本书 / 同一工作目录只保留 **1 个** once（label 如 `书名OCR进度`）。
- **禁止**一次创建多个固定间隔检查。
- **禁止**未完成时删掉检查却不建下一次。
- 启动 OCR（后台或长任务）后：有可靠 ETA 就**马上**建第一次 once，不必等用户再催。
- 到点检查：
  1. 读 `ocr_status.py --json`；确认 OCR 进程（如 `logs/ocr.pid`）。
  2. 可恢复停止 → 同 profile 断点续跑；`*.fail.json` / 配额 / 认证错误 → 停止死循环，会话说明原因。
  3. `remaining>0` → 重算 ETA，**只建 1 个**下一次 once；删已触发/过期任务。
  4. `complete=true`：
     - **OCR-only**：`validate_ocr.py`，会话汇报完成与结果路径，**删除本书剩余 once**，停止。
     - **PDF→EPUB**：`validate_ocr` → `crop_figures` → `extract_table_notes` → `merge_rough` → 标题分类 gate →（标题就绪后）typeset → EPUB → `validate_epub`；成功后回传 EPUB，**删除本书剩余 once**。

## 汇报方式（默认 = App 内）
- **默认**：`minis-scheduled`（或环境等价物）到点 **开新会话 / 会话内回复** 写进度。这就是“通知”。
- 至少包含：`validated/total`、`remaining`、`eta_local`、进程是否存活、下一步。
- **不要**默认 `android-notification`。
- 仅当用户**明确要求**系统通知时才额外发送。

## minis 调度示例

```bash
minis-scheduled create \
  --time HH:MM \
  --repeat once \
  --label "书名OCR进度" \
  --target new \
  --prompt "……见下方模板……"
```

## 推荐调度 prompt（按任务改最后一步）

```text
检查《书名》OCR/EPUB 进度（App 内汇报即可，不要发系统通知）。
工作目录：<BOOK_DIR>
任务类型：<ocr-only | pdf-to-epub>
1) python scripts/ocr_status.py --base-dir <BOOK_DIR> --json
2) 确认 OCR 进程；可恢复停止则同 profile 断点续跑。
3) 本会话汇报：validated/total、remaining、eta_local、进程状态。
4) remaining>0：按 eta_local（+10~15%缓冲，≥5分钟后）只创建 1 个 once（label 书名OCR进度，target new）；删除已触发任务，勿堆叠。
5) complete=true：
   - ocr-only：validate_ocr 后停止并汇报；删除本书剩余 once。
   - pdf-to-epub：validate_ocr → crop_figures → extract_table_notes → merge_rough → 标题 gate → typeset → EPUB → validate_epub；成功回传 EPUB 并删除本书剩余 once。
不得用文件数量冒充完成；不得泄露密钥；不要 android-notification（除非用户明确要求）。
```

## 环境
- minis：`minis-scheduled` once + `target new`（App 内新会话）。
- Linux/OpenClaw：环境内可靠 one-shot / agentTurn。
- prompt 只写 profile 名，不写 API key。

## 生命周期
- 任务成功结束（OCR-only 校验完成，或 EPUB 校验完成）：清未执行定时任务。
- PDF→EPUB：保留工作目录待用户验收；验收后按 Acceptance Gate 清理。
