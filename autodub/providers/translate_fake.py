"""Deterministic translation fake (no network). Used by tests."""
from __future__ import annotations


class FakeTranslator:
    """Prefix the target code; deterministic and reversible for assertions."""

    def translate(self, text: str, source: str, target: str) -> str:
        return f"[{target}] {text}"
