import os
import sys
import time
import re
import base64
from datetime import datetime
import glob
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from openai import OpenAI

SCRIPT_DIR = os.path.dirname(__file__)
ASSETS_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "assets"))

# Temporary provider issues: rotate profile, but do NOT permanently discard it.
_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
# Likely account/quota issues: mark profile exhausted for this run.
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
    def __init__(self, profiles, start_name=None):
        if not profiles:
            raise ValueError(
                "No usable OCR profiles. Configure PDF_OCR_PROFILES plus "
                "PDF_OCR_<NAME>_{BASE_URL,API_KEY,MODEL}, or legacy "
                "PDF_OCR_{BASE_URL,API_KEY,MODEL}."
            )
        self._lock = Lock()
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
        self._clients = {}
        self._exhausted = set()
        # name -> unix timestamp until which this profile is temporarily skipped
        self._cooldown_until = {}

    def list_public(self):
        now = time.time()
        with self._lock:
            return [
                {
                    "name": p["name"],
                    "base_url": p["base_url"],
                    "model": p["model"],
                    "active": i == self._index,
                    "exhausted": p["name"] in self._exhausted,
                    "cooldown_remaining": max(
                        0, int(self._cooldown_until.get(p["name"], 0) - now)
                    ),
                }
                for i, p in enumerate(self.profiles)
            ]

    def current(self):
        with self._lock:
            return dict(self.profiles[self._index])

    def _is_temporarily_skipped(self, name, now=None):
        now = time.time() if now is None else now
        until = self._cooldown_until.get(name, 0)
        return until > now

    def client(self):
        with self._lock:
            now = time.time()
            total = len(self.profiles)
            # Prefer a profile that is neither exhausted nor cooling down.
            for step in range(total):
                idx = (self._index + step) % total
                profile = self.profiles[idx]
                name = profile["name"]
                if name in self._exhausted:
                    continue
                if self._is_temporarily_skipped(name, now):
                    continue
                self._index = idx
                if name not in self._clients:
                    self._clients[name] = OpenAI(
                        base_url=profile["base_url"],
                        api_key=profile["api_key"],
                    )
                return self._clients[name], dict(profile)

            # All profiles are cooling down or exhausted. Wait for the soonest cooldown.
            wait_candidates = [
                (name, until)
                for name, until in self._cooldown_until.items()
                if name not in self._exhausted and until > now
            ]
            if wait_candidates:
                name, until = min(wait_candidates, key=lambda x: x[1])
                wait_s = max(1, int(until - now) + 1)
                print(
                    f"\n[profile] all free profiles cooling down; "
                    f"waiting {wait_s}s for '{name}'..."
                )
                # Release lock while sleeping.
            else:
                wait_s = 0
                name = None

        if wait_s > 0:
            time.sleep(wait_s)
            with self._lock:
                for i, profile in enumerate(self.profiles):
                    if profile["name"] == name:
                        self._index = i
                        if name not in self._clients:
                            self._clients[name] = OpenAI(
                                base_url=profile["base_url"],
                                api_key=profile["api_key"],
                            )
                        print(
                            f"[profile] resuming '{profile['name']}' "
                            f"(model={profile['model']})"
                        )
                        return self._clients[name], dict(profile)

        raise RuntimeError("All OCR profiles exhausted or unavailable.")

    def switch(self, reason="", permanent=False, cooldown_seconds=30):
        with self._lock:
            current = self.profiles[self._index]
            now = time.time()
            if permanent:
                self._exhausted.add(current["name"])
                print(
                    f"\n[profile] '{current['name']}' exhausted"
                    + (f": {reason}" if reason else "")
                    + "; switching..."
                )
            else:
                until = now + max(1, int(cooldown_seconds))
                # Keep the longer cooldown if concurrent workers hit the same profile.
                prev = self._cooldown_until.get(current["name"], 0)
                self._cooldown_until[current["name"]] = max(prev, until)
                print(
                    f"\n[profile] '{current['name']}' temporary issue"
                    + (f": {reason}" if reason else "")
                    + f"; cooldown {int(self._cooldown_until[current['name']] - now)}s; switching..."
                )

            total = len(self.profiles)
            for step in range(1, total + 1):
                nxt = (self._index + step) % total
                candidate = self.profiles[nxt]
                name = candidate["name"]
                if name in self._exhausted:
                    continue
                if self._is_temporarily_skipped(name, now):
                    continue
                self._index = nxt
                print(
                    f"[profile] now using '{candidate['name']}' "
                    f"(model={candidate['model']})"
                )
                return dict(candidate)
            return None

    def available_count(self):
        now = time.time()
        with self._lock:
            return sum(
                1
                for p in self.profiles
                if p["name"] not in self._exhausted
                and not self._is_temporarily_skipped(p["name"], now)
            )


