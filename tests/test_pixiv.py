"""Offline tests: python -m unittest discover -s tests  (no network needed)."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from pixiv_skill import config  # noqa: E402
from pixiv_skill.api import PixivClient, PixivError  # noqa: E402
from pixiv_skill.cli import main  # noqa: E402
from pixiv_skill.download import convert_markup, download_series, safe_name  # noqa: E402
from pixiv_skill.models import from_artwork, from_novel, from_ranking, line  # noqa: E402
from pixiv_skill.targets import Target, parse_target  # noqa: E402


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b"", headers=None):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class TargetTests(unittest.TestCase):
    def test_urls(self):
        cases = {
            "https://www.pixiv.net/artworks/123": Target("artwork", "123"),
            "https://www.pixiv.net/en/artworks/456": Target("artwork", "456"),
            "https://www.pixiv.net/novel/show.php?id=789": Target("novel", "789"),
            "https://www.pixiv.net/novel/show.php?mode=cover&id=790": Target("novel", "790"),
            "https://www.pixiv.net/novel/series/111": Target("series", "111"),
            "https://www.pixiv.net/users/222": Target("user", "222"),
            "https://www.pixiv.net/member.php?id=333": Target("user", "333"),
            "https://i.pximg.net/img-original/img/2026/01/01/00/00/00/444_p0.png": Target("artwork", "444"),
        }
        for text, expected in cases.items():
            self.assertEqual(parse_target(text), expected, text)

    def test_prefixes_and_bare_numbers(self):
        self.assertEqual(parse_target("n:5"), Target("novel", "5"))
        self.assertEqual(parse_target("ser：6"), Target("series", "6"))
        self.assertEqual(parse_target("u:7"), Target("user", "7"))
        self.assertEqual(parse_target("8"), Target("artwork", "8"))
        self.assertEqual(parse_target("8", default="novel"), Target("novel", "8"))
        self.assertIsNone(parse_target("abc"))
        self.assertIsNone(parse_target("zz:9"))


class ModelTests(unittest.TestCase):
    def test_artwork_card(self):
        w = from_artwork({"id": "1", "illustType": 1, "title": "T", "userName": "U", "userId": "2",
                          "tags": ["中文", "猫"], "pageCount": 3, "xRestrict": 1, "aiType": 2})
        self.assertEqual((w.type, w.page_count, w.r18, w.ai, w.chinese), ("manga", 3, 1, True, True))
        self.assertIsNone(w.bookmarks)  # search cards have no bookmark count
        self.assertIn("[R-18][AI][中文]", line(w, 1))

    def test_detail_tags_shape(self):
        w = from_artwork({"illustId": "9", "illustType": 2, "tags": {"tags": [{"tag": "a"}]},
                          "bookmarkCount": 5, "seriesNavData": {"seriesId": 3, "title": "S"}})
        self.assertEqual((w.id, w.type, w.tags, w.bookmarks, w.series_id), ("9", "ugoira", ["a"], 5, "3"))

    def test_novel_and_ranking(self):
        n = from_novel({"id": "1", "title": "N", "characterCount": 1234, "language": "zh-cn", "tags": {"tags": []}})
        self.assertTrue(n.chinese)
        self.assertEqual(n.text_count, 1234)
        r = from_ranking({"illust_id": 5, "illust_type": "1", "rank": 2, "rating_count": 10,
                          "illust_content_type": {"sexual": 0}, "tags": ["x"], "illust_series": False})
        self.assertEqual((r.id, r.type, r.rank, r.bookmarks, r.series_id), ("5", "manga", 2, 10, ""))


class MarkupTests(unittest.TestCase):
    def test_convert(self):
        text = convert_markup("[chapter:一]A[newpage]B [[rb:漢字 > かんじ]] [pixivimage:12-1] [jump:3]")
        self.assertIn("========== 一 ==========", text)
        self.assertIn("---", text)
        self.assertIn("漢字（かんじ）", text)
        self.assertIn("https://www.pixiv.net/artworks/12", text)
        self.assertIn("跳到第 3 页", text)

    def test_safe_name(self):
        self.assertEqual(safe_name('a/b:c*?"<>|d'), "a_b_c______d")
        self.assertEqual(safe_name("a?."), "a")
        self.assertEqual(safe_name("   "), "untitled")
        self.assertEqual(len(safe_name("x" * 200)), 60)


class ClientTests(unittest.TestCase):
    def client(self, *responses):
        c = PixivClient({"PHPSESSID": "x"}, delay=0, retries=2)
        c.session.get = mock.Mock(side_effect=list(responses))
        return c

    def test_api_error_and_not_found(self):
        c = self.client(FakeResponse(404, {"error": True, "message": ""}))
        with self.assertRaises(PixivError) as ctx:
            c.artwork("1")
        self.assertEqual(ctx.exception.kind, "not_found")
        c = self.client(FakeResponse(200, {"error": True, "message": "bad"}))
        with self.assertRaises(PixivError) as ctx:
            c.artwork("1")
        self.assertIn("bad", str(ctx.exception))

    @mock.patch("time.sleep")
    def test_retry_then_success(self, _sleep):
        c = self.client(FakeResponse(503, {}), FakeResponse(200, {"error": False, "body": {"id": "1"}}))
        self.assertEqual(c.artwork("1"), {"id": "1"})
        self.assertEqual(c.session.get.call_count, 2)

    @mock.patch("time.sleep")
    def test_retry_gives_up(self, _sleep):
        c = self.client(FakeResponse(429, {}), FakeResponse(429, {}))
        with self.assertRaises(PixivError) as ctx:
            c.artwork("1")
        self.assertEqual(ctx.exception.kind, "rate_limit")

    def test_search_maps_order_and_type(self):
        body = {"error": False, "body": {"manga": {"total": 2, "lastPage": 1, "data": [{"id": "1"}, {}]}}}
        c = self.client(FakeResponse(200, body))
        result = c.search("manga", "猫 耳", order="popular")
        url = c.session.get.call_args.args[0]
        params = c.session.get.call_args.kwargs["params"]
        self.assertTrue(url.endswith("/ajax/search/manga/%E7%8C%AB%20%E8%80%B3"))
        self.assertEqual((params["order"], params["type"]), ("popular_d", "manga"))
        self.assertEqual(len(result["items"]), 1)  # entries without id are ad slots

    def test_user_works_batches_and_keeps_order(self):
        ids = [str(i) for i in range(60, 0, -1)]
        first = {"error": False, "body": {"works": {i: {"id": i} for i in ids[:48]}}}
        second = {"error": False, "body": {"works": {i: {"id": i} for i in ids[48:]}}}
        c = self.client(FakeResponse(200, first), FakeResponse(200, second))
        works = c.user_works("9", "illust", ids)
        self.assertEqual([w["id"] for w in works], ids)
        self.assertEqual(c.session.get.call_count, 2)


class SeriesTests(unittest.TestCase):
    def test_merge_and_partial_failure(self):
        client = mock.Mock()
        client.novel_series.return_value = {"title": "S", "userName": "U"}
        client.novel_series_titles.return_value = [
            {"id": "1", "title": "a", "available": True},
            {"id": "2", "title": "b", "available": True},
            {"id": "3", "title": "hidden", "available": False},
        ]

        def novel(nid):
            if nid == "2":
                raise PixivError("boom")
            return {"id": nid, "title": "ch" + nid, "content": "body" + nid, "tags": {"tags": []}}

        client.novel.side_effect = novel
        with tempfile.TemporaryDirectory() as tmp:
            meta, files, failures = download_series(client, "7", Path(tmp), progress=lambda _: None)
            self.assertEqual(len(files), 1)
            self.assertEqual(len(failures), 1)
            text = files[0].read_text(encoding="utf-8")
            self.assertIn("body1", text)
            self.assertNotIn("hidden", text)
            self.assertEqual(list(Path(tmp).glob("*.part")), [])


class ConfigTests(unittest.TestCase):
    def test_parse_cookie_string(self):
        self.assertEqual(config.parse_cookie_string("abc"), {"PHPSESSID": "abc"})
        self.assertEqual(config.parse_cookie_string("Cookie: PHPSESSID=1; a=2"), {"PHPSESSID": "1", "a": "2"})
        self.assertEqual(config.parse_cookie_string("  "), {})

    def test_save_load_clear_and_env_priority(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"PIXIV_SKILL_HOME": tmp}, clear=False):
            os.environ.pop("PIXIV_COOKIE", None)
            os.environ.pop("PIXIV_PHPSESSID", None)
            self.assertEqual(config.load_cookies(), ({}, ""))
            path = config.save_cookies({"PHPSESSID": "file"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"cookies": {"PHPSESSID": "file"}})
            self.assertEqual(config.load_cookies()[0], {"PHPSESSID": "file"})
            with mock.patch.dict(os.environ, {"PIXIV_PHPSESSID": "env"}):
                self.assertEqual(config.load_cookies()[0], {"PHPSESSID": "env"})
            self.assertTrue(config.clear_cookies())
            self.assertFalse(path.exists())


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_bad_target_is_usage_error(self):
        code, _, err = self.run_cli("info", "abc")
        self.assertEqual(code, 2)
        self.assertIn("usage", err)

    def test_bad_page(self):
        self.assertEqual(self.run_cli("search", "x", "--page", "0")[0], 2)

    @mock.patch("pixiv_skill.cli.PixivClient")
    def test_search_json(self, client_cls):
        client_cls.return_value.search.return_value = {
            "total": 1, "last_page": 1, "items": [{"id": "1", "title": "T", "illustType": 0}]}
        code, out, _ = self.run_cli("search", "猫", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["items"][0]["url"], "https://www.pixiv.net/artworks/1")

    @mock.patch("pixiv_skill.cli.PixivClient")
    def test_not_found_exit_code(self, client_cls):
        client_cls.return_value.artwork.side_effect = PixivError("gone", "not_found")
        self.assertEqual(self.run_cli("info", "1")[0], 4)


class LoginTests(unittest.TestCase):
    def test_find_session_only_accepts_logged_in_values(self):
        from pixiv_skill.login import find_session
        anon = {"name": "PHPSESSID", "domain": ".pixiv.net", "value": "a1b2c3d4e5"}
        other_site = {"name": "PHPSESSID", "domain": ".example.com", "value": "123_abc"}
        good = {"name": "PHPSESSID", "domain": ".pixiv.net", "value": "12345_AbCdEf"}
        self.assertIsNone(find_session([anon, other_site]))
        self.assertEqual(find_session([anon, good]), "12345_AbCdEf")

    def test_missing_browser_is_auth_error(self):
        from pixiv_skill import login
        with mock.patch.object(login, "browser_candidates", return_value=[]), \
                mock.patch.dict(os.environ, {"PIXIV_BROWSER": ""}):
            with self.assertRaises(login.LoginError) as ctx:
                login.find_browser()
        self.assertEqual(ctx.exception.kind, "auth")

    def test_cli_login_saves_cookie(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"PIXIV_SKILL_HOME": tmp, "PIXIV_PHPSESSID": "", "PIXIV_COOKIE": ""}), \
                mock.patch("pixiv_skill.login.browser_login", return_value="1_x"), \
                mock.patch("pixiv_skill.cli.PixivClient") as client_cls:
            client_cls.return_value.logged_in.return_value = True
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["cookie", "--login"])
            self.assertEqual(code, 0)
            self.assertEqual(config.load_cookies()[0], {"PHPSESSID": "1_x"})
            self.assertNotIn("1_x", out.getvalue() + err.getvalue())  # never echo the cookie


if __name__ == "__main__":
    unittest.main()
