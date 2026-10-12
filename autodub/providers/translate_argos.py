"""Real offline translation via argostranslate (CPU, no API key).

The required language package is installed on demand from the Argos package
index. If it cannot be fetched, a clear DependencyError/ProviderError is
raised -- no translation result is ever fabricated.
"""
from __future__ import annotations

from ..errors import DependencyError, ProviderError


class ArgosTranslator:
    def __init__(self) -> None:
        self._ready: set[tuple[str, str]] = set()
        self._module = None

    def _load(self):
        if self._module is None:
            try:
                import argostranslate.package as pkg
                import argostranslate.translate as tr
            except ImportError as exc:  # pragma: no cover
                raise DependencyError(
                    "provider 'argos' needs the 'argostranslate' package "
                    "(pip install argostranslate)"
                ) from exc
            self._module = (pkg, tr)
        return self._module

    def _ensure_pair(self, source: str, target: str) -> None:
        if (source, target) in self._ready:
            return
        pkg, tr = self._load()
        install_hint = (
            f"argospm install translate-{source}_{target}  "
            f"(package: translate-{source}_{target})"
        )

        from argostranslate.translate import get_installed_languages

        try:
            installed = get_installed_languages()
        except Exception:  # a partial/corrupt package dir must not crash the scan
            installed = []
        for lang in installed:
            if lang.code != source:
                continue
            if any(t.to_lang.code == target for t in lang.translations_from):
                self._ready.add((source, target))
                return
        try:
            pkg.update_package_index()
            for p in pkg.get_available_packages():
                if p.from_code == source and p.to_code == target:
                    pkg.install_from_path(p.download())
                    self._ready.add((source, target))
                    return
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"argos has no installed translation for {source!r}->{target!r} and it "
                f"could not be downloaded ({exc}). Install it once with network access: "
                f"{install_hint}"
            ) from exc
        raise ProviderError(
            f"argos has no offline translation package for {source!r}->{target!r}; "
            f"not every pair exists (try a pivot language such as English). "
            f"To check/install: {install_hint}"
        )

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target:
            return text
        self._ensure_pair(source, target)
        _pkg, tr = self._load()
        try:
            return tr.translate(text, source, target)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"argos translation failed: {exc}") from exc