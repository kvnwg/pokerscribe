"""API keys live in the macOS Keychain (via `keyring`) or in environment variables,
never in the source code or the settings file."""
from __future__ import annotations

import os
from typing import Optional, Tuple

from app import APP_NAME

ENV_VARS = {"claude": "ANTHROPIC_API_KEY", "openai_compat": "OPENAI_API_KEY",
            "github_reads": "POKERSCRIBE_GITHUB_TOKEN"}  # sending saved reads (send.py)


def get_api_key(provider: str) -> Tuple[Optional[str], str]:
    """(key, where it came from). Environment variables win over the keychain."""
    env = ENV_VARS.get(provider)
    if env and os.environ.get(env):
        return os.environ[env], f"environment variable {env}"
    try:
        import keyring

        key = keyring.get_password(APP_NAME, provider)
        if key:
            return key, "system keychain"
    except Exception:
        pass
    return None, ""


def set_api_key(provider: str, key: str) -> None:
    import keyring

    keyring.set_password(APP_NAME, provider, key.strip())


def delete_api_key(provider: str) -> None:
    try:
        import keyring

        keyring.delete_password(APP_NAME, provider)
    except Exception:
        pass


def keychain_available() -> bool:
    try:
        import keyring
        from keyring.backends import fail

        return not isinstance(keyring.get_keyring(), fail.Keyring)
    except Exception:
        return False
