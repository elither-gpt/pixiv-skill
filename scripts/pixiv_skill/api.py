"""Thin client for the Pixiv web AJAX endpoints.

Every request goes through :meth:`PixivClient._get`, which handles rate
limiting, retries and turning HTTP/API failures into :class:`PixivError`.
Nothing here prints or exits; the CLI decides how to report errors.
"""

from __future__ import annotations

import time
from typing import Any, Iterable
from urllib.parse import quote

import requests

BASE = "https://www.pixiv.net"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
REFERER = "https://www.pixiv.net/"

# Friendly names -> Pixiv's own ``order`` values. popular* needs Premium;
# without it Pixiv silently falls back to newest-first.
ORDER_ALIASES = {
    "newest": "date_d", "latest": "date_d", "oldest": "date",
    "popular": "popular_d", "male": "popular_male_d", "female": "popular_female_d",
}
ORDERS = ["date_d", "date", "popular_d", "popular_male_d", "popular_female_d",
          *ORDER_ALIASES]

# kind -> (search endpoint, ``type`` param, key in the response body)
SEARCH_KINDS = {
    "illust": ("illustrations", "illust_and_ugoira", "illust"),
    "manga": ("manga", "manga", "manga"),
    "novel": ("novels", None, "novel"),
}

RANKING_MODES = {
    "daily": "日榜", "weekly": "周榜", "monthly": "月榜", "rookie": "新人榜",
    "original": "原创榜", "daily_ai": "AI 日榜", "male": "男性热门", "female": "女性热门",
    "daily_r18": "R-18 日榜", "weekly_r18": "R-18 周榜", "male_r18": "R-18 男性热门",
    "female_r18": "R-18 女性热门", "daily_r18_ai": "R-18 AI 日榜", "r18g": "R-18G",
}

PROFILE_BATCH = 48  # the web client asks for at most 48 works per call


class PixivError(Exception):
    """kind is one of: auth, not_found, network, server, rate_limit, api."""

    def __init__(self, message: str, kind: str = "api"):
        super().__init__(message)
        self.kind = kind


