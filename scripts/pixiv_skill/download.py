"""Download artworks and novels to disk.

Every function returns the list of files it wrote. Files are written to a
temporary name first and renamed at the end, so an interrupted run never
leaves a half-written file that looks finished.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path
from typing import Callable

from .api import PixivClient, PixivError
from .models import Work, clean_html, from_artwork, from_novel

PDF_MAX_PAGES = 50
Progress = Callable[[str], None]


def safe_name(text: str, limit: int = 60) -> str:
    text = re.sub(r'[\\/:*?"<>|#\x00-\x1f]', "_", text or "")
    text = re.sub(r"\s+", " ", text).strip(" ._")
    return text[:limit] or "untitled"


def _write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    if isinstance(data, str):
        tmp.write_text(data, encoding="utf-8")
    else:
        tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


def _ext(url: str) -> str:
    ext = url.rsplit(".", 1)[-1].split("?")[0].lower()
    return ext if ext in ("jpg", "jpeg", "png", "gif", "webp") else "jpg"


# ── artworks ─────────────────────────────────────────────────────────

def download_artwork(client: PixivClient, illust_id: str, out_dir: Path,
                     quality: str = "original", as_images: bool = False,
                     progress: Progress = print) -> tuple[Work, list[Path]]:
    """Single page -> image file. Multi page -> PDF (split every 50 pages),
    or a folder of images with ``as_images``. Ugoira -> ZIP of frames, or a
    GIF when Pillow is installed."""
    raw = client.artwork(illust_id)
    work = from_artwork(raw)
    base = f"pixiv_{work.id}_{safe_name(work.title)}"

    if work.type == "ugoira":
        return work, [_download_ugoira(client, work, out_dir, base, progress)]

    pages = client.artwork_pages(illust_id)
    if not pages:
        raise PixivError(f"作品 {illust_id} 没有可下载的图片")
    urls = [p["urls"].get(quality) or p["urls"]["original"] for p in pages]

    if len(urls) == 1:
        data = client.download(urls[0], f"作品 {illust_id}")
        return work, [_write(out_dir / f"{base}.{_ext(urls[0])}", data)]

    progress(f"共 {len(urls)} 页，开始下载…")
    images = []
    for i, url in enumerate(urls, 1):
        images.append((url, client.download(url, f"第 {i} 页")))
        progress(f"  [{i}/{len(urls)}] 完成")

    if as_images:
        folder = out_dir / base
        return work, [_write(folder / f"p{i:03d}.{_ext(url)}", data)
                      for i, (url, data) in enumerate(images, 1)]
    return work, images_to_pdf([d for _, d in images], out_dir, base)


def images_to_pdf(images: list[bytes], out_dir: Path, base: str) -> list[Path]:
    import img2pdf

    files = []
    chunks = [images[i:i + PDF_MAX_PAGES] for i in range(0, len(images), PDF_MAX_PAGES)]
    for n, chunk in enumerate(chunks, 1):
        suffix = f"_part{n}" if len(chunks) > 1 else ""
        try:
            pdf = img2pdf.convert(chunk)
        except Exception as exc:  # img2pdf raises many types for odd images
            raise PixivError(f"合成 PDF 失败（第 {n} 卷）：{exc}")
        files.append(_write(out_dir / f"{base}{suffix}.pdf", pdf))
    return files


def _download_ugoira(client: PixivClient, work: Work, out_dir: Path, base: str,
                     progress: Progress) -> Path:
    meta = client.ugoira_meta(work.id)
    progress(f"动图：{len(meta['frames'])} 帧，下载中…")
    archive = client.download(meta.get("originalSrc") or meta["src"], f"动图 {work.id}")
    try:
        from PIL import Image
    except ImportError:
        return _write(out_dir / f"{base}_frames.zip", archive)

    frames, delays = [], []
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for frame in meta["frames"]:
            img = Image.open(io.BytesIO(zf.read(frame["file"])))
            frames.append(img.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE))
            delays.append(int(frame.get("delay") or 100))
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                   duration=delays, loop=0, disposal=2)
    return _write(out_dir / f"{base}.gif", buf.getvalue())


# ── novels ───────────────────────────────────────────────────────────

def convert_markup(text: str) -> str:
    """Pixiv novel markup -> readable plain text."""
    text = re.sub(r"\[chapter:\s*(.+?)\]", r"\n\n========== \1 ==========\n", text)
    text = text.replace("[newpage]", "\n\n---\n\n")
    text = re.sub(r"\[\[rb:\s*(.+?)\s*>\s*(.+?)\]\]", r"\1（\2）", text)
    text = re.sub(r"\[\[jumpuri:\s*(.+?)\s*>\s*(.+?)\]\]", r"\1（\2）", text)
    text = re.sub(r"\[jump:\s*(\d+)\]", r"（跳到第 \1 页）", text)
    text = re.sub(r"\[pixivimage:\s*(\d+)(?:-(\d+))?\]",
                  lambda m: f"\n[插图：https://www.pixiv.net/artworks/{m.group(1)}]\n", text)
    text = re.sub(r"\[uploadedimage:\s*(\d+)\]", r"\n[插图 \1]\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _novel_header(w: Work) -> str:
    rows = [w.title, f"作者：{w.user_name}", f"链接：{w.url}"]
    if w.series_id:
        rows.append(f"系列：{w.series_title}（{w.series_id}）")
    if w.tags:
        rows.append("标签：" + "、".join(w.tags))
    if w.description:
        rows.append("简介：" + w.description[:300])
    bar = "=" * 40
    return f"{bar}\n" + "\n".join(rows) + f"\n{bar}\n\n"


def fetch_novel(client: PixivClient, novel_id: str) -> tuple[Work, str]:
    raw = client.novel(novel_id)
    body = raw.get("content") or ""
    if not body:
        raise PixivError(f"小说 {novel_id} 正文为空：可能需要登录或开启 R-18 显示", "auth")
    return from_novel(raw), convert_markup(body)


def download_novel(client: PixivClient, novel_id: str, out_dir: Path) -> tuple[Work, list[Path]]:
    work, body = fetch_novel(client, novel_id)
    path = out_dir / f"pixiv_novel_{work.id}_{safe_name(work.title, 80)}.txt"
    return work, [_write(path, _novel_header(work) + body + "\n")]


def download_series(client: PixivClient, series_id: str, out_dir: Path,
                    merge: bool = True, progress: Progress = print) -> tuple[dict, list[Path], list[str]]:
    """Returns (series meta, files written, failures)."""
    meta = client.novel_series(series_id)
    chapters = [c for c in client.novel_series_titles(series_id) if c.get("available", True)]
    if not chapters:
        raise PixivError(f"系列 {series_id} 没有可读的章节")
    title = meta.get("title") or f"series_{series_id}"
    progress(f"系列《{title}》共 {len(chapters)} 篇，开始下载…")

    texts, files, failures = [], [], []
    for i, ch in enumerate(chapters, 1):
        try:
            work, body = fetch_novel(client, str(ch["id"]))
        except PixivError as exc:
            failures.append(f"{ch['id']} {ch.get('title', '')}：{exc}")
            progress(f"  [{i}/{len(chapters)}] 失败：{exc}")
            continue
        progress(f"  [{i}/{len(chapters)}] {work.title}")
        if merge:
            texts.append(f"\n\n{'#' * 40}\n第 {i} 话  {work.title}\n{'#' * 40}\n\n{body}\n")
        else:
            name = f"pixiv_series_{series_id}_{i:03d}_{safe_name(work.title, 60)}.txt"
            files.append(_write(out_dir / safe_name(title) / name, _novel_header(work) + body + "\n"))

    if merge and texts:
        head = (f"{'=' * 40}\n{title}\n作者：{meta.get('userName', '')}\n"
                f"链接：https://www.pixiv.net/novel/series/{series_id}\n"
                f"共 {len(texts)} 话\n")
        caption = clean_html(meta.get("caption") or "")
        if caption:
            head += f"简介：{caption[:300]}\n"
        head += "=" * 40 + "\n"
        path = out_dir / f"pixiv_series_{series_id}_{safe_name(title, 80)}.txt"
        files.append(_write(path, head + "".join(texts)))
    return meta, files, failures
