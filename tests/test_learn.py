"""Learning new addresses of blocked apps (class Learner, `sinko learn`, docs/maintainers/host-model.md step 2).

Pi-hole is the in-memory mock; the model is the one the release ships (model/host-model.json), so these tests also say
what that model does with real names.
"""
import contextlib
import datetime as dt
import importlib.machinery
import importlib.util
import io
import os
import tempfile
import time
import unittest
from unittest import mock

import fake_release
import mock_pihole

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LISTS = os.path.join(ROOT, "lists")
MODEL = os.path.join(ROOT, "model", "host-model.json")

loader = importlib.machinery.SourceFileLoader("sinko_learn", os.path.join(ROOT, "bin", "sinko"))
spec = importlib.util.spec_from_loader("sinko_learn", loader)
pb = importlib.util.module_from_spec(spec)
loader.exec_module(pb)

KID, OTHER_KID = "192.168.1.21", "192.168.1.22"


class TheShippedModel(unittest.TestCase):
    def test_it_knows_every_app_of_the_catalogue_and_nothing_else(self):
        model = pb.load_model(MODEL)
        catalog = pb.load_catalog(LISTS)
        self.assertEqual(sorted(model.apps), sorted(s["id"] for s in catalog["services"]),
                         "an app was added or removed: train the model again (model/README.md)")

    def test_it_is_small_enough_for_the_box(self):
        self.assertLess(os.path.getsize(MODEL), 600 * 1024)

    def test_what_it_says_about_a_few_real_names(self):
        model = pb.load_model(MODEL)
        for name, app in (("tiktok-minis.us", "tiktok"), ("byteoversea.net", "tiktok"), ("youtubetv.com", "youtube")):
            p, guess = model.score(name)
            self.assertGreaterEqual(p, pb.MODEL_THRESHOLD, name)
            self.assertEqual(guess, app, name)
        for name in ("www.bbc.co.uk", "office.com", "mail.google.com", "akamaihd.net"):
            self.assertLess(model.score(name)[0], pb.MODEL_THRESHOLD, name)

    def test_what_is_not_a_model_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for text in ("[]", '{"v": 2}', '{"v": 1, "apps": ["a"], "b1": 0, "w1": {}, "b2": [0, 1], "w2": {}}',
                         '{"v": 1, "apps": ["a"], "b1": 0, "w1": {}, "b2": [0], "w2": {"x": [[3, 1.0]]}}', "NaN"):
                path = os.path.join(tmp, "m.json")
                with open(path, "w") as fh:
                    fh.write(text)
                with self.assertRaises(ValueError, msg=text):
                    pb.load_model(path)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.httpd, self.store = fake_release.serve_pihole()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.api = pb.Api("http://127.0.0.1:%d" % self.httpd.server_port, password=mock_pihole.PASSWORD)
        self.api.login()
        self.catalog = pb.load_catalog(LISTS)
        self.ctl = pb.Controller(self.api, self.catalog, "https://lists.example/l")
        self.ctl.setup(run_gravity=False)
        self.learner = pb.Learner(model_file=MODEL, lists_dir=LISTS)
        self.now = time.time()
        self.day = time.strftime("%Y-%m-%d", time.localtime(self.now))

    def block(self, *apps):
        groups = self.api.group_map()
        for sid in apps:
            g = groups[pb.svc_group(sid)]
            self.api.put_group(g["name"], g.get("comment") or "", True)

    def lookup(self, name, status="FORWARDED", client=KID, ago=0.0):
        self.store.add_query(name, status=status, client=client, when=self.now - ago)

    def look(self, epoch=None):
        return self.learner.run(self.api, self.api.group_map(), self.now if epoch is None else epoch)

    def learned(self):
        return pb.learned_rules(self.api.domains())

    def zones(self):
        return sorted(r["zone"] for r in self.learned() if not r["back"])


