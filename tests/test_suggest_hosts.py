"""tools/suggest-hosts.py: how it reads a name, what it never suggests, and that it learns, on a small made-up world.

Standard library only, no network: the names come from a file the test writes.
"""
import importlib.machinery
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(ROOT, "tools", "suggest-hosts.py")
sys.path.insert(0, HERE)
import test_core  # noqa: E402  (its list of names that must never be blocked as a whole)

loader = importlib.machinery.SourceFileLoader("suggest_hosts", TOOL)
spec = importlib.util.spec_from_loader("suggest_hosts", loader)
sh = importlib.util.module_from_spec(spec)
loader.exec_module(sh)

LISTS = {
    "tiktok": ["tiktok.com", "tiktokcdn.com", "tiktokcdn-us.com", "tiktokv.com", "byteimg.com", "ibyteimg.com",
               "bytedance.map.fastly.net"],
    "steam": ["steampowered.com", "steamcommunity.com", "steamstatic.com", "steamcontent.com",
              "steamcdn-a.akamaihd.net"],
    "roblox": ["roblox.com", "rbxcdn.com", "robloxcdn.com", "rbxinfra.com"],
}
SYLLABLES = ["ka", "li", "mo", "to", "re", "vi", "na", "su", "pe", "da", "lo", "mi", "ra", "ne", "ba", "go", "fu",
             "zen", "tor", "mar", "sol", "kin", "dal", "ver", "pix", "nov", "lum", "bri"]
WORDS = ["mail", "api", "cdn", "www", "static", "img", "login", "shop", "news", "media", "video", "cloud", "app",
         "stream", "live", "chat", "teams", "office", "game", "play", "data", "edge", "assets", "auth"]
TLDS = ["com", "net", "org", "io", "co.uk", "de", "info", "tv"]


def ordinary_names(count=5000, seed=3):
    """Names of made-up sites, with the words real names have ("livestream", "msteams", "gameplay") and subdomains."""
    rnd = random.Random(seed)
    names = []
    while len(names) < count:
        base = "".join(rnd.choice(SYLLABLES) for _ in range(rnd.randint(2, 3)))
        if rnd.random() < 0.4:
            base = rnd.choice(WORDS) + rnd.choice(["", "-"]) + base
        domain = base + "." + rnd.choice(TLDS)
        names.append(domain)
        for _ in range(rnd.randint(0, 3)):
            names.append(rnd.choice(WORDS) + rnd.choice(["", "1", "-eu", "-v2"]) + "." + domain)
    return names


def world_names():
    """The ordinary names, the listed apps' own hosts (known to the lists) and some the lists miss."""
    names = ordinary_names()
    names += ["www.tiktok.com", "m.tiktok.com", "p16-sign.tiktokcdn-us.com", "v16.tiktokcdn.com", "api.tiktokv.com",
              "p16.tiktokcdn-us.com.edgesuite.net", "store.steampowered.com", "cdn.steamstatic.com",
              "www.roblox.com", "tr.rbxcdn.com", "c0.rbxcdn.com", "apis.roblox.com"]
    missed = ["tiktokv.eu", "tiktokcdn-eu.com", "api16.tiktokv.eu", "steamcontent-eu.com", "robloxcdn.net"]
    return names + missed, missed