PROFILE_MANAGER = None


def countdown_timer(seconds):
    for remaining in range(seconds, 0, -1):
        sys.stdout.write(f"\rWaiting for {remaining} seconds...  ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\rWait complete!            \n")
    sys.stdout.flush()


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


def find_max_index(output_dir):
    if not os.path.isdir(output_dir):
        return -1
    nums = set()
    for name in os.listdir(output_dir):
        if name.endswith(".md"):
            stem = os.path.splitext(name)[0]
            if stem.endswith(".fail"):
                stem = stem[:-5]
            if stem.isdigit():
                nums.add(int(stem))
    idx = 0
    while idx in nums:
        idx += 1
    return idx - 1


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


def _cooldown_seconds_for_error(exc):
    status = _error_status_code(exc)
    text = str(exc).lower()
    if status == 429 or "rate limit" in text or "too many requests" in text:
        return 60
    if status in {500, 502, 503, 504} or "temporarily unavailable" in text:
        return 45
    return 30


def extract_text_from_openai_api(image_path, page_num, prompt_text):
    """
    Send one image to the configured OCR profile only.
    No auto-switch. On 503 / temporary provider errors, raise immediately.
    """
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
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "text", "text": f"文件名：{image_filename}"},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                        },
                    ],
                }
            ]
            response = client.chat.completions.create(
                model=selected_model,
                messages=messages,
            )

            finish_reason = _get_finish_reason(response)
            if finish_reason and "CONTENT_FILTER" in finish_reason.upper():
                return prohibited_sentinel
            if finish_reason and "PROHIBITED_CONTENT" in finish_reason.upper():
                return prohibited_sentinel

            content_text = _extract_text_from_response(response)
            if content_text:
                return content_text

            last_error_message = (
                f"Empty OCR response for page {page_num} "
                f"via profile '{profile['name']}' (attempt {attempt}/{max_attempts})"
            )

        except Exception as e:
            error_message = f"\nError processing page {page_num} via profile '{profile['name']}':\n"
            error_message += f"Error Type: {type(e).__name__}\n"
            error_message += f"Error Message: {str(e)}\n"
            status = _error_status_code(e)
            if status is not None:
                error_message += f"Status Code: {status}\n"
            if hasattr(e, "response"):
                error_message += f"Response: {e.response}\n"
            last_error_message = error_message

            # Strict mode: temporary provider/quota issues fail immediately.
            if _is_switchable_error(e) or status == 503:
                print(error_message)
                raise RuntimeError(
                    f"OCR profile '{profile['name']}' failed"
                    + (f" with status {status}" if status is not None else "")
                    + f": {e}"
                ) from e

            if attempt >= max_attempts:
                print(error_message)
                raise RuntimeError(error_message) from e

            time.sleep(min(2 ** attempt, 8))

    raise RuntimeError(last_error_message or f"OCR failed for page {page_num}")