class WhatIsLearned(Fixture):
    def test_a_new_name_of_a_blocked_app_right_after_the_app_was_stopped_on_that_device(self):
        self.block("tiktok")
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        self.lookup("tiktok-minis.us", ago=25)
        restarts = self.store.dns_restarts
        actions = self.look()
        self.assertEqual(self.zones(), ["tiktok-minis.us"])
        rule = next(d for d in self.store.domains if d["comment"] and d["comment"].startswith("pb-learned:"))
        self.assertEqual((rule["type"], rule["kind"], rule["domain"]), ("deny", "regex", r"(^|\.)tiktok-minis\.us$"))
        self.assertEqual(rule["comment"], "pb-learned:tiktok " + self.day)
        self.assertEqual(rule["groups"], [self.api.group_map()["pb-svc-tiktok"]["id"]])
        self.assertTrue(rule["enabled"])
        self.assertEqual(self.store.dns_restarts, restarts + 1, "an answer the box already holds must not outlive the rule")
        self.assertTrue(any("tiktok-minis.us" in a for a in actions), actions)

    def test_the_refusal_may_come_just_after_the_new_name(self):
        self.block("tiktok")
        self.lookup("byteoversea.net", ago=60)
        self.lookup("tiktok.com", "GRAVITY", ago=5)
        self.look()
        self.assertEqual(self.zones(), ["byteoversea.net"])

    def test_on_a_shared_platform_only_the_apps_own_part_is_blocked(self):
        self.block("youtube")
        self.lookup("www.youtube.com", "GRAVITY", ago=10)
        self.lookup("youtubetoken-pa.googleapis.com", ago=8)
        self.look()
        self.assertEqual(self.zones(), ["youtubetoken-pa.googleapis.com"])
        self.assertNotIn("googleapis.com", self.zones())

    def test_two_lookups_of_one_name_in_one_second_one_with_a_cname(self):
        self.block("tiktok")
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        self.lookup("tiktok-minis.us", ago=25)
        self.lookup("tiktok-minis.us", ago=25)
        self.store.query_log[-1]["cname"] = "edge.tiktok-minis.us"
        self.look()
        self.assertEqual(self.zones(), ["tiktok-minis.us"])

    def test_a_name_is_learned_once_however_often_it_is_seen(self):
        self.block("tiktok")
        for ago in (40, 30, 20):
            self.lookup("tiktok.com", "GRAVITY", ago=ago)
            self.lookup("pull-1.tiktok-minis.us", ago=ago - 1)
            self.lookup("pull-2.tiktok-minis.us", ago=ago - 2)
        self.look()
        self.look(self.now + 61)
        self.assertEqual(self.zones(), ["tiktok-minis.us"])


