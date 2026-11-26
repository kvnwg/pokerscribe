"""Minimal JSON-over-HTTPS client built on the standard library.

Used instead of vendor SDKs so we control every byte that is sent: SDKs add
headers describing the operating system, CPU architecture and Python version,
which the privacy requirements rule out. Only content-type, accept, a generic
user-agent and the provider's auth headers are sent.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict

from .base import AIError

USER_AGENT = "text-client/1.0"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def post_json(url: str, payload: dict, headers: Dict[str, str], timeout: float = 60.0) -> dict:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise AIError("The API address must start with https:// (or http:// for a local server).")
    if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS:
        raise AIError("Plain http is only allowed for a server on this computer (localhost).")
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", USER_AGENT)
    for k, v in headers.items():
        req.add_header(k, v)
    handlers = [urllib.request.HTTPSHandler(context=_ssl_context())]
    if parsed.hostname in LOCAL_HOSTS:
        handlers.append(urllib.request.ProxyHandler({}))  # never route local traffic through a proxy
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise AIError(_http_error_message(exc)) from None
    except urllib.error.URLError as exc:
        raise AIError(f"Could not reach the AI provider: {exc.reason}") from None
    except TimeoutError:
        raise AIError("The AI provider did not answer in time.") from None
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        raise AIError("The AI provider returned something that is not JSON.") from None


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    detail = ""
    try:
        data = json.loads(exc.read().decode("utf-8"))
        err = data.get("error", data)
        detail = err.get("message", "") if isinstance(err, dict) else str(err)
    except Exception:
        pass
    hint = {401: "check the API key", 403: "the key is not allowed to use this model",
            404: "check the model name and API address", 429: "rate limit or quota reached, try again shortly"}.get(exc.code)
    parts = [f"HTTP {exc.code}"]
    if detail:
        parts.append(detail)
    if hint:
        parts.append(f"({hint})")
    return "AI request failed: " + " ".join(parts)
