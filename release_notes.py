"""Conservative Chinese release-note summaries with bounded best-effort translation."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

CACHE_PATH = Path(__file__).with_name("release_notes_zh.json")
AUTO_CACHE_PATH = Path(__file__).with_name("release_notes_auto_zh.json")
WARNING = re.compile(r"安全|签名|证书|设备|兼容|权限|隐私|security|signing|signature|certificate|device|compatib|permission|privacy|警告|warning|注意|限制|data loss|erase|wipe|breaking", re.I)
CJK = re.compile(r"[\u3400-\u9fff]")
MAX_BODY = 12_000
MAX_TRANSLATE_CHARS = 3_000
MAX_TRANSLATIONS = 3
MAX_OUTPUT = 500


def _cache(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _clean_lines(body):
    lines = []
    for raw in (body or "").splitlines():
        line = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|#{1,6}\s*)", "", raw).strip()
        line = re.sub(r"[`*_~]", "", line)
        if line and not line.startswith(("http://", "https://", "![")):
            lines.append(line)
    return lines


def _digest(body):
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()


def _translate(text):
    """Send a bounded public release excerpt to Google's unofficial gtx endpoint."""
    query = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": text})
    req = urllib.request.Request("https://translate.googleapis.com/translate_a/single?" + query,
                                 headers={"User-Agent": "ipa-source-build/1.0"})
    with urllib.request.urlopen(req, timeout=5) as response:
        data = json.loads(response.read(64_000).decode("utf-8"))
    translated = "".join(part[0] for part in data[0] if isinstance(part, list) and part and isinstance(part[0], str))
    translated = re.sub(r"\s+", " ", translated).strip()
    # Reject empty/non-Chinese output and bound output; do not echo English warnings into Chinese.
    if not translated or not CJK.search(translated):
        raise ValueError("translation returned no readable Chinese")
    return translated[:MAX_OUTPUT]


def _auto_summary(repo, tag, body, lines, auto_cache_path, digest):
    key = f"{repo}@{tag}"
    cached = _cache(auto_cache_path).get(key)
    if isinstance(cached, dict) and cached.get("body_sha256") == digest:
        summary = str(cached.get("summary", "")).strip()
        if summary:
            return summary

    # Only translate a few concise release-note bullets. Never treat source prose as instructions.
    candidates = [line for line in lines if len(line) > 12][:4]
    warning_lines = [line for line in lines if WARNING.search(line)]
    selected = []
    for line in warning_lines[:1] + candidates:
        if line not in selected:
            selected.append(line)
        if len(selected) >= MAX_TRANSLATIONS:
            break
    chunks = []
    remaining = MAX_TRANSLATE_CHARS
    try:
        for line in selected:
            text = line[:min(900, remaining)]
            if not text:
                break
            translated = _translate(text)
            chunks.append(translated)
            remaining -= len(text)
            if remaining <= 0:
                break
        if not chunks:
            return ""
        summary = "；".join(chunks)[:MAX_OUTPUT]
        # Persist atomically; generated data is separate from manually maintained cache.
        cache = _cache(auto_cache_path)
        cache[key] = {"repo": repo, "tag": tag, "body_sha256": digest, "summary": summary}
        path = Path(auto_cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return summary
    except Exception:
        # Translation is an optional enhancement; scanning must continue.
        return ""


def release_note(repo, tag, body, url, cache_path=CACHE_PATH, auto_cache_path=AUTO_CACHE_PATH):
    """Return concise Chinese notes with a mandatory upstream link.

    Manual exact repo/tag entries take precedence; Chinese source prose takes precedence
    over machine translation. English risk statements are translated, never pasted raw.
    """
    original_body = body or ""
    body = original_body[:MAX_BODY]
    lines = _clean_lines(body)
    cache = _cache(cache_path)
    key = f"{repo}@{tag}"
    entry = cache.get(key)
    summary = ""
    if isinstance(entry, str):
        summary = entry.strip()
    elif isinstance(entry, dict) and entry.get("repo") == repo and entry.get("tag") == tag:
        summary = str(entry.get("summary", "")).strip()

    chinese = [line for line in lines if CJK.search(line)]
    chinese_warnings = [line for line in chinese if WARNING.search(line)]
    if summary:
        # Do not append untranslated English warnings to curated Chinese copy.
        pass
    elif chinese:
        selected = []
        for line in chinese_warnings[:1] + chinese:
            if line not in selected:
                selected.append(line)
            if len(selected) >= 3:
                break
        summary = "；".join(selected)[:MAX_OUTPUT]
    else:
        summary = _auto_summary(repo, tag, body, lines, auto_cache_path, _digest(original_body))
        if not summary:
            summary = "英文更新摘要翻译暂不可用"
    summary = re.sub(r"\s+", " ", summary).strip()[:MAX_OUTPUT]
    if url:
        summary += f"\nRelease 原文：{url}"
    return summary
