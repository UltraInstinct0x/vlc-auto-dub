"""Optional external translation backend (LibreTranslate-compatible HTTP).

**CODE-ONLY / UNTESTED.** This backend is never selected by default and is
never invoked by the shipped tests. It requires the operator to set
``AUTODUB_TRANSLATE_URL`` to a reachable endpoint (and optionally
``AUTODUB_TRANSLATE_KEY``). It must not be pointed at a public endpoint with
private media; send only the text spans you are allowed to share.

If it is not configured it raises a clear error instead of guessing.
"""
from __future__ import annotations

import json
import os
import urllib.request

from ..errors import DependencyError, ProviderError


class HttpTranslator:
    def __init__(self, url: str | None = None, api_key: str | None = None, timeout: float = 20.0):
        self.url = url or os.environ.get("AUTODUB_TRANSLATE_URL")
        self.api_key = api_key or os.environ.get("AUTODUB_TRANSLATE_KEY")
        self.timeout = timeout

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target:
            return text
        if not self.url:
            raise DependencyError(
                "provider 'http' is not configured: set AUTODUB_TRANSLATE_URL to a "
                "LibreTranslate-compatible endpoint (this backend is untested)"
            )
        payload = json.dumps(
            {"q": text, "source": source, "target": target, "format": "text"}
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}
        )
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body["translatedText"]
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"http translation request failed: {exc}") from exc
