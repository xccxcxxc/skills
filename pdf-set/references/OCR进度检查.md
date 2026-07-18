# OCR 进度检查

仅在用户要求**全书 PDF→EPUB 且需要后台自动跟进**时使用。用户只要求 OCR 时，OCR 完成后停在 `validate_ocr.py`，不要建 ETA 定时。

## 状态来源
不要用 `ls *.md | wc -l`（fail/partial/旧结果会冒充完成）。统一：

```bash
python scripts/ocr_status.py --base-dir "书籍目录" --json
```

完成页定义：`N.meta.json` 且 `status=ok` + `validated=true`。

关注字段：`total` / `validated` / `remaining` / `seconds_per_page_median` / `eta_local` / `complete`。

## ETA 怎么定
1. 优先用 `ocr_status.py` 的 `eta_local`。
2. 调度时间 = ETA + **10–15% 缓冲**；若距现在不足 **5 分钟**，则至少排到 5 分钟后。
3. 进程刚启动、样本不足时：等至少 **3～5 页** validated 再算 ETA 并建定时；不要用拍脑袋间隔（如每 10 分钟扫一次）。
4. 每次检查后必须用**最新**速度重算；不得沿用过期 ETA。

## 定时任务（强制）
- 每本书全程只保留 **1 个** once（同一 label，如 `书名OCR进度`）。
- **禁止**一次创建多个固定间隔检查。
- **禁止**未完成时删掉检查却不建下一次。
- 到点检查：
  1. 读 `ocr_status.py --json`；确认 `logs/ocr.pid`（或等价进程）。
  2. 可恢复停止 → 同 profile 断点续跑；出现 `*.fail.json` / 配额 / 认证错误 → **停止死循环**，在会话说明原因。
  3. `remaining>0` → 重算 ETA，**只建 1 个**下一次 once；删已触发/过期任务。
  4. `complete=true` →  
     `validate_ocr` → `crop_figures` → `extract_table_notes` → `merge_rough` → 标题分类 gate →（标题就绪后）typeset → EPUB → `validate_epub`。  
     全流程成功后：**删除本书所有剩余 once**，并在会话回传 EPUB。

## 汇报方式（默认 = App 内）
- **默认**：用 `minis-scheduled`（或当前环境等价调度）在到点 **开新会话 / 会话内回复** 写进度。这就是“通知”。
- 汇报至少包含：`validated/total`、`remaining`、`eta_local`、进程是否存活、下一步（续跑 / 已建下次检查 / 进入合并导出）。
- **不要**默认调用 `android-notification` 系统通知。
- 仅当用户**明确要求**系统通知时，才额外 `android-notification`。

## minis 调度示例

```bash
minis-scheduled create \
  --time HH:MM \
  --repeat once \
  --label "书名OCR进度" \
  --target new \
  --prompt "……见下方模板……"
```

## 推荐调度 prompt

```text
检查《书名》PDF→EPUB 流水线（App 内汇报即可，不要发系统通知）。
工作目录：<BOOK_DIR>
1) python scripts/ocr_status.py --base-dir <BOOK_DIR> --json
2) 确认 OCR 进程；可恢复停止则同 profile 断点续跑。
3) 在本会话汇报：validated/total、remaining、eta_local、进程状态。
4) remaining>0：按 eta_local（+10~15%缓冲，≥5分钟后）只创建 1 个 once（label 书名OCR进度，target new）；删除已触发任务，勿堆叠。
5) complete=true：validate_ocr → crop_figures → extract_table_notes → merge_rough → 标题分类 gate；标题就绪后 typeset、导出 EPUB、validate_epub。成功后回传 EPUB 并删除本书剩余 once。
不得用文件数量冒充完成；不得泄露密钥；不要 android-notification（除非用户明确要求）。
```

## 环境
- minis：`minis-scheduled` once + `target new`（App 内新会话）。
- Linux/OpenClaw：环境内可靠的 one-shot / cron agentTurn。
- prompt 只写 profile 名，不写 API key。

## 生命周期
- EPUB 校验成功：清未执行定时任务；保留工作目录待用户验收。
- 用户验收后：按 EPUB Acceptance Gate 清理中间产物。
