"""Scrubbing messages before they are stored or shown (spec 30 section 4)."""

import re

from masterba.guard.detect import find, preview

_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s@:]+(?::[^/\s@]*)?@")
_HEADER = re.compile(
    r"(?i)((?:authorization|x-api-key|api-key|proxy-authorization)[\"']?\s*[:=]\s*[\"']?)"
    r"(?:bearer\s+|basic\s+)?[^\s\"',}]+"
)


def scrub(text: str) -> str:
    """Every finding replaced by its preview, credentials in URLs and headers removed."""
    text = _USERINFO.sub(r"\1***@", text)
    text = _HEADER.sub(r"\1***", text)
    findings = find(text)
    if not findings:
        return text
    parts: list[str] = []
    cursor = 0
    for finding in findings:
        parts.append(text[cursor : finding.start])
        parts.append(preview(finding))
        cursor = finding.end
    parts.append(text[cursor:])
    return "".join(parts)