class ReadingANameTests(unittest.TestCase):
    def test_platforms_and_the_public_suffix_are_cut_off(self):
        self.assertEqual(sh.app_labels("dualstack.twimg.twitter.map.fastly.net"), ["dualstack", "twimg", "twitter"])
        self.assertEqual(sh.app_labels("zynga4-a.akamaihd.net.edgesuite.net"), ["zynga4-a"])
        self.assertEqual(sh.app_labels("api-stream.twitter.com.cdn.cloudflare.net"), ["api-stream", "twitter"])
        self.assertEqual(sh.app_labels("www.bbc.co.uk"), ["www", "bbc"])
        self.assertEqual(sh.app_labels("akamaihd.net"), [])
        self.assertEqual(sh.features("akamaihd.net"), ())

    def test_an_alias_on_a_platform_is_the_host_it_stands_for(self):
        self.assertEqual(sh.unwrap("p16.tiktokcdn-us.com.edgesuite.net"), "p16.tiktokcdn-us.com")
        self.assertEqual(sh.unwrap("xsts.auth.xboxlive.com.akadns.net"), "xsts.auth.xboxlive.com")
        self.assertEqual(sh.unwrap("steamcdn-a.akamaihd.net"), "steamcdn-a.akamaihd.net")
        cover = sh.Cover({"tiktok": ["tiktokcdn-us.com"]})
        for name in ("tiktokcdn-us.com", "a.b.tiktokcdn-us.com", "p16.tiktokcdn-us.com.edgesuite.net"):
            self.assertEqual(cover(name), "tiktok", name)
        for name in ("nottiktokcdn-us.com", "tiktokcdn-us.com.example.org", "edgesuite.net"):
            self.assertIsNone(cover(name), name)

    def test_the_pieces_are_sorted_and_digits_count_as_one(self):
        fs = sh.features("p16-va.tiktokcdn.com")
        self.assertEqual(list(fs), sorted(fs))
        self.assertIn("L:p0-va", fs)
        self.assertIn("D:tiktokcdn", fs)
        self.assertIn("P:p0-va.tiktokcdn", fs)

    def test_names_come_from_csv_plain_lines_or_a_zip_and_junk_is_skipped(self):
        lines = ["1,google.com", "2,UPPER.Example.COM.", "3,bad name.com", "4,localhost", "5,ünï.com", "",
                 "6,google.com", "7,", "8,a_b.example.net", "plain.example.org", "9,-dash.example.com"]
        expected = ["google.com", "upper.example.com", "a_b.example.net", "plain.example.org"]
        self.assertEqual(sh.parse_names(lines), expected)
        with tempfile.TemporaryDirectory() as tmp:
            csv = os.path.join(tmp, "top.csv")
            with open(csv, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
            self.assertEqual(sh.read_names(csv), expected)
            packed = os.path.join(tmp, "top.zip")
            with zipfile.ZipFile(packed, "w") as zf:
                zf.write(csv, "top-1m.csv")
            self.assertEqual(sh.read_names(packed), expected)
            with zipfile.ZipFile(packed, "a") as zf:
                zf.writestr("second.csv", "1,example.com")
            with self.assertRaises(ValueError):
                sh.read_names(packed)


class AnAppsOwnWordsTests(unittest.TestCase):
    def test_whole_sites_and_hosts_on_platforms_give_words_and_somebody_elses_site_does_not(self):
        words = sh.app_words({"teams": ["teams.microsoft.com", "skypeforbusiness.com", "lync.com"],
                              "steam": ["steamcdn-a.akamaihd.net", "steampowered.com"],
                              "x": ["x.com", "twimg.com", "api-stream.twitter.com.cdn.cloudflare.net"]})
        self.assertEqual(words["teams"], {"skypeforbusiness"})          # not "microsoft"; "lync" is too short
        self.assertEqual(words["steam"], {"steamcdn-a", "steampowered"})
        self.assertEqual(words["x"], {"twimg", "twitter"})                # not "x": it is in everything

    def test_the_zone_stops_at_the_apps_word_and_never_takes_the_site_it_is_on(self):
        rx = sh.matcher({"tiktokcdn"})
        self.assertEqual(sh.zone("pull-flv.tiktokcdn.com.wsdvs.com", rx), "tiktokcdn.com.wsdvs.com")
        self.assertEqual(sh.zone("tiktokcdn-eu.com", rx), "tiktokcdn-eu.com")
        self.assertIsNone(sh.zone("example.com", rx))
        self.assertEqual(sh.zone("blog.youtube", sh.matcher({"youtube"})), "blog.youtube")    # never the whole .youtube


class WhatItSuggestsTests(unittest.TestCase):
    def test_hosts_of_one_shape_are_one_line_with_a_pattern_that_matches_them_only(self):
        lists = {"instagram": ["instagram.com", "cdninstagram.com"]}
        hosts = ["instagram.fdel29-1.fna.fbcdn.net", "instagram.fsdu7-1.fna.fbcdn.net", "instagram.ffjr1-6.fna.fbcdn.net"]
        groups = sh.group([(0.99, "instagram", h) for h in hosts], lists)
        self.assertEqual(len(groups), 1)
        line = groups[0].line
        self.assertEqual(line, r"/(^|\.)instagram\.[a-z0-9_-]+\.fna\.fbcdn\.net$/")
        rx = re.compile(line[1:-1])
        for h in hosts + ["x.instagram.fbos2-1.fna.fbcdn.net"]:
            self.assertTrue(rx.search(h), h)
        for h in ("instagram.com", "scontent.fdel29-1.fna.fbcdn.net", "instagram.fdel29-1.fna.fbcdn.net.example.org"):
            self.assertFalse(rx.search(h), h)

    def test_a_zone_on_somebody_elses_site_says_so(self):
        groups = sh.group([(0.99, "tiktok", "pull-flv-l1.tiktokcdn.com.wsdvs.com"), (0.99, "tiktok", "tiktok-minis.us")],
                          {"tiktok": ["tiktokcdn.com", "tiktok.com"]})
        self.assertEqual([(g.kind, g.line) for g in groups],
                         [("site", "||tiktok-minis.us^"), ("alias", "||tiktokcdn.com.wsdvs.com^")])
        self.assertIn("never wsdvs.com", groups[1].note)

    def test_a_site_is_not_offered_whole_when_only_the_start_of_its_names_looks_like_the_app(self):
        scored = [(0.99, "youtube", "rr%d---sn-abc.gvt1.com" % i) for i in range(3)] + [(0.99, "youtube", "ytfan.org")]
        judge = {"gvt1.com": (0.01, "youtube"), "ytfan.org": (0.99, "youtube")}.get
        lines = {g.line: g for g in sh.group(scored, {"youtube": ["youtube.com"]}, judge=judge)}
        self.assertEqual(sorted(lines), ["*.gvt1.com", "||ytfan.org^"])
        self.assertIn("never block it whole", lines["*.gvt1.com"].note)
        self.assertEqual(lines["*.gvt1.com"].names, 3)

    def test_nothing_that_must_never_be_blocked_whole_is_suggested_whole(self):
        self.assertLessEqual(test_core.ListSafetyTests.NEVER, sh.NEVER, "the tool forgets a name the lists may not block")
        lists = {"discord": ["discord.com", "watchanimeattheoffice.com"], "steam": ["steampowered.com"]}
        scored = [(0.99, "discord", "office.com"), (0.99, "discord", "www.office.com"), (0.99, "steam", "fastly.net"),
                  (0.99, "discord", "cdn.office.net.edgesuite.net"), (0.99, "steam", "a.akamaihd.net")]
        for g in sh.group(scored, lists):
            for d in sh.NEVER:
                self.assertNotEqual(g.line, "||%s^" % d)
            if sh.site(g.line) in sh.NEVER:
                self.assertIn("exact name only", g.note)


class LearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.names, cls.missed = world_names()
        cls.scored, cls.models = sh.cross_scored(LISTS, cls.names, progress=lambda text: None)

    def test_it_finds_the_hosts_the_lists_miss_with_the_right_app(self):
        found = {name: sid for _, sid, name in self.scored}
        self.assertEqual(found.get("tiktokv.eu"), "tiktok")
        self.assertEqual(found.get("tiktokcdn-eu.com"), "tiktok")
        self.assertEqual(found.get("steamcontent-eu.com"), "steam")

    def test_ordinary_names_are_left_alone(self):
        flagged = [name for _, _, name in self.scored if name not in self.missed and not name.endswith(".tiktokv.eu")]
        self.assertLessEqual(len(flagged), len(self.names) // 1000, flagged)

    def test_a_listed_name_is_never_suggested(self):
        cover = sh.Cover(LISTS)
        self.assertEqual([n for _, _, n in self.scored if cover(n)], [])

    def test_a_model_written_and_read_back_scores_the_same(self):
        model = self.models[0]
        again = sh.Model.from_json(json.loads(json.dumps(model.to_json())))
        for name in ["tiktokv.eu", "steamcontent-eu.com", "mail.example.com", "akamaihd.net"]:
            self.assertEqual(again.score(name), model.score(name))

    def test_the_backtest_counts_what_was_found_missed_and_could_not_be(self):
        new = dict(LISTS, tiktok=LISTS["tiktok"] + ["tiktokv.eu"], steam=LISTS["steam"] + ["zz-unrelated.org"],
                   snapchat=["snapchat.com"])
        rows, found = sh.backtest(LISTS, new, self.names, progress=lambda text: None)
        verdicts = {d: v for _, d, _, _, v in rows}
        self.assertEqual(verdicts, {"tiktokv.eu": "found", "zz-unrelated.org": "missed",
                                    "snapchat.com": "the app was not in the lists then"})
        self.assertEqual(found, 1)


class TheCommandTests(unittest.TestCase):
    def run_tool(self, tmp, seed, *extra):
        out = os.path.join(tmp, "out-%s.md" % seed)
        env = dict(os.environ, PYTHONHASHSEED=str(seed))
        subprocess.run([sys.executable, TOOL, "--names", os.path.join(tmp, "names.csv"), "--lists",
                        os.path.join(tmp, "lists"), "--out", out] + list(extra), check=True, env=env,
                       capture_output=True, text=True)
        with open(out, encoding="utf-8") as fh:
            return fh.read()

    def test_the_same_input_gives_the_same_file_whatever_the_hash_seed(self):
        names, _ = world_names()
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "lists"))
            for sid, domains in list(LISTS.items()) + [("guard", ["dns.google"])]:
                with open(os.path.join(tmp, "lists", sid + ".txt"), "w", encoding="utf-8") as fh:
                    fh.write("! Title: sinko / %s\n" % sid + "".join("||%s^\n" % d for d in domains))
            with open(os.path.join(tmp, "names.csv"), "w", encoding="utf-8") as fh:
                fh.write("".join("%d,%s\n" % (i + 1, n) for i, n in enumerate(names)))
            first = self.run_tool(tmp, 1, "--save-model", os.path.join(tmp, "m1.json"))
            second = self.run_tool(tmp, 2, "--save-model", os.path.join(tmp, "m2.json"))
            self.assertEqual(first, second)
            with open(os.path.join(tmp, "m1.json"), "rb") as a, open(os.path.join(tmp, "m2.json"), "rb") as b:
                self.assertEqual(a.read(), b.read())
        self.assertIn("`||tiktokv.eu^`", first)
        self.assertIn("Every line is a guess", first)
        self.assertNotIn("guard", first)


class GitTests(unittest.TestCase):
    def test_the_lists_of_a_git_ref_are_read_without_the_guard_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "lists"))
            for name, text in (("tiktok.txt", "! x\n||tiktok.com^\n"), ("guard.txt", "||dns.google^\n")):
                with open(os.path.join(tmp, "lists", name), "w", encoding="utf-8") as fh:
                    fh.write(text)
            git = ["git", "-C", tmp, "-c", "user.name=t", "-c", "user.email=t@example.org"]
            subprocess.run(git[:3] + ["init", "-q"], check=True)
            subprocess.run(git + ["add", "lists"], check=True)
            subprocess.run(git + ["commit", "-qm", "lists"], check=True)
            self.assertEqual(sh.lists_at("HEAD", root=tmp), {"tiktok": ["tiktok.com"]})
        with self.assertRaises(ValueError):
            sh.lists_at("--output=/tmp/x")


if __name__ == "__main__":
    unittest.main()
