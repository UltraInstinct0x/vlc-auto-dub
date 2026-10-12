"""vlc-auto-dub: practical end-to-end dubbing pipeline."""
import os as _os
import ssl as _ssl

__version__ = "0.1.0"


def _ensure_ca_bundle() -> None:
    """Point Python at certifi's CA bundle when it has no usable one.

    python.org builds on macOS ship without a CA store until "Install
    Certificates.command" is run, so model/voice/translation-pack downloads fail
    with CERTIFICATE_VERIFY_FAILED. Only applied when nothing is configured.
    """
    if _os.environ.get("SSL_CERT_FILE") or _os.environ.get("SSL_CERT_DIR"):
        return
    paths = _ssl.get_default_verify_paths()
    if (paths.cafile and _os.path.exists(paths.cafile)) or (
        paths.capath and _os.path.isdir(paths.capath) and _os.listdir(paths.capath)
    ):
        return
    try:
        import certifi
    except ImportError:
        return
    _os.environ["SSL_CERT_FILE"] = certifi.where()


_ensure_ca_bundle()
