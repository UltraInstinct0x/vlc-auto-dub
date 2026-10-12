"""One-line progress messages, flushed immediately (the VLC status reads them)."""
from __future__ import annotations


def progress(message: str) -> None:
    print(f"[autodub] {message}", flush=True)
