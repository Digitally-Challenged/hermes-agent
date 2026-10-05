"""TLS trust for Hermes. One authority, one trust source.

Trust comes from the platform verifier via ``truststore``: CryptoAPI on
Windows, Security.framework on macOS, and OpenSSL's own store (with a
distro candidate sweep) on Linux. That is the machine's real answer to
"is this chain valid", so a corporate MITM root installed by MDM, an
internal CA, and a locked-down NixOS box all work with no configuration.

``install_truststore()`` runs once at process start and patches
``ssl.SSLContext`` process-wide, so every stack that builds a default
context inherits it — httpx, requests/urllib3, aiohttp, AND the stdlib
``urllib.request`` call sites (the llama.cpp engine download among them)
that a certifi-only or requests-only approach never reached.

The only thing above the platform store is EXPLICIT PER-PROVIDER CONFIG:
``ssl_ca_cert`` (a self-signed or internal endpoint's bundle) and
``ssl_verify: false`` (local development). Those are deliberate
statements about one endpoint, not an ambient guess about the machine.
"""

from __future__ import annotations

import logging
import ssl
import sys
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_installed: bool | None = None


def install_truststore() -> bool:
    """Point every default SSLContext at the OS trust store. Idempotent.

    Returns True when the platform verifier is in force. A False return
    means truststore could not load (an unsupported platform, or a
    stripped payload); TLS still works off OpenSSL's compiled-in paths,
    it just won't see certificates the OS trusts.

    Call before the first HTTPS client is constructed.
    """
    global _installed
    if _installed is not None:
        return _installed
    try:
        import truststore

        truststore.inject_into_ssl()
        repin_botocore_ssl_context()
        _installed = True
        logger.debug("TLS trust: platform store (truststore)")
    except Exception as exc:  # noqa: BLE001 — never break startup over TLS setup
        _installed = False
        logger.warning(
            "truststore unavailable (%s); falling back to OpenSSL's default "
            "trust paths. Certificates trusted only by the OS store — a "
            "corporate root, for instance — will not verify.",
            exc,
        )
    return _installed


def repin_botocore_ssl_context() -> None:
    """Point an already-loaded ``botocore.httpsession.SSLContext`` at the live class.

    ``botocore/httpsession.py`` captures ``SSLContext`` once, at its own
    import time (``from urllib3.util.ssl_ import SSLContext``, or the
    pyopenssl fallback). truststore's ``inject_into_ssl()`` patches
    ``ssl.SSLContext`` and ``urllib3.util.ssl_.SSLContext`` but cannot know
    about botocore's copy, so a botocore loaded BEFORE the injection keeps the
    raw stdlib class. The WebUI does exactly that: its Bedrock model list loads
    botocore, and ``install_truststore()`` only runs once the first chat turn
    builds an HTTP client.

    A raw context built while ``ssl.SSLContext`` is replaced recurses forever
    on ``.options``: CPython 3.14's setter re-resolves ``SSLContext`` from the
    ``ssl`` module's globals on every call, so it calls right back into
    truststore's class. Every Bedrock credential resolution builds one (the
    ``ContainerMetadataFetcher``), including the Anthropic SDK's Bedrock signer,
    which never goes through ``agent/bedrock_adapter.py``.

    ``install_truststore()`` calls this right after injecting; the Bedrock
    adapter calls it again after importing boto3. A botocore that is not loaded
    yet is left alone: it will capture the live class when it is imported.
    """
    httpsession = sys.modules.get("botocore.httpsession")
    if httpsession is not None and httpsession.SSLContext is not ssl.SSLContext:
        httpsession.SSLContext = ssl.SSLContext


def _coerce_insecure(ssl_verify: Any) -> bool:
    if ssl_verify is False:
        return True
    if isinstance(ssl_verify, str) and ssl_verify.strip().lower() in {"false", "0", "no", "off"}:
        return True
    return False


_CA_CONTEXTS: dict[str | None, ssl.SSLContext] = {}
_CA_CONTEXTS_LOCK = threading.Lock()


def _stdlib_ssl_context_class() -> type[ssl.SSLContext]:
    """The un-injected stdlib ``ssl.SSLContext``.

    An explicit bundle must REPLACE OS trust, and truststore's context falls
    back to the OS verifier whenever the loaded bundle rejects a chain — so
    the bundle context has to be built from the stdlib class. Once injected
    (here, or by pm.launch/pm.worker before this module loads) the only
    handle on it is truststore's own saved reference; when nothing is
    injected — truststore absent or not installed — ``ssl.SSLContext`` is
    already the stdlib class and truststore must not be imported at all.
    """
    if ssl.SSLContext.__module__ == "ssl":
        return ssl.SSLContext
    from truststore._ssl_constants import _original_SSLContext

    return _original_SSLContext


def _shared_context(ca_path: str | None) -> ssl.SSLContext:
    """A stable context identity lets clients reuse the existing transport pool."""
    with _CA_CONTEXTS_LOCK:
        ctx = _CA_CONTEXTS.get(ca_path)
        if ctx is None:
            if ca_path is not None:
                # PROTOCOL_TLS_CLIENT sets hostname checking and CERT_REQUIRED;
                # assigning the original class's properties after injection recurses.
                ctx = _stdlib_ssl_context_class()(ssl.PROTOCOL_TLS_CLIENT)
                ctx.load_verify_locations(cafile=ca_path)
            else:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                if not _installed:
                    ctx.load_default_certs()
            _CA_CONTEXTS[ca_path] = ctx
        return ctx


def resolve_httpx_verify(
    *,
    ca_bundle: Optional[str] = None,
    ssl_verify: Any = None,
    base_url: str = "",
) -> bool | ssl.SSLContext:
    """Resolve ``verify`` for an HTTP client.

    1. ``ssl_verify: false`` — verification off (local development only)
    2. explicit ``ca_bundle`` (the provider's ``ssl_ca_cert``) — that
       bundle INSTEAD of the platform store, for an endpoint whose chain
       the machine has no reason to trust
    3. ``True`` — the platform store, via the process-wide install

    ``base_url`` only labels the insecure-mode warning.
    """
    install_truststore()

    if _coerce_insecure(ssl_verify):
        logger.warning(
            "TLS certificate verification DISABLED (ssl_verify: false) for %s — "
            "this is intended for local development only and is unsafe on any "
            "network you do not fully control.",
            base_url or "a custom provider endpoint",
        )
        return False

    effective_ca = (ca_bundle or "").strip()
    if effective_ca:
        path = Path(effective_ca).expanduser()
        if path.is_file():
            return _shared_context(str(path.resolve()))
        logger.warning(
            "ssl_ca_cert path does not exist: %s — using the OS trust store instead",
            effective_ca,
        )
    # HTTPX reads CA env vars before the injected verifier gets control. Pass
    # the platform context directly so stale paths cannot break construction;
    # proxy environment handling remains enabled.
    import os

    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return _shared_context(None)
    return True
