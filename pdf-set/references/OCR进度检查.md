# OCR 进度检查

## 原则（无条件）
凡启动 OCR / PDF→EPUB 等会跑页的任务，**必须**向用户汇报进度，**不得**以页数少、耗时短、用户没口头要求等理由跳过。

- **马上能结束**（已在当次回复内跑完）：结束立刻在**当前会话**汇报结果，不必再挂定时。
- **不能马上结束**（后台 / 多页 / 当次回复结束时仍在跑）：必须用 `ocr_status.py` 算 ETA，建立 **1 个** once，到点在 **App 内会话**汇报；未完成则续建下一次，直到完成。
- 用户无需每次说「跟进 / 通知」。
- **默认 App 内会话**汇报；不要默认系统通知。仅用户明确要求系统通知时才 `android-notification`。

## OCR-only vs 全书导出
| 用户目标 | 进行中 | 完成后 |
|---|---|---|
| 只要 OCR | ETA / 完成汇报 | `validate_ocr.py` 后**停止** |
| PDF→EPUB | 同上 | validate → crop_figures → extract_table_notes → merge → 标题 gate → typeset → EPUB → validate_epub |

## 状态来源
不要用 `ls *.md | wc -l`。统一：

```bash
python scripts/ocr_status.py --base-dir "书籍目录" --json
```

完成页：`N.meta.json` 且 `status=ok` + `validated=true`。  
字段：`total` / `validated` / `remaining` / `seconds_per_page_median` / `eta_local` / `complete`。

## ETA
1. 用 `eta_local`；调度 = ETA + **10–15% 缓冲**，且距现在 **≥5 分钟**（若 ETA 更近：能等则等到完成并马上汇报；否则至少 5 分钟后查一次，避免空转）。
2. 样本不足时先跑出若干页再估；有 ETA 后**立即**建 once，不要等用户催。
3. 每次检查后按最新速度重算，禁止沿用过期 ETA。

## 定时任务
- 同一工作目录只保留 **1 个** once（label 如 `书名OCR进度`）。
- 禁止一次堆多个固定间隔检查。
- 禁止未完成时只删不建。
- 到点：
  1. 读 status；确认进程；可恢复则续跑。
  2. 失败/配额/认证：停死循环，会话说明。
  3. `remaining>0`：汇报 + 只建下一次 once。
  4. `complete=true`：按任务类型收尾（上表），汇报/回传，**删除本书剩余 once**。

## 汇报内容
至少：`validated/total`、`remaining`、`eta_local`、进程是否存活、下一步。

## minis

```bash
minis-scheduled create \
  --time HH:MM \
  --repeat once \
  --label "书名OCR进度" \
  --target new \
  --prompt "……模板……"
```

## 调度 prompt 模板

```text
检查《书名》OCR/EPUB 进度（App 内汇报，不要系统通知）。
工作目录：<BOOK_DIR>
任务类型：<ocr-only | pdf-to-epub>
1) python scripts/ocr_status.py --base-dir <BOOK_DIR> --json
2) 确认进程；可恢复则同 profile 续跑。
3) 本会话汇报 validated/total、remaining、eta_local、进程状态。
4) remaining>0：按 eta_local（+10~15%缓冲，≥5分钟后）只建 1 个 once（label 书名OCR进度，target new）；删已触发任务。
5) complete=true：
   - ocr-only：validate_ocr 后停止并汇报；删剩余 once。
   - pdf-to-epub：validate_ocr → crop_figures → extract_table_notes → merge_rough → 标题 gate → typeset → EPUB → validate_epub；回传 EPUB；删剩余 once。
不得用文件数冒充完成；不得泄露密钥。
```

## 生命周期
任务成功结束即清未执行 once。PDF→EPUB 保留工作目录待验收。
