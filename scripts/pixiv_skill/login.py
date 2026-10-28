"""Log in through a real browser window and capture the PHPSESSID cookie.

The user signs in by themselves in a throwaway browser profile. This module only
reads the resulting cookie over the Chrome DevTools Protocol, then closes the
window and deletes the profile. Passwords never pass through here, and the
user's everyday browser profile is never read or touched.

Works with Chrome, Edge, Brave and Chromium. Standard library only.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import ProxyHandler, build_opener

from .api import PixivError

LOGIN_URL = "https://accounts.pixiv.net/login?return_to=https%3A%2F%2Fwww.pixiv.net%2F&lang=zh"
# Logged-in sessions look like "<user id>_<random>"; anonymous ones don't.
_SESSION = re.compile(r"^\d+_\w+$")


class LoginError(PixivError):
    def __init__(self, message: str):
        super().__init__(message, "auth")


# ── finding and starting a browser ───────────────────────────────────

def browser_candidates() -> list[str]:
    if sys.platform == "win32":
        roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        rel = [r"Google\Chrome\Application\chrome.exe",
               r"Microsoft\Edge\Application\msedge.exe",
               r"BraveSoftware\Brave-Browser\Application\brave.exe",
               r"Chromium\Application\chrome.exe"]
        return [str(Path(root) / path) for path in rel for root in roots if root]
    if sys.platform == "darwin":
        apps = ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium")
        return [f"/Applications/{a}.app/Contents/MacOS/{a}" for a in apps]
    names = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
             "microsoft-edge", "microsoft-edge-stable", "brave-browser")
    return [p for n in names if (p := shutil.which(n))]


def find_browser(explicit: str | None = None) -> str:
    for choice in (explicit, os.environ.get("PIXIV_BROWSER")):
        if choice:
            found = shutil.which(choice) or (choice if Path(choice).is_file() else None)
            if not found:
                raise LoginError(f"找不到指定的浏览器：{choice}")
            return found
    for path in browser_candidates():
        if Path(path).is_file():
            return path
    raise LoginError("没找到 Chrome、Edge、Brave 或 Chromium。"
                     "用 --browser 指定浏览器程序的路径，或者按说明手动复制 Cookie")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def launch(exe: str, port: int, profile: str, extra_args=()) -> subprocess.Popen:
    args = [exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check", "--disable-sync",
            *extra_args, LOGIN_URL]
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def devtools_url(port: int, proc: subprocess.Popen, timeout: float = 20) -> str:
    opener = build_opener(ProxyHandler({}))  # never send localhost through a system proxy
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise LoginError("浏览器一启动就退出了。可能是同一个浏览器正在用别的方式运行，换一个浏览器试试（--browser）")
        try:
            with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=2) as resp:
                return json.load(resp)["webSocketDebuggerUrl"]
        except (OSError, ValueError, KeyError):
            time.sleep(0.3)
    raise LoginError("连不上浏览器的调试端口")


# ── a minimal WebSocket client, just enough for DevTools ─────────────

class CDP:
    def __init__(self, ws_url: str, timeout: float = 15):
        url = urlparse(ws_url)
        self.sock = socket.create_connection((url.hostname, url.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {url.path} HTTP/1.1\r\nHost: {url.hostname}:{url.port}\r\n"
                           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise LoginError("浏览器拒绝了调试连接")
            head += chunk
        status, _, self.buf = head.partition(b"\r\n\r\n")
        if b" 101 " not in status.split(b"\r\n", 1)[0]:
            raise LoginError("浏览器拒绝了调试连接")
        self.next_id = 0

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("浏览器断开了连接")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _message(self) -> str:
        parts = []
        while True:
            b1, b2 = self._read(2)
            opcode, length = b1 & 0x0F, b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            data = self._read(length)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 8:
                raise ConnectionError("浏览器关闭了连接")
            if opcode == 9:
                self._send(10, data)
                continue
            if opcode in (0, 1, 2):
                parts.append(data)
                if b1 & 0x80:
                    return b"".join(parts).decode("utf-8")

    def call(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        self._send(1, json.dumps({"id": self.next_id, "method": method,
                                  "params": params or {}}).encode())
        while True:
            msg = json.loads(self._message())
            if msg.get("id") == self.next_id:
                if "error" in msg:
                    raise LoginError(f"浏览器调试命令失败：{msg['error'].get('message')}")
                return msg.get("result", {})


# ── the login flow ───────────────────────────────────────────────────

def find_session(cookies: list) -> str | None:
    for c in cookies:
        if (c.get("name") == "PHPSESSID" and str(c.get("domain", "")).endswith("pixiv.net")
                and _SESSION.match(str(c.get("value", "")))):
            return c["value"]
    return None


def wait_for_login(cdp: CDP, proc: subprocess.Popen, timeout: float, poll: float = 1.5) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = find_session(cdp.call("Storage.getCookies").get("cookies", []))
        except (OSError, ConnectionError):
            raise LoginError("浏览器窗口被关掉了，还没检测到登录")
        if value:
            return value
        if proc.poll() is not None:
            raise LoginError("浏览器窗口被关掉了，还没检测到登录")
        time.sleep(poll)
    raise LoginError(f"等了 {int(timeout)} 秒还没登录成功，已放弃。重新运行再试一次即可")


def shutdown(cdp: CDP | None, proc: subprocess.Popen, profile: str) -> None:
    if cdp:
        try:
            cdp.call("Browser.close")
        except Exception:
            pass
        cdp.close()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(5)
    for _ in range(20):  # the browser may hold files for a moment after exiting
        shutil.rmtree(profile, ignore_errors=True)
        if not Path(profile).exists():
            return
        time.sleep(0.5)


def browser_login(browser: str | None = None, timeout: float = 300, extra_args=(),
                  progress: Callable[[str], None] = print) -> str:
    """Open a fresh browser window, wait until the user logs in, return PHPSESSID."""
    exe = find_browser(browser)
    profile = tempfile.mkdtemp(prefix="pixiv-login-")
    port = free_port()
    proc = launch(exe, port, profile, extra_args)
    cdp = None
    try:
        cdp = CDP(devtools_url(port, proc))
        progress(f"已打开一个新的浏览器窗口（{Path(exe).stem}）。请在里面登录 Pixiv，"
                 f"登录成功后窗口会自动关闭（最多等 {int(timeout)} 秒）…")
        return wait_for_login(cdp, proc, timeout)
    finally:
        shutdown(cdp, proc, profile)