class PixivClient:
    def __init__(self, cookies: dict | None = None, delay: float = 0.7,
                 retries: int = 3, timeout: int = 30):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
            "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7",
        })
        if cookies:
            self.session.cookies.update(cookies)
        self.has_cookie = bool(cookies)
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self._last = 0.0

    # ── transport ────────────────────────────────────────────────────

    def _wait(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()

    def _request(self, url: str, params: Any = None, label: str = "") -> requests.Response:
        label = label or url
        for attempt in range(1, self.retries + 1):
            self._wait()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == self.retries:
                    raise PixivError(f"连不上 Pixiv（{label}）：{type(exc).__name__}", "network")
                time.sleep(1.5 ** attempt)
                continue
            status = resp.status_code
            if status == 429 or status >= 500:
                if attempt == self.retries:
                    kind = "rate_limit" if status == 429 else "server"
                    raise PixivError(f"Pixiv 返回 {status}（{label}），稍后再试", kind)
                retry_after = resp.headers.get("Retry-After", "")
                time.sleep(float(retry_after) if retry_after.isdigit() else 2 * attempt)
                continue
            return resp
        raise PixivError(f"请求失败：{label}", "network")  # pragma: no cover

    def _get(self, path: str, params: Any = None, label: str = "") -> Any:
        resp = self._request(BASE + path, params, label)
        try:
            data = resp.json()
        except ValueError:
            raise PixivError(f"Pixiv 返回的不是 JSON（{label}，HTTP {resp.status_code}）")
        if resp.status_code in (401, 403):
            raise PixivError(f"没有权限（{label}）：Cookie 无效、过期，或账号没开 R-18 显示", "auth")
        if resp.status_code == 404:
            raise PixivError(f"找不到（{label}）：作品不存在、已删除或仅登录可见", "not_found")
        if isinstance(data, dict) and data.get("error"):
            message = data.get("message") or f"HTTP {resp.status_code}"
            raise PixivError(f"Pixiv 报错（{label}）：{message}")
        if resp.status_code >= 400:
            raise PixivError(f"HTTP {resp.status_code}（{label}）")
        return data.get("body", data) if isinstance(data, dict) else data

    def download(self, url: str, label: str = "") -> bytes:
        """Fetch an image from i.pximg.net (needs the pixiv Referer)."""
        resp = self._request(url, label=label or url)
        if resp.status_code == 403:
            raise PixivError(f"图片服务器拒绝访问（{label}）", "auth")
        if resp.status_code >= 400:
            raise PixivError(f"图片下载失败 HTTP {resp.status_code}（{label}）")
        return resp.content

    # ── account ──────────────────────────────────────────────────────

    def logged_in(self) -> bool:
        """True when the cookie belongs to a logged-in account."""
        if not self.has_cookie:
            return False
        try:
            self._get("/ajax/user/extra", label="登录状态")
            return True
        except PixivError as exc:
            if exc.kind in ("network", "server", "rate_limit"):
                raise
            return False

    # ── search & ranking ─────────────────────────────────────────────

    def search(self, kind: str, keyword: str, page: int = 1, order: str = "date_d",
               mode: str = "all", exact: bool = False) -> dict:
        endpoint, type_param, key = SEARCH_KINDS[kind]
        params = {
            "word": keyword, "order": ORDER_ALIASES.get(order, order), "mode": mode,
            "p": page, "s_mode": "s_tag_full" if exact else "s_tag", "lang": "zh",
        }
        if type_param:
            params["type"] = type_param
        body = self._get(f"/ajax/search/{endpoint}/{quote(keyword, safe='')}",
                         params, f"搜索 {keyword}")
        block = body.get(key) or {}
        return {"total": int(block.get("total") or 0),
                "last_page": int(block.get("lastPage") or 1),
                "items": [i for i in block.get("data") or [] if isinstance(i, dict) and i.get("id")]}

    def ranking(self, mode: str = "daily", content: str | None = None,
                page: int = 1, date: str | None = None) -> dict:
        params: dict = {"mode": mode, "p": page, "format": "json"}
        if content:
            params["content"] = content
        if date:
            params["date"] = date
        resp = self._request(f"{BASE}/ranking.php", params, f"排行榜 {mode}")
        try:
            data = resp.json()
        except ValueError:
            raise PixivError(f"排行榜 {mode} 返回格式异常（HTTP {resp.status_code}）")
        if data.get("error") or resp.status_code >= 400:
            hint = "（R-18 榜需要登录并开启 R-18 显示）" if "r18" in mode else ""
            raise PixivError(f"排行榜 {mode} 不可用：{data.get('error') or resp.status_code}{hint}",
                             "auth" if "r18" in mode else "api")
        return {"date": data.get("date", ""), "next": data.get("next") or None,
                "total": int(data.get("rank_total") or 0),
                "items": data.get("contents") or []}

    # ── artworks (illust / manga / ugoira share one API) ─────────────

    def artwork(self, illust_id: str) -> dict:
        return self._get(f"/ajax/illust/{illust_id}", {"lang": "zh"}, f"作品 {illust_id}")

    def artwork_pages(self, illust_id: str) -> list:
        return self._get(f"/ajax/illust/{illust_id}/pages", {"lang": "zh"}, f"作品 {illust_id} 分页")

    def ugoira_meta(self, illust_id: str) -> dict:
        return self._get(f"/ajax/illust/{illust_id}/ugoira_meta", None, f"动图 {illust_id}")

    # ── novels ───────────────────────────────────────────────────────

    def novel(self, novel_id: str) -> dict:
        return self._get(f"/ajax/novel/{novel_id}", {"lang": "zh"}, f"小说 {novel_id}")

    def novel_series(self, series_id: str) -> dict:
        return self._get(f"/ajax/novel/series/{series_id}", {"lang": "zh"}, f"系列 {series_id}")

    def novel_series_titles(self, series_id: str) -> list:
        """Every chapter of a series in reading order: [{id, title, available}]."""
        return self._get(f"/ajax/novel/series/{series_id}/content_titles", None,
                         f"系列 {series_id} 目录")

    # ── users ────────────────────────────────────────────────────────

    def user(self, user_id: str) -> dict:
        return self._get(f"/ajax/user/{user_id}", {"full": 0, "lang": "zh"}, f"用户 {user_id}")

    def user_work_ids(self, user_id: str) -> dict:
        """{"illust": [...], "manga": [...], "novel": [...]}, newest first."""
        body = self._get(f"/ajax/user/{user_id}/profile/all", {"lang": "zh"}, f"用户 {user_id}")

        def ids(block: Any) -> list:
            return sorted(block, key=int, reverse=True) if isinstance(block, dict) else []

        return {"illust": ids(body.get("illusts")), "manga": ids(body.get("manga")),
                "novel": ids(body.get("novels"))}

    def user_works(self, user_id: str, kind: str, ids: Iterable[str]) -> list:
        """Card data for the given work ids, kept in the order of ``ids``."""
        ids = list(ids)
        path, extra = ((f"/ajax/user/{user_id}/profile/novels", [])
                       if kind == "novel" else
                       (f"/ajax/user/{user_id}/profile/illusts",
                        [("work_category", "illustManga"), ("is_first_page", "0")]))
        found: dict = {}
        for start in range(0, len(ids), PROFILE_BATCH):
            chunk = ids[start:start + PROFILE_BATCH]
            params = [*(("ids[]", i) for i in chunk), *extra, ("lang", "zh")]
            works = self._get(path, params, f"用户 {user_id} 作品").get("works") or {}
            found.update(works)
        return [found[i] for i in ids if i in found]
