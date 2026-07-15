import os
import sys
import time
import re
import base64
from datetime import datetime, timezone
import glob
import argparse
from openai import OpenAI

from table_utils import (
    atomic_write_json,
    atomic_write_text,
    natural_path_key,
    page_is_valid,
    page_meta_path,
    sanitize_html_table_block,
    sha256_file,
    sha256_text,
    validate_page_markdown,
    find_raw_table_blocks,
)

SCRIPT_DIR = os.path.dirname(__file__)
ASSETS_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "assets"))

_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_EXHAUST_STATUS_CODES = {402, 403}
_TRANSIENT_MESSAGE_MARKERS = (
    "service temporarily unavailable",
    "rate limit",
    "rate_limit",
    "too many requests",
    "overloaded",
    "capacity",
    "resource exhausted",
    "resource_exhausted",
    "temporarily unavailable",
    "model is overloaded",
    "server error",
    "upstream",
    "timeout",
    "timed out",
)
_EXHAUST_MESSAGE_MARKERS = (
    "quota",
    "insufficient",
    "billing",
    "credit",
    "balance",
    "exceeded your current quota",
    "payment required",
    "permission denied",
)


def _load_secrets_text(path):
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _extract_secret(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def _split_csv(value):
    if not value:
        return []
    return [part.strip() for part in re.split(r"[,;\s]+", value) if part.strip()]


def _normalize_profile_name(name):
    return re.sub(r"[^A-Za-z0-9_]+", "_", (name or "").strip()).strip("_")


def _profile_env_prefix(name):
    return f"PDF_OCR_{_normalize_profile_name(name).upper()}"


def _parse_profiles_from_secrets(text):
    """
    Optional multi-profile secrets format:

      profiles = primary,backup

      [primary]
      base_url = "..."
      api_key = "..."
      model = "..."

      [backup]
      base_url = "..."
      api_key = "..."
      model = "..."

    Legacy single-profile secrets without sections remain supported.
    """
    profiles = {}
    if not text.strip():
        return profiles

    section = None
    section_data = {}
    declared = []

    def _flush():
        nonlocal section, section_data
        if section and section_data:
            profiles[section] = dict(section_data)
        section = None
        section_data = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        m = re.match(r"^profiles\s*[:=]\s*(.+)$", line, flags=re.IGNORECASE)
        if m:
            declared = _split_csv(m.group(1).strip().strip("'\""))
            continue
        m = re.match(r"^\[([^\]]+)\]$", line)
        if m:
            _flush()
            section = _normalize_profile_name(m.group(1))
            continue
        m = re.match(
            r"^(base_url|api_key|model)\s*[:=]\s*['\"]?([^'\"#]+?)['\"]?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m and section:
            section_data[m.group(1).lower()] = m.group(2).strip()
            continue
        # legacy top-level keys without section
        m = re.match(
            r"^(base_url|api_key|model)\s*[:=]\s*['\"]?([^'\"#]+?)['\"]?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m and not section:
            profiles.setdefault("default", {})
            profiles["default"][m.group(1).lower()] = m.group(2).strip()

    _flush()

    if declared:
        ordered = {}
        for name in declared:
            key = _normalize_profile_name(name)
            if key in profiles:
                ordered[key] = profiles[key]
        # keep undeclared sections after declared ones
        for key, value in profiles.items():
            if key not in ordered:
                ordered[key] = value
        return ordered
    return profiles


def _discover_profile_names_from_env():
    names = []
    for key in os.environ:
        m = re.match(r"^PDF_OCR_([A-Z0-9_]+)_(BASE_URL|API_KEY|MODEL)$", key)
        if not m:
            continue
        name = m.group(1)
        if name in {"BASE", "API", "MODEL"}:
            # ignore malformed PDF_OCR_BASE_URL style matches if any
            continue
        if name not in names:
            names.append(name)
    # Preserve a stable order: PDF_OCR_PROFILES first, then discovery order.
    declared = [_normalize_profile_name(n).upper() for n in _split_csv(_env("PDF_OCR_PROFILES"))]
    ordered = []
    for name in declared:
        if name in names and name not in ordered:
            ordered.append(name)
    for name in names:
        if name not in ordered:
            ordered.append(name)
    return ordered


def load_ocr_profiles(secrets_text=""):
    """
    Load one or more OCR profiles.

    Priority for each field:
      1) named env: PDF_OCR_<NAME>_BASE_URL / _API_KEY / _MODEL
      2) secrets section [name]
      3) legacy single env: PDF_OCR_BASE_URL / PDF_OCR_API_KEY / PDF_OCR_MODEL
         or legacy secrets top-level keys (mapped to profile "default")
    """
    secret_profiles = _parse_profiles_from_secrets(secrets_text)
    names = []

    declared = [_normalize_profile_name(n) for n in _split_csv(_env("PDF_OCR_PROFILES"))]
    for name in declared:
        if name and name not in names:
            names.append(name)

    for name in secret_profiles:
        if name not in names:
            names.append(name)

    for name in _discover_profile_names_from_env():
        # env discovery uses upper-case tokens; normalize to original-ish lower/as-is form
        n = name.lower() if name.isupper() else name
        n = _normalize_profile_name(n)
        if n and n not in names:
            names.append(n)

    # legacy single-profile fallback
    legacy_base = _env("PDF_OCR_BASE_URL")
    legacy_key = _env("PDF_OCR_API_KEY")
    legacy_model = _env("PDF_OCR_MODEL")
    if not names and (legacy_base or legacy_key or legacy_model or "default" in secret_profiles):
        names = ["default"]

    profiles = []
    for raw_name in names:
        name = _normalize_profile_name(raw_name) or "default"
        prefix = _profile_env_prefix(name)
        secret = secret_profiles.get(name, {})
        if name == "default":
            secret = secret_profiles.get("default", secret)

        base_url = (
            _env(f"{prefix}_BASE_URL")
            or secret.get("base_url", "")
            or (legacy_base if name in ("default", names[0]) else "")
        )
        api_key = (
            _env(f"{prefix}_API_KEY")
            or secret.get("api_key", "")
            or (legacy_key if name in ("default", names[0]) else "")
        )
        model = (
            _env(f"{prefix}_MODEL")
            or secret.get("model", "")
            or (legacy_model if name in ("default", names[0]) else "")
        )

        # If only one named profile is declared and legacy single vars exist, allow them as fill-in.
        if len(names) == 1:
            base_url = base_url or legacy_base
            api_key = api_key or legacy_key
            model = model or legacy_model

        if not (base_url and api_key and model):
            missing = [k for k, v in (("base_url", base_url), ("api_key", api_key), ("model", model)) if not v]
            print(f"[warn] OCR profile '{name}' incomplete, missing: {', '.join(missing)}; skipped.")
            continue

        profiles.append(
            {
                "name": name,
                "base_url": base_url.rstrip("/"),
                "api_key": api_key,
                "model": model,
            }
        )

    return profiles


class ProfileManager:
    """Select exactly one OCR profile for a run; never fail over automatically."""
    def __init__(self, profiles, start_name=None):
        if not profiles:
            raise ValueError(
                "No usable OCR profiles. Configure PDF_OCR_PROFILES plus "
                "PDF_OCR_<NAME>_{BASE_URL,API_KEY,MODEL}, or legacy "
                "PDF_OCR_{BASE_URL,API_KEY,MODEL}."
            )
        self.profiles = list(profiles)
        self._index = 0
        if start_name:
            start = _normalize_profile_name(start_name)
            for i, profile in enumerate(self.profiles):
                if profile["name"].lower() == start.lower():
                    self._index = i
                    break
            else:
                available = ", ".join(p["name"] for p in self.profiles)
                raise ValueError(f"OCR profile '{start_name}' not found. Available: {available}")
        self._client = None

    def list_public(self):
        return [
            {
                "name": profile["name"],
                "base_url": profile["base_url"],
                "model": profile["model"],
                "active": idx == self._index,
            }
            for idx, profile in enumerate(self.profiles)
        ]

    def current(self):
        return dict(self.profiles[self._index])

    def client(self):
        profile = self.profiles[self._index]
        if self._client is None:
            self._client = OpenAI(base_url=profile["base_url"], api_key=profile["api_key"])
        return self._client, dict(profile)


PROFILE_MANAGER = None


class OCRPageOutputError(RuntimeError):
    """Model returned page text that must not be accepted as a completed page."""
    def __init__(self, message, *, output_text="", finish_reason="", profile=None):
        super().__init__(message)
        self.output_text = output_text or ""
        self.finish_reason = finish_reason or ""
        self.profile = profile or {}


def update_progress(completed, total):
    if total <= 0:
        return
    bar_length = 50
    progress = completed / total
    block = int(round(bar_length * progress))
    bar = "#" * block + "-" * (bar_length - block)
    pct = round(progress * 100, 2)
    status = "OVER" if completed >= total else "RUNNING"
    text = f"[{completed}/{total}][{bar}][{pct:.2f}%][{status}]"
    sys.stdout.write("\r\033[K" + text)
    sys.stdout.flush()
    if completed >= total:
        sys.stdout.write("\n")
        sys.stdout.flush()


def _read_image_bytes(image_path):
    with open(image_path, "rb") as f:
        return f.read()


def _guess_mime_type(image_path):
    ext = os.path.splitext(image_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext in (".tif", ".tiff"):
        return "image/tiff"
    if ext == ".bmp":
        return "image/bmp"
    return "image/jpeg"


def _extract_text_from_response(response):
    try:
        message = response.choices[0].message
    except Exception:
        return ""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if not content:
        return ""
    texts = []
    for part in content:
        text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts).strip()


def _get_finish_reason(response):
    try:
        choice = response.choices[0]
    except Exception:
        return ""
    for attr in ("finish_reason", "finishReason"):
        val = getattr(choice, attr, None)
        if val:
            return str(val)
    if isinstance(choice, dict):
        return choice.get("finishReason") or choice.get("finish_reason") or ""
    for method in ("model_dump", "to_dict"):
        if hasattr(response, method):
            try:
                data = getattr(response, method)()
                choice0 = (data.get("choices") or [None])[0] or {}
                return choice0.get("finishReason") or choice0.get("finish_reason") or ""
            except Exception:
                pass
    return ""


def read_single_path(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            value = line.strip()
            if value:
                return value
    return ""


def find_max_image_index(images_dir):
    if not os.path.isdir(images_dir):
        return -1
    exts = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
    max_idx = -1
    for name in os.listdir(images_dir):
        if name.lower().endswith(exts):
            stem = os.path.splitext(name)[0]
            if stem.isdigit():
                max_idx = max(max_idx, int(stem))
    return max_idx


def _load_prompt(prompt_path):
    if prompt_path and os.path.isfile(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content
    return "Extract and transcribe any visible text from this image, exactly as it appears."


def _error_status_code(exc):
    for attr in ("status_code", "status"):
        val = getattr(exc, attr, None)
        if val is not None:
            try:
                return int(val)
            except Exception:
                pass
    response = getattr(exc, "response", None)
    if response is not None:
        val = getattr(response, "status_code", None)
        if val is not None:
            try:
                return int(val)
            except Exception:
                pass
    m = re.search(r"\b([45]\d\d)\b", str(exc))
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def _classify_provider_error(exc):
    """
    Return one of: 'exhaust', 'transient', None
    """
    status = _error_status_code(exc)
    text = str(exc).lower()
    if status in _EXHAUST_STATUS_CODES:
        return "exhaust"
    if status in _TRANSIENT_STATUS_CODES:
        return "transient"
    if any(marker in text for marker in _EXHAUST_MESSAGE_MARKERS):
        return "exhaust"
    if any(marker in text for marker in _TRANSIENT_MESSAGE_MARKERS):
        return "transient"
    return None


def _is_switchable_error(exc):
    return _classify_provider_error(exc) is not None


def _extract_last_table_header_block(md_text, max_chars=2500):
    """Return last table header (GFM or HTML thead) from prior page OCR."""
    if not md_text:
        return ""
    text = md_text
    # Prefer last HTML table header (multi-level)
    html_matches = list(
        re.finditer(
            r"(?is)(?:<div\b[^>]*table-wrap[^>]*>\s*)?<table\b[^>]*>\s*"
            r"(?:<thead\b[^>]*>.*?</thead>|(?:<tr\b[^>]*>.*?</tr>\s*){1,3})",
            text,
        )
    )
    if html_matches:
        m = html_matches[-1]
        block = m.group(0).strip()
        # Prefer only thead if present for cleaner continuation prompt
        thead = re.search(r"(?is)<thead\b[^>]*>.*?</thead>", block)
        if thead:
            # include opening table tag attributes when possible
            open_tag = re.search(r"(?is)<table\b[^>]*>", block)
            wrap = re.search(r"(?is)<div\b[^>]*table-wrap[^>]*>", m.group(0))
            parts = []
            if wrap:
                parts.append(wrap.group(0))
            if open_tag:
                parts.append(open_tag.group(0))
            parts.append(thead.group(0))
            block = "\n".join(parts)
        if len(block) > max_chars:
            block = block[:max_chars]
        return block

    lines = text.splitlines()
    # Find last separator line of a pipe table
    sep_idx = None
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        if s.startswith("|") and re.search(r"-{3,}", s) and s.count("|") >= 2:
            sep_idx = i
            break
    if sep_idx is None or sep_idx == 0:
        return ""
    header_idx = sep_idx - 1
    if not lines[header_idx].strip().startswith("|"):
        return ""
    # Optional table title in the 1-2 non-empty lines above header
    title_parts = []
    j = header_idx - 1
    skipped_blank = 0
    while j >= 0 and len(title_parts) < 2:
        s = lines[j].strip()
        if not s:
            skipped_blank += 1
            if skipped_blank > 1:
                break
            j -= 1
            continue
        if s.startswith("|") or s.startswith("#"):
            break
        if s.startswith("<sup>") or s.startswith("资料来源"):
            break
        title_parts.insert(0, lines[j].rstrip())
        j -= 1
        break  # only one title line
    block_lines = title_parts + [lines[header_idx].rstrip(), lines[sep_idx].rstrip()]
    block = "\n".join(block_lines).strip()
    if len(block) > max_chars:
        block = block[-max_chars:]
    return block


def _prior_page_table_context(image_path, output_dir):
    """If previous numeric page OCR exists, extract its last table header for continuation."""
    base = os.path.splitext(os.path.basename(image_path))[0]
    if not base.isdigit() or not output_dir:
        return ""
    prev = int(base) - 1
    prev_path = os.path.join(output_dir, f"{prev}.md")
    if not os.path.isfile(prev_path):
        return ""
    try:
        with open(prev_path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return ""
    return _extract_last_table_header_block(text)


def _compose_page_prompt(prompt_text, image_filename, table_context=""):
    parts = [prompt_text, f"文件名：{image_filename}"]
    if table_context:
        parts.append(
            "【上页表格结构参考——仅当本页是同一表格的续页时使用】\n"
            "若本页开头继续上页未结束的表格：\n"
            "- 若参考是 GFM：使用完全相同的表头行与分隔行（列名、列序、列数一致）；\n"
            "- 若参考是 HTML：复制相同的 <table> 开标签与 <thead>…</thead>（rowspan/colspan 一致），"
            "再只写本页新数据的 <tbody> 行；\n"
            "只输出本页新出现的数据行；不要重复上页已有数据行；不要输出空表头；"
            "单元格内禁止换行。\n"
            "若本页是新表或与上表无关的正文，忽略本参考。\n"
            f"{table_context}"
        )
    return parts


def _sanitize_page_tables(text):
    """Validate and canonicalize model-generated raw HTML tables."""
    out = []
    pos = 0
    for block_start, block_end, block in find_raw_table_blocks(text):
        out.append(text[pos:block_start])
        out.append(sanitize_html_table_block(block))
        pos = block_end
    out.append(text[pos:])
    return "".join(out)


def _is_truncated_finish_reason(reason):
    value = (reason or "").strip().upper()
    return any(marker in value for marker in ("LENGTH", "MAX_TOKEN", "MAX_OUTPUT"))


def extract_text_from_openai_api(
    image_path,
    page_num,
    prompt_text,
    table_context="",
    max_tokens=8192,
):
    """OCR one image with one selected profile; fail closed on truncation."""
    prohibited_sentinel = "__PROHIBITED_CONTENT__"
    client, profile = PROFILE_MANAGER.client()
    selected_model = profile["model"]
    max_attempts = 3
    last_error_message = None

    for attempt in range(1, max_attempts + 1):
        try:
            image_bytes = _read_image_bytes(image_path)
            image_filename = os.path.basename(image_path)
            mime_type = _guess_mime_type(image_path)
            image_b64 = base64.b64encode(image_bytes).decode("ascii")
            content_parts = [
                {"type": "text", "text": p}
                for p in _compose_page_prompt(prompt_text, image_filename, table_context)
            ]
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                }
            )
            messages = [{"role": "user", "content": content_parts}]
            create_kwargs = {
                "model": selected_model,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            try:
                response = client.chat.completions.create(**create_kwargs)
            except Exception as token_err:
                msg = str(token_err).lower()
                if "max_tokens" in msg or "max_completion_tokens" in msg:
                    create_kwargs.pop("max_tokens", None)
                    create_kwargs["max_completion_tokens"] = max_tokens
                    try:
                        response = client.chat.completions.create(**create_kwargs)
                    except Exception:
                        create_kwargs.pop("max_completion_tokens", None)
                        response = client.chat.completions.create(
                            model=selected_model,
                            messages=messages,
                        )
                else:
                    raise

            finish_reason = _get_finish_reason(response)
            upper_reason = finish_reason.upper()
            if "CONTENT_FILTER" in upper_reason or "PROHIBITED_CONTENT" in upper_reason:
                return prohibited_sentinel, finish_reason, profile

            content_text = _extract_text_from_response(response)
            if _is_truncated_finish_reason(finish_reason):
                raise OCRPageOutputError(
                    f"OCR response truncated for page {page_num}: finish_reason={finish_reason}",
                    output_text=content_text,
                    finish_reason=finish_reason,
                    profile=profile,
                )
            if content_text:
                try:
                    content_text = _sanitize_page_tables(content_text)
                except Exception as validation_exc:
                    raise OCRPageOutputError(
                        f"OCR HTML validation failed for page {page_num}: {validation_exc}",
                        output_text=content_text,
                        finish_reason=finish_reason,
                        profile=profile,
                    ) from validation_exc
                errors = validate_page_markdown(content_text, allow_placeholders=True)
                if errors:
                    raise OCRPageOutputError(
                        f"OCR structural validation failed for page {page_num}: "
                        + "; ".join(errors),
                        output_text=content_text,
                        finish_reason=finish_reason,
                        profile=profile,
                    )
                return content_text, finish_reason or "stop", profile

            last_error_message = (
                f"Empty OCR response for page {page_num} "
                f"via profile '{profile['name']}' (attempt {attempt}/{max_attempts})"
            )

        except Exception as e:
            if isinstance(e, OCRPageOutputError) and e.output_text:
                # Preserve rejected model output for diagnosis; never count it as completed.
                atomic_write_text(
                    os.path.join(output_dir, f"{os.path.splitext(os.path.basename(image_path))[0]}.partial.md"),
                    e.output_text.rstrip() + "\n",
                )
            error_message = f"\nError processing page {page_num} via profile '{profile['name']}':\n"
            error_message += f"Error Type: {type(e).__name__}\n"
            error_message += f"Error Message: {str(e)}\n"
            status = _error_status_code(e)
            if status is not None:
                error_message += f"Status Code: {status}\n"
            last_error_message = error_message
            if status == 503 or _is_switchable_error(e):
                if attempt >= max_attempts:
                    print(error_message)
                    raise RuntimeError(error_message) from e
                wait = min(2 ** attempt, 12)
                print(f"{error_message}\nRetrying same profile in {wait}s...")
                time.sleep(wait)
                continue
            if attempt >= max_attempts:
                print(error_message)
                raise RuntimeError(error_message) from e
            time.sleep(min(2 ** attempt, 8))

    raise RuntimeError(last_error_message or f"OCR failed for page {page_num}")

def _page_metadata(image_path, text, prompt_text, profile, finish_reason):
    return {
        "status": "ok",
        "validated": True,
        "image_sha256": sha256_file(image_path),
        "prompt_sha256": sha256_text(prompt_text),
        "output_sha256": sha256_text(text),
        "profile": profile.get("name"),
        "model": profile.get("model"),
        "finish_reason": finish_reason or "stop",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_failed_page(output_dir, stem, status, error, extra=None):
    payload = {
        "status": status,
        "validated": False,
        "error": str(error),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)
    atomic_write_json(os.path.join(output_dir, f"{stem}.fail.json"), payload)


def process_images(
    images_dir,
    output_dir,
    prompt_text,
    start_idx=None,
    end_idx=None,
    batch_size=1,
    max_tokens=8192,
    trust_existing=False,
):
    if not os.path.isdir(images_dir):
        raise RuntimeError(f"Images directory not found: {images_dir}")
    os.makedirs(output_dir, exist_ok=True)

    exts = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tif", "*.tiff", "*.webp")
    image_files = []
    for ext in exts:
        image_files.extend(glob.glob(os.path.join(images_dir, ext)))
    if not image_files:
        raise RuntimeError(f"No images found in: {images_dir}")

    if start_idx is not None or end_idx is not None:
        filtered = []
        for path in image_files:
            stem = os.path.splitext(os.path.basename(path))[0]
            if not stem.isdigit():
                continue
            num = int(stem)
            if start_idx is not None and num < start_idx:
                continue
            if end_idx is not None and num > end_idx:
                continue
            filtered.append(path)
        image_files = filtered
        if not image_files:
            raise RuntimeError(f"No numeric images found in requested range: {start_idx}-{end_idx}")

    image_files = sorted(image_files, key=natural_path_key)
    total = len(image_files)
    prompt_hash = sha256_text(prompt_text)
    completed = 0
    skipped = 0
    update_progress(0, total)

    for idx, image_path in enumerate(image_files, start=1):
        stem = os.path.splitext(os.path.basename(image_path))[0]
        out_path = os.path.join(output_dir, f"{stem}.md")
        meta_path = page_meta_path(output_dir, stem)
        if trust_existing and os.path.isfile(out_path) and not os.path.isfile(meta_path):
            with open(out_path, "r", encoding="utf-8", errors="replace") as legacy_file:
                legacy_text = legacy_file.read()
            legacy_errors = validate_page_markdown(legacy_text, allow_placeholders=True)
            if not legacy_errors:
                atomic_write_json(
                    meta_path,
                    {
                        "status": "ok",
                        "validated": True,
                        "image_sha256": sha256_file(image_path),
                        "prompt_sha256": prompt_hash,
                        "output_sha256": sha256_file(out_path),
                        "profile": "legacy-adopted",
                        "model": "unknown",
                        "finish_reason": "legacy-adopted",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
        if page_is_valid(
            image_path,
            out_path,
            meta_path,
            prompt_hash=prompt_hash,
            trust_existing=trust_existing,
        ):
            skipped += 1
            completed += 1
            update_progress(completed, total)
            continue

        table_context = _prior_page_table_context(image_path, output_dir)
        page_num = int(stem) if stem.isdigit() else idx
        try:
            result = extract_text_from_openai_api(
                image_path,
                page_num,
                prompt_text,
                table_context=table_context,
                max_tokens=max_tokens,
            )
            text, finish_reason, profile = result
            if text == "__PROHIBITED_CONTENT__":
                _write_failed_page(
                    output_dir,
                    stem,
                    "prohibited",
                    f"finish_reason={finish_reason}",
                    {"finish_reason": finish_reason, "profile": profile.get("name")},
                )
                print(f"Prohibited OCR content on page {stem}; recorded as fail and continuing.")
                completed += 1
                update_progress(completed, total)
                continue
            errors = validate_page_markdown(text, allow_placeholders=True)
            if errors:
                raise RuntimeError("; ".join(errors))
            meta = _page_metadata(image_path, text, prompt_text, profile, finish_reason)
            atomic_write_text(out_path, text.rstrip() + "\n")
            meta["output_sha256"] = sha256_file(out_path)
            atomic_write_json(meta_path, meta)
            fail_path = os.path.join(output_dir, f"{stem}.fail.json")
            partial_path = os.path.join(output_dir, f"{stem}.partial.md")
            for stale_path in (fail_path, partial_path):
                if os.path.exists(stale_path):
                    os.remove(stale_path)
        except Exception as exc:
            _write_failed_page(
                output_dir,
                stem,
                "failed",
                exc,
                {"image_sha256": sha256_file(image_path), "prompt_sha256": prompt_hash},
            )
            print(f"Page {stem} failed and was recorded; continuing: {exc}")
        completed += 1
        update_progress(completed, total)

    fail_count = len(glob.glob(os.path.join(output_dir, "*.fail.json")))
    print(f"Validated/skipped existing pages: {skipped}")
    if fail_count:
        print(f"Failed pages: {fail_count}")
        raise RuntimeError(f"OCR completed with {fail_count} failed page(s). See *.fail.json")

def process_single_image(
    image_path,
    output_dir,
    output_file,
    prompt_text,
    max_tokens=8192,
):
    if not os.path.isfile(image_path):
        raise RuntimeError(f"Image file not found: {image_path}")

    if output_file:
        out_path = output_file
        out_dir = os.path.dirname(out_path) or "."
        os.makedirs(out_dir, exist_ok=True)
    else:
        os.makedirs(output_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(image_path))[0]
        out_path = os.path.join(output_dir, f"{stem}.md")
        out_dir = output_dir

    stem = os.path.splitext(os.path.basename(image_path))[0]
    table_context = _prior_page_table_context(image_path, out_dir)
    try:
        text, finish_reason, profile = extract_text_from_openai_api(
            image_path,
            int(stem) if stem.isdigit() else 1,
            prompt_text,
            table_context=table_context,
            max_tokens=max_tokens,
        )
        if text == "__PROHIBITED_CONTENT__":
            _write_failed_page(out_dir, stem, "prohibited", f"finish_reason={finish_reason}")
            raise RuntimeError(f"Prohibited OCR content on page {stem}")
        errors = validate_page_markdown(text, allow_placeholders=True)
        if errors:
            raise RuntimeError("; ".join(errors))
        atomic_write_text(out_path, text.rstrip() + "\n")
        meta = _page_metadata(image_path, text, prompt_text, profile, finish_reason)
        meta["output_sha256"] = sha256_file(out_path)
        atomic_write_json(page_meta_path(out_dir, stem), meta)
    except Exception as exc:
        _write_failed_page(out_dir, stem, "failed", exc)
        raise


def main():
    print("\n********************************")
    print("*** Image OCR to Markdown ***")
    print("********************************\n")

    parser = argparse.ArgumentParser(description="OCR images to per-page Markdown files.")
    parser.add_argument(
        "--base-dir",
        default=os.getcwd(),
        help="Book directory containing images/ and ocr-result/ (default: current directory).",
    )
    parser.add_argument(
        "--book-name",
        default=None,
        help="Optional book subfolder under --base-dir.",
    )
    parser.add_argument(
        "--base-dir-from",
        default=None,
        help="UTF-8 text file containing base directory (first non-empty line).",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Path to images folder (default: <base-dir>/images).",
    )
    parser.add_argument(
        "--input-file",
        default=None,
        help="Path to a single image file to OCR (overrides input dir).",
    )
    parser.add_argument(
        "--input-dir-from",
        default=None,
        help="UTF-8 text file containing input directory (first non-empty line).",
    )
    parser.add_argument(
        "--input-file-from",
        default=None,
        help="UTF-8 text file containing input file path (first non-empty line).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Path to output folder (default: <base-dir>/ocr-result).",
    )
    parser.add_argument(
        "--output-file",
        default=None,
        help="Path to output Markdown file for single-image OCR.",
    )
    parser.add_argument(
        "--output-dir-from",
        default=None,
        help="UTF-8 text file containing output directory (first non-empty line).",
    )
    parser.add_argument(
        "--output-file-from",
        default=None,
        help="UTF-8 text file containing output file path (first non-empty line).",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=None,
        help="Start index (inclusive) for numeric image filenames.",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=None,
        help="End index (inclusive) for numeric image filenames.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Deprecated compatibility option; OCR pages are always sequential.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=8192,
        help="Maximum OCR completion tokens per page (default: 8192).",
    )
    parser.add_argument(
        "--trust-existing",
        action="store_true",
        help="Adopt structurally valid legacy N.md files without metadata; use once for migration.",
    )
    parser.add_argument(
        "--prompt-file",
        default=None,
        help="Path to prompt file (default: <skill-dir>/assets/ocr_prompt.md).",
    )
    parser.add_argument(
        "--prompt-file-from",
        default=None,
        help="UTF-8 text file containing prompt file path (first non-empty line).",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="OCR profile name to start with (from PDF_OCR_PROFILES / named env vars).",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List configured OCR profiles (no secrets) and exit.",
    )
    args = parser.parse_args()

    secrets_path = os.path.join(ASSETS_DIR, "secrets_openai.txt")
    secrets_text = _load_secrets_text(secrets_path)

    try:
        profiles = load_ocr_profiles(secrets_text)
        start_profile = args.profile or _env("PDF_OCR_PROFILE") or None
        global PROFILE_MANAGER
        PROFILE_MANAGER = ProfileManager(profiles, start_name=start_profile)
    except Exception as e:
        print(str(e))
        sys.exit(1)

    if args.list_profiles:
        print("Configured OCR profiles:")
        for item in PROFILE_MANAGER.list_public():
            mark = "*" if item["active"] else " "
            print(
                f"  {mark} {item['name']}: model={item['model']} "
                f"base_url={item['base_url']}"
            )
        return

    current = PROFILE_MANAGER.current()
    print(
        f"Active OCR profile: {current['name']} "
        f"(model={current['model']}, base_url={current['base_url']})"
    )
    print("Mode: sequential pages; strict validation; no automatic profile switch.")
    args.batch_size = 1
    args.max_tokens = max(256, int(args.max_tokens))

    base_dir = args.base_dir
    if args.base_dir_from:
        base_dir_from = read_single_path(args.base_dir_from)
        if base_dir_from:
            base_dir = base_dir_from
    if args.book_name:
        base_dir = os.path.join(base_dir, args.book_name)

    images_dir = args.input_dir or os.path.join(base_dir, "images")
    if args.input_dir_from:
        input_dir_from = read_single_path(args.input_dir_from)
        if input_dir_from:
            images_dir = input_dir_from
    input_file = args.input_file
    if args.input_file_from:
        input_file_from = read_single_path(args.input_file_from)
        if input_file_from:
            input_file = input_file_from

    output_dir = args.output_dir or os.path.join(base_dir, "ocr-result")
    if args.output_dir_from:
        output_dir_from = read_single_path(args.output_dir_from)
        if output_dir_from:
            output_dir = output_dir_from
    output_file = args.output_file
    if args.output_file_from:
        output_file_from = read_single_path(args.output_file_from)
        if output_file_from:
            output_file = output_file_from

    prompt_path = args.prompt_file or os.path.join(ASSETS_DIR, "ocr_prompt.md")
    if args.prompt_file_from:
        prompt_file_from = read_single_path(args.prompt_file_from)
        if prompt_file_from:
            prompt_path = prompt_file_from

    start_idx = args.start
    end_idx = args.end
    if input_file:
        start_idx = None
        end_idx = None
    auto_range = False
    auto_end_from = None
    if input_file:
        start_idx = None
        end_idx = None
    elif start_idx is None and end_idx is None:
        auto_range = True
        # Scan all numeric images. Per-page metadata determines which pages are safely skipped.
        start_idx = None
        images_max_idx = find_max_image_index(images_dir)
        end_idx = images_max_idx if images_max_idx >= 0 else None
        auto_end_from = images_max_idx

    prompt_text = _load_prompt(prompt_path)

    print(f"Images directory: {images_dir}")
    print(f"Input file: {input_file or '(none)'}")
    print(f"Output directory: {output_dir}")
    print(f"Output file: {output_file or '(auto)'}")
    if auto_range:
        print(f"Auto end from (max image index or fallback): {auto_end_from}")
    print(f"Image index range: {start_idx}-{end_idx}")
    print(f"Prompt file: {prompt_path}")
    print(f"Batch size: {args.batch_size}")

    if input_file:
        process_single_image(
            input_file,
            output_dir,
            output_file,
            prompt_text,
            max_tokens=args.max_tokens,
        )
    else:
        process_images(
            images_dir,
            output_dir,
            prompt_text,
            start_idx=start_idx,
            end_idx=end_idx,
            batch_size=args.batch_size,
            max_tokens=args.max_tokens,
            trust_existing=args.trust_existing,
        )


if __name__ == "__main__":
    main()
