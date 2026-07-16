#!/usr/bin/env bash
# Example dual-profile OCR env for pdf-set. Copy and fill; do not commit real keys.
# Usage:
#   source scripts/ocr_env.example.sh
#   export PDF_OCR_PROFILE=backup   # or primary
#   python scripts/ocr.py --list-profiles
set -euo pipefail

: "${PDF_OCR_PRIMARY_API_KEY:?set primary key}"
: "${PDF_OCR_BACKUP_API_KEY:?set backup key}"

export PDF_OCR_PROFILES="${PDF_OCR_PROFILES:-primary,backup}"
export PDF_OCR_PRIMARY_BASE_URL="${PDF_OCR_PRIMARY_BASE_URL:-https://api.example.com/v1}"
export PDF_OCR_PRIMARY_MODEL="${PDF_OCR_PRIMARY_MODEL:-gpt-5.6-terra}"
export PDF_OCR_BACKUP_BASE_URL="${PDF_OCR_BACKUP_BASE_URL:-https://api.example.com/v1}"
export PDF_OCR_BACKUP_MODEL="${PDF_OCR_BACKUP_MODEL:-grok-4.5}"
# Default active profile (override per run)
export PDF_OCR_PROFILE="${PDF_OCR_PROFILE:-backup}"

_active="${PDF_OCR_PROFILE}"
case "${_active}" in
  primary) _model="${PDF_OCR_PRIMARY_MODEL}" ;;
  backup)  _model="${PDF_OCR_BACKUP_MODEL}" ;;
  *)       _model="unknown" ;;
esac
echo "[pdf-set OCR] profile=${_active} model=${_model}" >&2
unset _active _model
