"""Real offline translation via argostranslate (CPU, no API key).

The required language package is installed on demand from the Argos package
index. Correctness note: ``argostranslate.translate.get_installed_languages`` is
``lru_cache``d, so a package installed during a run is invisible to argos's own
``translate()`` until the cache is cleared. We clear it after any install and
then *verify* the pair actually resolves; if it does not, we raise -- we never
let argos silently return the source text.
"""
from __future__ import annotations

from ..errors import DependencyError, ProviderError

# Pivot language for pairs Argos has no direct pack for.
PIVOT = "en"


class ArgosTranslator:
    def __init__(self) -> None:
        self._ready: set[tuple[str, str]] = set()
        self._routes: dict[tuple[str, str], list[tuple[str, str]]] = {}
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

    @staticmethod
    def _install_hint(source: str, target: str) -> str:
        return (
            f"argospm install translate-{source}_{target}  "
            f"(package: translate-{source}_{target})"
        )

    @staticmethod
    def _cache_clear() -> None:
        from argostranslate.translate import get_installed_languages

        try:
            get_installed_languages.cache_clear()
        except AttributeError:  # pragma: no cover - not cached in some versions
            pass

    def _pair_resolves(self, source: str, target: str) -> bool:
        """True only if argos can resolve source->target with the current cache."""
        from argostranslate.translate import (
            get_installed_languages,
            get_translation_from_codes,
        )

        try:
            installed = get_installed_languages()
        except Exception:  # a partial/corrupt package dir must not crash the scan
            installed = []
        for lang in installed:
            if lang.code != source:
                continue
            if any(t.to_lang.code == target for t in lang.translations_from):
                try:
                    get_translation_from_codes(source, target)
                    return True
                except Exception:
                    return False
        return False

    def _ensure_pair(self, source: str, target: str) -> None:
        if (source, target) in self._ready:
            return
        pkg, _tr = self._load()
        install_hint = self._install_hint(source, target)

        if self._pair_resolves(source, target):
            self._ready.add((source, target))
            return

        # Not installed yet: fetch it, then clear the lru_cache so argos sees the
        # newly installed package, and re-verify.
        try:
            pkg.update_package_index()
            for p in pkg.get_available_packages():
                if p.from_code == source and p.to_code == target:
                    pkg.install_from_path(p.download())
                    break
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"argos has no installed translation for {source!r}->{target!r} and it "
                f"could not be downloaded ({exc}). Install it once with network access: "
                f"{install_hint}"
            ) from exc

        self._cache_clear()
        if not self._pair_resolves(source, target):
            raise ProviderError(
                f"argos has no usable translation for {source!r}->{target!r} after install "
                f"attempt; not every pair exists. Install/verify with: {install_hint}"
            )
        self._ready.add((source, target))

    def _route(self, source: str, target: str) -> list[tuple[str, str]]:
        """Return the translation legs: direct, or through English when no direct
        pack exists (Argos ships most languages only to/from English, e.g. there is
        no es->tr pack but es->en and en->tr exist)."""
        if (source, target) in self._routes:
            return self._routes[(source, target)]
        try:
            self._ensure_pair(source, target)
            route = [(source, target)]
        except ProviderError as direct_error:
            if PIVOT in (source, target):
                raise
            try:
                self._ensure_pair(source, PIVOT)
                self._ensure_pair(PIVOT, target)
            except ProviderError:
                raise direct_error from None
            route = [(source, PIVOT), (PIVOT, target)]
        self._routes[(source, target)] = route
        return route

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target:
            return text
        _pkg, tr = self._load()
        for src, tgt in self._route(source, target):
            try:
                text = tr.translate(text, src, tgt)
            except Exception as exc:  # noqa: BLE001
                raise ProviderError(
                    f"argos translation {src!r}->{tgt!r} failed: {exc}; verify the pack: "
                    f"{self._install_hint(src, tgt)}"
                ) from exc
        return text
