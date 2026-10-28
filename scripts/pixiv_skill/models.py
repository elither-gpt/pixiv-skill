"""Normalize the different Pixiv payload shapes into one ``Work`` and render text.

Search results, user listings, ranking rows and detail responses all name the
same fields differently; everything downstream only deals with ``Work``.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

TYPE_LABELS = {"illust": "插画", "manga": "漫画", "ugoira": "动图", "novel": "小说"}
_ILLUST_TYPES = {0: "illust", 1: "manga", 2: "ugoira"}
_CN_TAGS = {"中文", "中国语", "中国語", "简体中文", "繁体中文", "繁體中文", "中文翻译", "中文翻譯", "chinese"}
_AI_TAGS = ("AI生成", "AIイラスト", "AI-generated", "AIart")


@dataclass
class Work:
    id: str
    type: str
    title: str = ""
    user_id: str = ""
    user_name: str = ""
    tags: list = field(default_factory=list)
    page_count: int = 1
    r18: int = 0          # 0 all ages, 1 R-18, 2 R-18G
    ai: bool = False
    bookmarks: int | None = None   # None = not provided by this endpoint
    views: int | None = None
    likes: int | None = None
    text_count: int | None = None
    series_id: str = ""
    series_title: str = ""
    created: str = ""
    description: str = ""
    width: int = 0
    height: int = 0
    rank: int | None = None
    language: str = ""

    @property
    def chinese(self) -> bool:
        if self.language.lower().startswith("zh"):
            return True
        return any(t.lower() in _CN_TAGS for t in self.tags)

    @property
    def url(self) -> str:
        if self.type == "novel":
            return f"https://www.pixiv.net/novel/show.php?id={self.id}"
        return f"https://www.pixiv.net/artworks/{self.id}"


def clean_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _tags(raw) -> list:
    """Accepts ['a', 'b'], {'tags': [{'tag': 'a'}]} or [{'tag': 'a'}]."""
    if isinstance(raw, dict):
        raw = raw.get("tags") or []
    out = []
    for t in raw or []:
        name = t.get("tag") if isinstance(t, dict) else t
        if name:
            out.append(str(name))
    return out


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def from_artwork(d: dict) -> Work:
    """Search/profile card or full /ajax/illust detail."""
    tags = _tags(d.get("tags"))
    ai_type = d.get("aiType") or d.get("illustAiType")
    return Work(
        id=str(d.get("id") or d.get("illustId") or ""),
        type=_ILLUST_TYPES.get(_int(d.get("illustType")) or 0, "illust"),
        title=d.get("title") or d.get("illustTitle") or "",
        user_id=str(d.get("userId") or ""),
        user_name=d.get("userName") or "",
        tags=tags,
        page_count=_int(d.get("pageCount")) or 1,
        r18=_int(d.get("xRestrict")) or 0,
        ai=ai_type == 2 or any(a in t for t in tags for a in _AI_TAGS),
        bookmarks=_int(d.get("bookmarkCount")),
        views=_int(d.get("viewCount")),
        likes=_int(d.get("likeCount")),
        series_id=str((d.get("seriesNavData") or {}).get("seriesId") or d.get("seriesId") or ""),
        series_title=(d.get("seriesNavData") or {}).get("title") or d.get("seriesTitle") or "",
        created=(d.get("createDate") or "")[:10],
        description=clean_html(d.get("description") or d.get("illustComment") or ""),
        width=_int(d.get("width")) or 0,
        height=_int(d.get("height")) or 0,
    )


def from_novel(d: dict) -> Work:
    tags = _tags(d.get("tags"))
    nav = d.get("seriesNavData") or {}
    return Work(
        id=str(d.get("id") or ""),
        type="novel",
        title=d.get("title") or "",
        user_id=str(d.get("userId") or ""),
        user_name=d.get("userName") or "",
        tags=tags,
        r18=_int(d.get("xRestrict")) or 0,
        ai=d.get("aiType") == 2 or any(a in t for t in tags for a in _AI_TAGS),
        bookmarks=_int(d.get("bookmarkCount")),
        views=_int(d.get("viewCount")),
        likes=_int(d.get("likeCount")),
        text_count=_int(d.get("characterCount") or d.get("textCount") or d.get("textLength")),
        series_id=str(nav.get("seriesId") or d.get("seriesId") or ""),
        series_title=nav.get("title") or d.get("seriesTitle") or "",
        created=(d.get("createDate") or "")[:10],
        description=clean_html(d.get("description") or ""),
        language=d.get("language") or "",
    )


def from_ranking(d: dict) -> Work:
    tags = _tags(d.get("tags"))
    content = d.get("illust_content_type") or {}
    series = d.get("illust_series") or {}
    return Work(
        id=str(d.get("illust_id") or ""),
        type=_ILLUST_TYPES.get(_int(d.get("illust_type")) or 0, "illust"),
        title=d.get("title") or "",
        user_id=str(d.get("user_id") or ""),
        user_name=d.get("user_name") or "",
        tags=tags,
        page_count=_int(d.get("illust_page_count")) or 1,
        r18=(1 if isinstance(content, dict) and content.get("sexual") else 0),
        ai=any(a in t for t in tags for a in _AI_TAGS),
        bookmarks=_int(d.get("rating_count")),
        views=_int(d.get("view_count")),
        series_id=str(series.get("illust_series_id") or series.get("id") or "") if isinstance(series, dict) else "",
        rank=_int(d.get("rank")),
        width=_int(d.get("width")) or 0,
        height=_int(d.get("height")) or 0,
    )


# ── text output ──────────────────────────────────────────────────────

def _flags(w: Work) -> str:
    parts = []
    if w.r18:
        parts.append("R-18G" if w.r18 == 2 else "R-18")
    if w.ai:
        parts.append("AI")
    if w.chinese:
        parts.append("中文")
    return "".join(f"[{p}]" for p in parts) + (" " if parts else "")


def line(w: Work, idx: int) -> str:
    """One plain-text line per work; safe for chat apps without Markdown."""
    bits = [f"{w.user_name or '?'}"]
    if w.type == "novel":
        if w.text_count is not None:
            bits.append(f"{w.text_count:,}字")
    elif w.page_count > 1:
        bits.append(f"{w.page_count}页")
    if w.bookmarks is not None:
        bits.append(f"收藏{w.bookmarks:,}")
    if w.tags:
        bits.append("、".join(w.tags[:4]))
    if w.series_id:
        bits.append(f"系列{w.series_id}")
    prefix = f"#{w.rank} " if w.rank else ""
    kind = "" if w.type in ("illust", "novel") else f"<{TYPE_LABELS[w.type]}>"
    return f"{idx}. {prefix}[{w.id}] {_flags(w)}{kind}{w.title} | " + " | ".join(bits)


def detail(w: Work, extra: list | None = None) -> str:
    rows = [
        f"{TYPE_LABELS.get(w.type, w.type)}：{w.title}",
        f"ID：{w.id}  {_flags(w).strip()}".rstrip(),
        f"作者：{w.user_name}（用户 ID {w.user_id}）",
    ]
    stats = []
    if w.type == "novel" and w.text_count is not None:
        stats.append(f"{w.text_count:,} 字")
    if w.type != "novel":
        stats.append(f"{w.page_count} 页")
        if w.width and w.height:
            stats.append(f"{w.width}×{w.height}")
    for label, value in (("收藏", w.bookmarks), ("浏览", w.views), ("点赞", w.likes)):
        if value is not None:
            stats.append(f"{label} {value:,}")
    rows.append("  ".join(stats))
    if w.created:
        rows.append(f"发布：{w.created}")
    if w.series_id:
        rows.append(f"系列：{w.series_title}（系列 ID {w.series_id}）")
    rows.append(f"标签：{'、'.join(w.tags) if w.tags else '无'}")
    rows.append(f"链接：{w.url}")
    if extra:
        rows.extend(extra)
    if w.description:
        rows.append("简介：" + w.description[:500])
    return "\n".join(rows)