def process_images(images_dir, output_dir, prompt_text, start_idx=None, end_idx=None, batch_size=6):
    if not os.path.isdir(images_dir):
        print(f"Images directory not found: {images_dir}")
        return

    os.makedirs(output_dir, exist_ok=True)

    exts = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tif", "*.tiff", "*.webp")
    image_files = []
    for ext in exts:
        image_files.extend(glob.glob(os.path.join(images_dir, ext)))
    if not image_files:
        print(f"No images found in: {images_dir}")
        return
    if start_idx is not None and end_idx is not None:
        filtered = []
        for path in image_files:
            name = os.path.splitext(os.path.basename(path))[0]
            if name.isdigit():
                num = int(name)
                if start_idx <= num <= end_idx:
                    filtered.append(path)
        image_files = filtered
        if not image_files:
            print(f"No images found in range {start_idx}-{end_idx}: {images_dir}")
            return
    image_files = sorted(
        image_files,
        key=lambda p: int(os.path.splitext(os.path.basename(p))[0])
        if os.path.splitext(os.path.basename(p))[0].isdigit()
        else os.path.basename(p),
    )

    total = len(image_files)
    fail_count = 0
    fail_lock = Lock()

    def _process_one(image_path, idx):
        nonlocal fail_count
        text = extract_text_from_openai_api(image_path, idx, prompt_text)
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        if text == "__PROHIBITED_CONTENT__":
            out_path = os.path.join(output_dir, f"{base_name}.fail.md")
            try:
                with open(out_path, "w", encoding="utf-8") as md_file:
                    md_file.write("")
            except Exception:
                pass
            with fail_lock:
                fail_count += 1
            return
        if text is None:
            raise RuntimeError(f"No content after retries on page {idx}. Please intervene.")
        out_path = os.path.join(output_dir, f"{base_name}.md")
        try:
            with open(out_path, "w", encoding="utf-8") as md_file:
                md_file.write(text)
        except Exception:
            pass

    completed = 0
    batch_size = max(1, int(batch_size or 1))
    items = list(enumerate(image_files, start=1))
    update_progress(0, total)
    for i in range(0, total, batch_size):
        batch = items[i : i + batch_size]
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = [executor.submit(_process_one, image_path, idx) for idx, image_path in batch]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"\n{e}")
                    sys.exit(1)
                completed += 1
                update_progress(completed, total)

    if fail_count:
        print(f"Fail pages: {fail_count}")


def process_single_image(image_path, output_dir, output_file, prompt_text):
    if not os.path.isfile(image_path):
        print(f"Image file not found: {image_path}")
        return

    if output_file:
        out_path = output_file
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
    else:
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        out_path = os.path.join(output_dir, f"{base_name}.md")

    text = extract_text_from_openai_api(image_path, 1, prompt_text)
    if text == "__PROHIBITED_CONTENT__":
        fail_path = os.path.join(
            output_dir, f"{os.path.splitext(os.path.basename(image_path))[0]}.fail.md"
        )
        try:
            with open(fail_path, "w", encoding="utf-8") as md_file:
                md_file.write("")
        except Exception:
            pass
        return
    if text is None:
        print("No content after retries. Please intervene.")
        sys.exit(1)
    try:
        with open(out_path, "w", encoding="utf-8") as md_file:
            md_file.write(text)
    except Exception:
        pass


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
        help="Concurrent batch size (default: PDF_OCR_BATCH_SIZE or 6).",
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
            flags = []
            if item.get("exhausted"):
                flags.append("exhausted")
            if item.get("cooldown_remaining"):
                flags.append(f"cooldown={item['cooldown_remaining']}s")
            flag_text = f" [{', '.join(flags)}]" if flags else ""
            print(
                f"  {mark} {item['name']}: model={item['model']} "
                f"base_url={item['base_url']}{flag_text}"
            )
        return

    current = PROFILE_MANAGER.current()
    print(
        f"Active OCR profile: {current['name']} "
        f"(model={current['model']}, base_url={current['base_url']})"
    )
    print("Mode: single profile only; no auto profile switch. Temporary 503/quota errors fail immediately.")
    if args.batch_size is None:
        raw_batch = _env("PDF_OCR_BATCH_SIZE")
        try:
            args.batch_size = int(raw_batch) if raw_batch else 6
        except ValueError:
            print(
                f"Invalid PDF_OCR_BATCH_SIZE={raw_batch!r}; falling back to 6."
            )
            args.batch_size = 6
    args.batch_size = max(1, int(args.batch_size))

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
    auto_start_from = None
    auto_end_from = None
    if input_file:
        start_idx = None
        end_idx = None
    elif start_idx is None and end_idx is None:
        auto_range = True
        max_idx = find_max_index(output_dir)
        start_idx = max_idx + 1
        auto_start_from = max_idx
        images_max_idx = find_max_image_index(images_dir)
        if images_max_idx >= start_idx:
            end_idx = images_max_idx
            auto_end_from = images_max_idx
        else:
            end_idx = start_idx + 49
            auto_end_from = end_idx

    prompt_text = _load_prompt(prompt_path)

    print(f"Images directory: {images_dir}")
    print(f"Input file: {input_file or '(none)'}")
    print(f"Output directory: {output_dir}")
    print(f"Output file: {output_file or '(auto)'}")
    if auto_range:
        print(f"Auto start from (last continuous output index): {auto_start_from}")
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
        )
    else:
        process_images(
            images_dir,
            output_dir,
            prompt_text,
            start_idx=start_idx,
            end_idx=end_idx,
            batch_size=args.batch_size,
        )


if __name__ == "__main__":
    main()