class WhatIsNotLearned(Fixture):
    def assertNothingLearned(self):
        self.look()
        self.assertEqual(self.learned(), [])

    def test_without_a_refusal_of_the_app_on_the_same_device(self):
        self.block("tiktok")
        self.lookup("tiktok.com", "GRAVITY", client=OTHER_KID, ago=30)
        self.lookup("tiktok-minis.us", ago=25)
        self.assertNothingLearned()

    def test_when_the_refusal_is_more_than_two_minutes_away(self):
        self.block("tiktok")
        self.lookup("tiktok.com", "GRAVITY", ago=110)
        self.lookup("tiktok-minis.us", ago=-30)                 # 140 seconds later
        self.assertNothingLearned()

    def test_a_refusal_of_another_app_is_no_sign(self):
        self.block("tiktok", "youtube")
        self.lookup("www.youtube.com", "GRAVITY", ago=30)
        self.lookup("tiktok-minis.us", ago=25)
        self.assertNothingLearned()

    def test_when_the_app_is_allowed(self):
        self.lookup("tiktok.com", "GRAVITY", ago=30)            # refused by something else, say a pause
        self.lookup("tiktok-minis.us", ago=25)
        self.assertNothingLearned()

    def test_a_name_a_list_already_blocks(self):
        self.block("tiktok")
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        self.lookup("v16.tiktokcdn.com", ago=25)                # answered from the box's memory before the block
        self.assertNothingLearned()

    def test_a_name_without_the_apps_own_word_even_when_the_model_is_sure(self):
        self.block("chatgpt")
        self.assertGreaterEqual(pb.load_model(MODEL).score("oaistatsig.com")[0], pb.MODEL_THRESHOLD)
        self.lookup("chatgpt.com", "GRAVITY", ago=30)
        self.lookup("oaistatsig.com", ago=25)
        self.assertNothingLearned()

    def test_an_ordinary_name(self):
        self.block("tiktok")
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        for name in ("www.bbc.co.uk", "mail.google.com", "office.com", "cdn.akamaihd.net"):
            self.lookup(name, ago=25)
        self.assertNothingLearned()

    def test_a_name_the_owner_allows(self):
        self.block("tiktok")
        self.api.request("POST", "/api/domains/allow/exact", {"domain": "tiktok-minis.us", "groups": [0], "enabled": True})
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        self.lookup("tiktok-minis.us", ago=25)
        self.assertNothingLearned()

    def test_a_name_that_was_allowed_again(self):
        self.block("tiktok")
        self.api.request("POST", "/api/domains/deny/regex", {"domain": pb.zone_regex("tiktok-minis.us"), "groups": [0],
                                                             "comment": "pb-learned-no:tiktok 2026-01-01", "enabled": False})
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        self.lookup("x.tiktok-minis.us", ago=25)
        self.look()
        self.assertEqual(self.zones(), [])

    def test_when_pihole_hides_the_names(self):
        self.store.privacy = 1
        self.block("tiktok")
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        self.lookup("tiktok-minis.us", ago=25)
        self.assertNothingLearned()

    def test_more_than_the_daily_limit_of_an_app(self):
        self.learner.PER_APP_DAY = 2
        self.block("tiktok")
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        for name in ("tiktok-minis.us", "byteoversea.net", "douyinliving.com"):
            self.lookup(name, ago=25)
        actions = self.look()
        self.assertEqual(len(self.zones()), 2)
        self.assertEqual(sum("not learning more" in a for a in actions), 1)
        self.assertEqual(self.look(self.now + 61), [], "the limit is said once a day")

    def test_more_than_the_limit_of_the_box(self):
        self.learner.MAX_RULES = 1
        self.block("tiktok", "youtube")
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        self.lookup("tiktok-minis.us", ago=25)
        self.lookup("www.youtube.com", "GRAVITY", ago=30)
        self.lookup("youtubetv.com", ago=25)
        self.look()
        self.assertEqual(len(self.zones()), 1)

    def test_without_a_model_nothing_is_learned_and_it_says_why(self):
        learner = pb.Learner(model_file=os.path.join(HERE, "no-such-model.json"), lists_dir=LISTS)
        with self.assertRaises(pb.LearnError):
            learner.run(self.api, self.api.group_map(), self.now)


class TheRules(Fixture):
    def test_a_rule_reads_back_as_its_zone_and_odd_ones_are_not_ours(self):
        for z in ("tiktok-minis.us", "tiktokcdn.com.wsdvs.com", "a_b.example.co.uk"):
            self.assertEqual(pb.regex_zone(pb.zone_regex(z)), z)
        for regex in ("^.*$", r"(^|\.)tiktok\.com$|.*", r"(^|\.)tiktok$", "", None):
            self.assertIsNone(pb.regex_zone(regex))

    def test_remove_takes_the_learned_rules_away(self):
        self.block("tiktok")
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        self.lookup("tiktok-minis.us", ago=25)
        self.look()
        self.assertTrue(self.learned())
        self.ctl.remove()
        self.assertEqual(self.learned(), [])

    def test_setup_leaves_the_learned_rules_alone(self):
        self.block("tiktok")
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        self.lookup("tiktok-minis.us", ago=25)
        self.look()
        self.ctl.setup(run_gravity=False)
        self.assertEqual(self.zones(), ["tiktok-minis.us"])


