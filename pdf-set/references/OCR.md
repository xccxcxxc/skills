CRITICAL: 
- 先提供命令（windows环境下的绝对路径）给用户让用户自己运行，用户要求你来执行命令时，你再执行命令。
- 一旦命令开始执行，进度条显示[RUNNING]，你就不应重复执行任务或者擅自中断任务──直至命令执行完毕，显示[OVER]再做出反应。
- 如果当前 AI 客户端支持后台任务，命令开始运行后用**中文**告诉用户去后台任务或终端输出中查看进度，并把对话控制权交还给用户，等待用户下一步指令。
- 若用户未指定开始和中止页码，不需要你来执行任何powershell命令来判断页数，你不应该擅自指定 --start; --end;和--batch 参数，你调用的脚本会自动判断页数。
- 若用户指定了开始和中止页码──你在列plan时不要把任务分很多条命令的小任务，如果你读取到的start参数是0, end参数是451, 那么你就列一条命令，像是`python skills/pdf-set/scripts/ocr.py --base-dir "C:\path\to" --book-name "某书" --start 0 --end 451`就可以了。不可以用`--start 0 --end 50`、`--start 51 --end 100`……`--start 400 --end 451`这样的多份小任务分批处理。

## 输入/输出
- 输入：`images/` 中的图片文件（支持 jpg/jpeg/png/bmp/tif/tiff/webp），按文件名前序号排序。
- 输入（单文件）：指定单张图片文件路径。
- 输出：`ocr-result/` 中的单页文件，文件名为「原图序号.md」，一一对应。
  - 单文件输出：默认写入 `ocr-result/`，文件名为「原图文件名.md」，也可指定输出文件路径。

## 脚本参考

- 使用 `scripts/ocr.py` 完成 OCR。
- OCR 统一使用 OpenAI Python 库及 `assets/secrets_openai.txt` 配置。
- 默认按当前工作目录推导路径：
  - 输入：`<当前目录>/images/`
  - 输出：`<当前目录>/ocr-result/`
  - Prompt：`<skill-dir>/assets/ocr_prompt.md`
  - 密钥配置：`<skill-dir>/assets/secrets_openai.txt`，需包含 `base_url`、`api_key`、`model`
- 可选参数：
  - `--base-dir` 指定书籍目录
  - `--book-name` 指定书籍名（自动定位到 `<base-dir>/<书籍名>`）
  - `--input-dir` 指定完整输入目录
  - `--input-file` 指定单张图片路径（将忽略 `--input-dir` 与 `--start/--end`）
  - `--output-dir` 指定完整输出目录
  - `--output-file` 指定单张输出 Markdown 文件路径
  - `--start` 指定起始序号（含）
  - `--end` 指定结束序号（含）
  - `--batch-size` 指定并发批次大小
  - `--prompt-file` 指定 prompt 文件路径
  - `--base-dir-from` 使用 UTF-8 文本文件提供书籍目录（首个非空行）
  - `--input-dir-from` 使用 UTF-8 文本文件提供输入目录（首个非空行）
  - `--input-file-from` 使用 UTF-8 文本文件提供单张图片路径（首个非空行）
  - `--output-dir-from` 使用 UTF-8 文本文件提供输出目录（首个非空行）
  - `--output-file-from` 使用 UTF-8 文本文件提供单张输出文件路径（首个非空行）
  - `--prompt-file-from` 使用 UTF-8 文本文件提供 prompt 文件路径（首个非空行）

示例：

```bash
python skills/pdf-set/scripts/ocr.py --base-dir "C:\path\to" --book-name "某书" --start 0 --end 20
```

单文件示例：

```bash
python skills/pdf-set/scripts/ocr.py --input-file "C:\path\to\images\20.jpg"
```

```bash
python skills/pdf-set/scripts/ocr.py --input-file "C:\path\to\images\20.jpg" --output-file "C:\path\to\ocr-result\20.md"
```

## 阶段 1：检查该书籍目录下images目录是否存在

## 阶段 2: 按照我的要求设置脚本的参数，不设置任何多余项。

## 阶段 3：不做任何其他检查地，运行你设置好必要参数后的脚本。

## 阶段4: 把脚本留在后台运行，等待用户进一步指令。
