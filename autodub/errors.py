"""Typed errors with actionable, single-line messages."""


class AutoDubError(Exception):
    """Base error. ``str(exc)`` is meant to be shown to the user directly."""


class InputError(AutoDubError):
    """Bad or missing CLI input (file, language, provider name)."""


class DependencyError(AutoDubError):
    """A required external binary or Python package is missing."""


class ProviderError(AutoDubError):
    """A provider (STT/translate/TTS) failed at runtime."""


class MediaError(AutoDubError):
    """ffmpeg/ffprobe failed."""
