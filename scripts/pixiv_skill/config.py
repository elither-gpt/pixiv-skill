"""Where the cookie and downloads live.

The cookie is kept outside the skill folder so updating or re-cloning the
skill never deletes it, and it can never be committed by accident.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def config_dir() -> Path:
    custom = os.environ.get("PIXIV_SKILL_HOME", "").strip()
    if custom:
        return Path(custom).expanduser()
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "pixiv-skill"
    base = os.environ.get("XDG_CONFIG_HOME", "").strip() or "~/.config"
    return Path(base).expanduser() / "pixiv-skill"


def cookie_file() -> Path:
    return config_dir() / "cookie.json"


def parse_cookie_string(text: str) -> dict:
    """Accept ``PHPSESSID=xxx; other=yyy`` or just the bare PHPSESSID value."""
    text = text.strip().strip('"').strip("'")
    if text.lower().startswith("cookie:"):
        text = text[7:].strip()
    if "=" not in text:
        return {"PHPSESSID": text} if text else {}
    cookies = {}
    for pair in text.split(";"):
        name, sep, value = pair.strip().partition("=")
        if sep and name.strip():
            cookies[name.strip()] = value.strip()
    return cookies


def load_cookies() -> tuple[dict, str]:
    """Return (cookies, source). Environment variables win over the saved file."""
    for var in ("PIXIV_COOKIE", "PIXIV_PHPSESSID"):
        value = os.environ.get(var, "").strip()
        if value:
            cookies = parse_cookie_string(value)
            if cookies:
                return cookies, f"环境变量 {var}"
    path = cookie_file()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}, ""
        cookies = data.get("cookies") if isinstance(data, dict) else None
        if isinstance(cookies, dict) and cookies:
            return {str(k): str(v) for k, v in cookies.items()}, str(path)
    return {}, ""


def save_cookies(cookies: dict) -> Path:
    path = cookie_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"cookies": cookies}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return path


def clear_cookies() -> bool:
    path = cookie_file()
    if path.exists():
        path.unlink()
        return True
    return False


def download_dir(override: str | None = None) -> Path:
    value = override or os.environ.get("PIXIV_DOWNLOAD_DIR", "").strip()
    return Path(value).expanduser() if value else Path.cwd() / "pixiv-downloads"