class TheSwitch(Fixture):
    def maintenance(self, learner):
        clock = {"t": 1000.0}
        m = pb.Maintenance(api=self.api, monotonic=lambda: clock["t"], clock_ok=lambda: True, learner=learner)
        return m, clock

    def test_it_is_off_until_switched_on_and_looks_once_a_minute(self):
        calls = []

        class Fake:
            def run(self, api, groups, epoch):
                calls.append(epoch)
                return []

            def reset(self):
                calls.append("reset")

        m, clock = self.maintenance(Fake())
        self.assertIs(pb.parse_state(self.api.group_map()["pb-state"]["comment"])["learn"]["on"], False)
        m._learn(dt.datetime.now(), self.now)
        self.assertEqual(calls, ["reset"])
        pb.patch_state(self.api, lambda st: st.update(learn={"on": True}))
        m._state = None
        m._learn(dt.datetime.now(), self.now)
        m._learn(dt.datetime.now(), self.now)
        self.assertEqual(calls, ["reset", self.now])
        clock["t"] += pb.Learner.EVERY
        m._learn(dt.datetime.now(), self.now + 60)
        self.assertEqual(calls, ["reset", self.now, self.now + 60])

    def test_a_scheduler_pass_learns_when_it_is_on(self):
        m, _ = self.maintenance(self.learner)
        pb.patch_state(self.api, lambda st: st.update(learn={"on": True}))
        self.block("tiktok")
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        self.lookup("tiktok-minis.us", ago=25)
        with mock.patch.object(m, "_check"), mock.patch.object(m, "_update"), mock.patch.object(m, "_power"), \
                mock.patch.object(m, "_address"), mock.patch.object(m, "_boxinfo"), mock.patch.object(m, "_telemetry"), \
                mock.patch.object(m, "_heal"), mock.patch.object(m, "_page"):
            actions = m.run(dt.datetime.fromtimestamp(self.now))
        self.assertEqual(self.zones(), ["tiktok-minis.us"])
        self.assertTrue(any("tiktok-minis.us" in a for a in actions), actions)


class TheCommand(Fixture):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with open(os.path.join(tmp.name, "pw"), "w") as fh:
            fh.write(mock_pihole.PASSWORD)
        for patch in (mock.patch.dict(os.environ, {"SINKO_API_URL": "http://127.0.0.1:%d" % self.httpd.server_port}),
                      mock.patch.object(pb, "CLI_PW_FILE", os.path.join(tmp.name, "pw")),
                      mock.patch.object(pb, "MODEL_FILE", MODEL)):
            patch.start()
            self.addCleanup(patch.stop)

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pb.main(["learn"] + list(args))
        return code, out.getvalue(), err.getvalue()

    def state(self):
        return pb.parse_state(self.api.group_map()["pb-state"]["comment"])

    def test_on_off_and_status(self):
        code, out, _ = self.cli("status")
        self.assertEqual(code, 0)
        self.assertIn("Learning new addresses of blocked apps: off", out)
        self.assertIn("knows 19 apps", out)
        self.assertEqual(self.cli("on")[0], 0)
        self.assertIs(self.state()["learn"]["on"], True)
        self.assertIn("Switch off: sudo sinko learn off", self.cli("status")[1])
        self.assertEqual(self.cli("off")[0], 0)
        self.assertIs(self.state()["learn"]["on"], False)

    def test_list_and_forget(self):
        self.block("tiktok")
        self.lookup("tiktok.com", "GRAVITY", ago=30)
        self.lookup("tiktok-minis.us", ago=25)
        self.look()
        code, out, _ = self.cli("list")
        self.assertEqual(code, 0)
        self.assertIn("tiktok-minis.us", out)
        code, out, _ = self.cli("forget", "Pull.Tiktok-Minis.us.")
        self.assertEqual(code, 0)
        self.assertIn("Allowed again: tiktok-minis.us (tiktok)", out)
        rule = self.learned()[0]
        self.assertEqual((rule["back"], rule["enabled"]), (True, False))
        self.assertIn("(allowed again)", self.cli("list")[1])
        # and it is not learned again
        self.lookup("tiktok.com", "GRAVITY", ago=-70)
        self.lookup("tiktok-minis.us", ago=-75)
        self.look(self.now + 61)
        self.assertEqual(self.zones(), [])

    def test_forget_needs_a_name_that_was_learned(self):
        self.assertEqual(self.cli("forget")[0], 1)
        self.assertEqual(self.cli("forget", "not a name")[0], 1)
        code, _, err = self.cli("forget", "example.com")
        self.assertEqual(code, 1)
        self.assertIn("no learned address covers example.com", err)


if __name__ == "__main__":
    unittest.main()
