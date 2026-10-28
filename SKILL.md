---
name: pixiv
description: "Search, inspect and download Pixiv illustrations, manga, ugoira and novels: keyword search, rankings, artist works, multi-page works to PDF, novel series merged into one TXT. Use when the user mentions Pixiv, a pixiv.net link, or wants Pixiv artwork or novels."
---

# Pixiv

All work goes through one script: `python scripts/pixiv.py <command> ...`, where `scripts/` is the folder next to this file. Use the absolute path; the working directory may be different. Requires Python 3.9+ and `pip install -r requirements.txt` from this folder (requests, img2pdf, Pillow).

## Commands

| Goal | Command |
| --- | --- |
| Search | `search <keyword> [-t illust\|manga\|novel] [-p PAGE] [-o newest\|oldest\|popular\|male\|female] [-n COUNT] [-b MIN_BOOKMARKS] [--r18 all\|safe\|only] [--exact]` |
| Ranking | `rank [daily\|weekly\|monthly\|rookie\|original\|daily_ai\|male\|female\|daily_r18\|...] [-t all\|illust\|manga\|ugoira] [-p PAGE] [-d YYYYMMDD]` |
| Details | `info <target>` (artwork, novel, series with chapter list, or user) |
| Artist's works | `user <user-url-or-id> [-t illust\|manga\|novel] [-p PAGE]` |
| Download | `download <target> [<target> ...] [--out DIR] [-q original\|regular\|small] [--images] [--no-merge]` |
| Login | `cookie` (check), `cookie --login` (browser login), `cookie --set -` (read from stdin), `cookie --clear` |

Targets: a pixiv.net URL is recognized automatically. A bare number means an artwork (illust/manga/ugoira). Prefix other IDs: `n:123` novel, `s:123` novel series, `u:123` user. Or pass `-k novel|series|user` to say what bare numbers are.

Add `--json` to any command for machine-readable stdout.

## How to work

- If the user already gave a link, ID or a clearly unique work, act on it directly. Do not search again.
- Keep the user's requested type, page, sort order and count. Search shows 20 results by default. The output says how to get the next page.
- `-o popular|male|female` only works with Pixiv Premium. Without it Pixiv quietly returns newest-first. Say so if the user asked for popular results.
- `-b` (minimum bookmarks) on illust/manga search fetches each work one by one (about 1 second each). It only filters the current page of 60. Prefer `rank` when the user just wants popular works.
- Downloads: a single page is saved as the image. Multi-page works become one PDF (split every 50 pages), or an image folder with `--images`. Ugoira becomes a GIF. A novel becomes a TXT. A series (`s:ID`) becomes one merged TXT, or one file per chapter with `--no-merge`.
- Downloads go to `--out`, else `$PIXIV_DOWNLOAD_DIR`, else `./pixiv-downloads`. Each saved file is printed as `SAVED: <absolute path>`. Failures are printed as `FAILED: ...`. Only report or attach files that appear on `SAVED:` lines of this run.
- Progress and errors go to stderr; results go to stdout.

## Login (cookie)

Without a cookie, all-ages works can be searched and downloaded. R-18 works, R-18 rankings and some restricted works need the user's own login cookie (`PHPSESSID` from pixiv.net in their browser).

- Ask the user to run `python scripts/pixiv.py cookie --login` themselves. It opens a fresh, temporary browser window (Chrome, Edge, Brave or Chromium). The user logs in there, and the cookie is saved automatically. The script never sees the password and never touches the user's normal browser profile. Only run it for the user if they are at this machine and asked you to, because they have to log in inside the window.
- Alternatives: `python scripts/pixiv.py cookie --set -` (paste the `PHPSESSID` value), or the `PIXIV_PHPSESSID` environment variable. Step-by-step help for every browser: [docs/cookie.md](docs/cookie.md).
- Never ask the user to paste the cookie into chat. Never print, log or echo it.
- R-18 content also requires the Pixiv account itself to have R-18 display enabled in its settings.

## Exit codes and errors

| Code | Meaning | What to do |
| --- | --- | --- |
| 0 | OK | |
| 1 | Other error, or some items in a multi-target download failed | Read stderr; keep the files that did succeed |
| 2 | Bad arguments or unrecognized target | Fix the command |
| 3 | Login missing, invalid or not allowed (R-18 off) | Tell the user to set or refresh the cookie; don't retry unchanged |
| 4 | Work not found, deleted or private | Report it |
| 5 | Network, Pixiv server error or rate limit (already retried) | Wait a bit and try once more at most |

## Respect the source

Downloads are for personal use. Remind the user not to repost works without the artist's permission when relevant. Keep the default request delay. Don't run large batch crawls.
