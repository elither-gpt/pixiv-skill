"""Command line interface. Run through ``scripts/pixiv.py``.

stdout carries results (plain text or ``--json``); progress and errors go to
stderr so agents can parse stdout safely. Exit codes: 0 ok, 1 error,
2 bad usage, 3 auth, 4 not found, 5 network / server.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__, config
from .api import ORDERS, RANKING_MODES, PixivClient, PixivError
from .download import download_artwork, download_novel, download_series
from .models import Work, detail, from_artwork, from_novel, from_ranking, line
from .targets import parse_target

EXIT_CODES = {"auth": 3, "not_found": 4, "network": 5, "server": 5, "rate_limit": 5}


class UsageError(Exception):
    pass


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def make_client(args) -> PixivClient:
    cookies, _ = config.load_cookies()
    return PixivClient(cookies, delay=args.delay)


def emit(args, data: dict, text: str) -> None:
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print(text)


def _works_json(works: list[Work]) -> list[dict]:
    return [{**asdict(w), "url": w.url, "chinese": w.chinese} for w in works]


def _fill_bookmarks(client: PixivClient, works: list[Work]) -> None:
    """Search cards for artworks omit bookmark counts; fetch them one by one."""
    missing = [w for w in works if w.bookmarks is None]
    if missing:
        log(f"正在读取 {len(missing)} 个作品的收藏数（每个约 1 秒）…")
    for w in missing:
        try:
            w.bookmarks = from_artwork(client.artwork(w.id)).bookmarks or 0
        except PixivError as exc:
            if exc.kind != "not_found":
                raise
            w.bookmarks = 0


# ── commands ─────────────────────────────────────────────────────────

def cmd_search(args) -> int:
    client = make_client(args)
    mode = {"all": "all", "safe": "safe", "only": "r18"}[args.r18]
    result = client.search(args.type, args.keyword, args.page, args.order, mode, args.exact)
    convert = from_novel if args.type == "novel" else from_artwork
    works = [convert(i) for i in result["items"]]
    if args.min_bookmarks:
        _fill_bookmarks(client, works)
        works = [w for w in works if (w.bookmarks or 0) >= args.min_bookmarks]
    shown = works[:args.count]

    label = {"illust": "插画", "manga": "漫画", "novel": "小说"}[args.type]
    head = f"搜索{label}「{args.keyword}」：共 {result['total']:,} 个结果，第 {args.page}/{result['last_page']} 页"
    if args.min_bookmarks:
        head += f"，本页收藏≥{args.min_bookmarks:,} 的有 {len(works)} 个"
    lines = [head] + [line(w, i) for i, w in enumerate(shown, 1)]
    if not shown:
        lines.append("（没有结果）")
    elif args.page < result["last_page"]:
        lines.append(f"下一页：加 --page {args.page + 1}")
    emit(args, {"total": result["total"], "page": args.page, "last_page": result["last_page"],
                "items": _works_json(shown)}, "\n".join(lines))
    return 0


def cmd_rank(args) -> int:
    client = make_client(args)
    content = None if args.type == "all" else args.type
    result = client.ranking(args.mode, content, args.page, args.date)
    works = [from_ranking(i) for i in result["items"]][:args.count]
    head = (f"{RANKING_MODES.get(args.mode, args.mode)}"
            f"{'（' + {'illust': '插画', 'manga': '漫画', 'ugoira': '动图'}[content] + '）' if content else ''}"
            f" {result['date']}：第 {args.page} 页")
    lines = [head] + [line(w, i) for i, w in enumerate(works, 1)]
    if result["next"]:
        lines.append(f"下一页：加 --page {result['next']}")
    emit(args, {"date": result["date"], "page": args.page, "next": result["next"],
                "items": _works_json(works)}, "\n".join(lines))
    return 0


def _target(args, text: str):
    target = parse_target(text, default=args.kind)
    if not target:
        raise UsageError(f"看不懂这个目标：{text}（支持作品链接、作品号、n:小说号、s:系列号、u:用户号）")
    return target


def cmd_info(args) -> int:
    client = make_client(args)
    target = _target(args, args.target)
    if target.kind == "artwork":
        work = from_artwork(client.artwork(target.id))
        emit(args, _works_json([work])[0], detail(work))
    elif target.kind == "novel":
        work = from_novel(client.novel(target.id))
        emit(args, _works_json([work])[0], detail(work))
    elif target.kind == "series":
        meta = client.novel_series(target.id)
        chapters = client.novel_series_titles(target.id)
        rows = [f"小说系列：{meta.get('title', '')}（{target.id}）",
                f"作者：{meta.get('userName', '')}（用户 ID {meta.get('userId', '')}）",
                f"共 {len(chapters)} 篇{'，已完结' if meta.get('isConcluded') else ''}",
                f"链接：https://www.pixiv.net/novel/series/{target.id}"]
        rows += [f"{i}. [{c['id']}] {c.get('title', '')}" + ("" if c.get("available", True) else "（不可见）")
                 for i, c in enumerate(chapters, 1)]
        emit(args, {"series": meta, "chapters": chapters}, "\n".join(rows))
    else:
        return cmd_user(args, target.id)
    return 0


def cmd_user(args, user_id: str | None = None) -> int:
    client = make_client(args)
    user_id = user_id or _target(args, args.target).id
    profile = client.user(user_id)
    ids = client.user_work_ids(user_id)
    kind = getattr(args, "type", "illust")
    start = (args.page - 1) * args.count
    page_ids = ids[kind][start:start + args.count]
    convert = from_novel if kind == "novel" else from_artwork
    works = [convert(w) for w in client.user_works(user_id, kind, page_ids)]
    label = {"illust": "插画", "manga": "漫画", "novel": "小说"}[kind]
    rows = [f"用户：{profile.get('name', '')}（{user_id}）  https://www.pixiv.net/users/{user_id}",
            f"插画 {len(ids['illust'])} 个，漫画 {len(ids['manga'])} 个，小说 {len(ids['novel'])} 篇",
            f"最新{label}，第 {args.page} 页："]
    rows += [line(w, start + i) for i, w in enumerate(works, 1)] or ["（没有）"]
    if start + args.count < len(ids[kind]):
        rows.append(f"下一页：加 --page {args.page + 1}")
    emit(args, {"user": {"id": user_id, "name": profile.get("name")},
                "counts": {k: len(v) for k, v in ids.items()},
                "items": _works_json(works)}, "\n".join(rows))
    return 0


def cmd_download(args) -> int:
    client = make_client(args)
    out_dir = config.download_dir(args.out)
    results, failed = [], 0
    for text in args.targets:
        target = _target(args, text)
        try:
            if target.kind == "artwork":
                work, files = download_artwork(client, target.id, out_dir, args.quality,
                                               args.images, progress=log)
                entry = {"target": text, "title": work.title, "files": files}
            elif target.kind == "novel":
                work, files = download_novel(client, target.id, out_dir)
                entry = {"target": text, "title": work.title, "files": files}
            elif target.kind == "series":
                meta, files, failures = download_series(client, target.id, out_dir,
                                                        merge=not args.no_merge, progress=log)
                entry = {"target": text, "title": meta.get("title", ""), "files": files,
                         "failures": failures}
                failed += bool(failures)
            else:
                raise UsageError("用户主页不能直接下载；先用 user 命令列出作品，再挑作品下载")
        except PixivError as exc:
            if len(args.targets) == 1:
                raise
            log(f"失败 {text}：{exc}")
            results.append({"target": text, "error": str(exc), "files": []})
            failed += 1
            continue
        results.append(entry)

    if args.json:
        print(json.dumps({"results": results}, ensure_ascii=False, indent=2, default=str))
    else:
        for r in results:
            if r.get("error"):
                print(f"FAILED: {r['target']} {r['error']}")
            for f in r["files"]:
                print(f"SAVED: {Path(f).resolve()}")
            for msg in r.get("failures", []):
                print(f"FAILED: {msg}")
    return 1 if failed else 0


def cmd_cookie(args) -> int:
    if args.clear:
        log("已删除保存的 Cookie" if config.clear_cookies() else "本来就没有保存的 Cookie")
        return 0
    if args.login:
        from .login import browser_login
        value = browser_login(args.browser, args.timeout, progress=log)
        path = config.save_cookies({"PHPSESSID": value})
        log(f"登录成功，Cookie 已保存到 {path}")
    elif args.set is not None:
        value = args.set
        if value == "-":
            value = sys.stdin.readline() if not sys.stdin.isatty() else getpass.getpass("粘贴 Cookie：")
        cookies = config.parse_cookie_string(value)
        if not cookies:
            raise UsageError("Cookie 是空的。格式：PHPSESSID=xxxx，或只填 PHPSESSID 的值")
        path = config.save_cookies(cookies)
        log(f"已保存到 {path}")
    cookies, source = config.load_cookies()
    if not cookies:
        print("未设置 Cookie：只能看全年龄作品，搜索和下载 R-18、仅好友可见作品需要登录。")
        print("设置方法：pixiv.py cookie --login（自动打开浏览器登录），或 pixiv.py cookie --set -（手动粘贴 PHPSESSID）")
        return 3
    ok = PixivClient(cookies, delay=args.delay).logged_in()
    print(f"Cookie 有效（来源：{source}）" if ok else f"Cookie 无效或已过期（来源：{source}），请重新设置")
    return 0 if ok else 3


# ── argument parsing ─────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="输出 JSON，方便程序读取")
    common.add_argument("--delay", type=float, default=0.7, help="两次请求的最小间隔秒数（默认 0.7）")

    p = argparse.ArgumentParser(prog="pixiv.py", description="Pixiv 插画、漫画、小说的搜索、查看和下载。")
    p.add_argument("--version", action="version", version=f"pixiv-skill {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", parents=[common], help="按关键词搜索")
    s.add_argument("keyword")
    s.add_argument("-t", "--type", choices=["illust", "manga", "novel"], default="illust")
    s.add_argument("-p", "--page", type=int, default=1)
    s.add_argument("-o", "--order", choices=ORDERS, default="date_d",
                   help="newest 最新（默认）、oldest 最旧、popular/male/female 热门（需要 Premium）")
    s.add_argument("-n", "--count", type=int, default=20, help="最多显示几条（默认 20）")
    s.add_argument("-b", "--min-bookmarks", type=int, default=0,
                   help="只留收藏数不低于此值的；插画和漫画要逐个查，比较慢")
    s.add_argument("--r18", choices=["all", "safe", "only"], default="all",
                   help="all 不限（默认，取决于账号设置）、safe 只要全年龄、only 只要 R-18")
    s.add_argument("--exact", action="store_true", help="标签完全一致才算（默认部分一致）")
    s.set_defaults(func=cmd_search)

    r = sub.add_parser("rank", parents=[common], help="排行榜")
    r.add_argument("mode", nargs="?", default="daily", choices=list(RANKING_MODES))
    r.add_argument("-t", "--type", choices=["all", "illust", "manga", "ugoira"], default="all")
    r.add_argument("-p", "--page", type=int, default=1, help="每页 50 名")
    r.add_argument("-d", "--date", help="哪天的榜，格式 20260101（默认最新）")
    r.add_argument("-n", "--count", type=int, default=50)
    r.set_defaults(func=cmd_rank)

    target_help = "作品链接或 ID；n:小说号、s:系列号、u:用户号；小说和系列链接会自动识别"
    i = sub.add_parser("info", parents=[common], help="看作品、小说、系列或用户详情")
    i.add_argument("target", help=target_help)
    i.add_argument("-k", "--kind", choices=["artwork", "novel", "series", "user"], default="artwork",
                   help="纯数字当作哪种 ID（默认 artwork 插画/漫画）")
    i.add_argument("-t", "--type", choices=["illust", "manga", "novel"], default="illust",
                   help="目标是用户时，列哪类作品")
    i.add_argument("-p", "--page", type=int, default=1)
    i.add_argument("-n", "--count", type=int, default=20)
    i.set_defaults(func=cmd_info)

    u = sub.add_parser("user", parents=[common], help="列出某个用户的作品")
    u.add_argument("target", help="用户主页链接或用户 ID")
    u.add_argument("-t", "--type", choices=["illust", "manga", "novel"], default="illust")
    u.add_argument("-p", "--page", type=int, default=1)
    u.add_argument("-n", "--count", type=int, default=20)
    u.set_defaults(func=cmd_user, kind="user")

    d = sub.add_parser("download", parents=[common], help="下载作品、小说或整个小说系列")
    d.add_argument("targets", nargs="+", help=target_help + "；可以一次给多个")
    d.add_argument("-k", "--kind", choices=["artwork", "novel", "series"], default="artwork",
                   help="纯数字当作哪种 ID（默认 artwork）")
    d.add_argument("--out", help="保存目录（默认环境变量 PIXIV_DOWNLOAD_DIR，否则当前目录下 pixiv-downloads）")
    d.add_argument("-q", "--quality", choices=["original", "regular", "small"], default="original")
    d.add_argument("--images", action="store_true", help="多页作品保存成图片文件夹，不合成 PDF")
    d.add_argument("--no-merge", action="store_true", help="小说系列每篇单独存一个文件，不合并")
    d.set_defaults(func=cmd_download)

    k = sub.add_parser("cookie", parents=[common], help="设置、检查或删除登录 Cookie")
    mode = k.add_mutually_exclusive_group()
    mode.add_argument("--login", action="store_true",
                      help="打开一个临时浏览器窗口，你自己登录，脚本自动拿到 Cookie（需要 Chrome/Edge/Brave/Chromium）")
    mode.add_argument("--set", metavar="COOKIE", help="保存 Cookie；填 - 则从标准输入读取，避免留在命令历史里")
    mode.add_argument("--clear", action="store_true", help="删除保存的 Cookie")
    k.add_argument("--browser", help="--login 用哪个浏览器：程序名或完整路径（默认自动找）")
    k.add_argument("--timeout", type=float, default=300, help="--login 最多等几秒（默认 300）")
    k.set_defaults(func=cmd_cookie)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    for name in ("page", "count"):
        if getattr(args, name, 1) < 1:
            log(f"错误[usage]：--{name} 必须大于 0")
            return 2
    try:
        return args.func(args)
    except UsageError as exc:
        log(f"错误[usage]：{exc}")
        return 2
    except PixivError as exc:
        log(f"错误[{exc.kind}]：{exc}")
        if exc.kind == "auth" and not config.load_cookies()[0]:
            log("提示：还没设置 Cookie，运行 pixiv.py cookie --set - 登录后再试")
        return EXIT_CODES.get(exc.kind, 1)
    except KeyboardInterrupt:
        log("已取消")
        return 130
