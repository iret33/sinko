"""What Sinko did for the family: the savings ledger in bin/sinko (classify_stops, read_stops, Ledger, Maintenance._ledger) and
the copy the page reads, the group pb-ledger (docs/maintainers/architecture.md, "Savings ledger (pb-ledger)").

Pi-hole's databases are hand-made subsets of the real ones (as in test_diagnostics.py), with and without the list_id that FTL 6
notes for a stopped lookup. The scheduler's side runs against the mock Pi-hole with the maintenance fixture's fakes, so nothing
here reads this machine's Pi-hole or starts anything."""
import datetime as dt
import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

import mock_pihole
import test_diagnostics as td
import test_maintenance as tm

pb = tm.pb
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
SERVICES = {"tiktok", "youtube", "roblox", "instagram"}


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def check_contract(test, text, services=None):
    """Everything the page checks before it shows pb-ledger, checked here so that the box never publishes what the page would
    refuse (architecture.md, "Savings ledger (pb-ledger)"). Returns the data."""
    test.assertIsInstance(text, str)
    test.assertLess(len(text), 4000, "the comment must stay under 4000 characters")
    data = json.loads(text, parse_float=lambda s: test.fail("a number that is not whole: %s" % s))
    test.assertEqual(set(data), {"v", "at", "today", "since", "keptSince", "adLists", "days", "tot"})
    test.assertEqual(data["v"], 1)
    test.assertTrue(is_int(data["at"]) and data["at"] > 0)
    today = data["today"]
    test.assertEqual(today, dt.datetime.fromtimestamp(data["at"]).date().isoformat(), "today is the box-local day of at")
    for key in ("since", "keptSince"):
        test.assertTrue(data[key] is None or (DAY.fullmatch(data[key]) and data[key] <= today), (key, data[key]))
    test.assertTrue(is_int(data["adLists"]) and data["adLists"] >= 0)

    def apps(value):
        test.assertIsInstance(value, dict)
        test.assertLessEqual(len(value), 8)
        for sid, n in value.items():
            test.assertTrue(re.fullmatch(r"[a-z0-9][a-z0-9_-]*", sid) and is_int(n) and n > 0, (sid, n))
            if services is not None:
                test.assertIn(sid, services)
        test.assertEqual(list(value.values()), sorted(value.values(), reverse=True), "biggest first")
    days = data["days"]
    test.assertTrue(1 <= len(days) <= 7)
    test.assertEqual(days[-1]["d"], today, "the last day is today")
    names = [d["d"] for d in days]
    test.assertEqual(names, sorted(set(names)), "oldest first, each day once")
    first = (dt.date.fromisoformat(today) - dt.timedelta(days=6)).isoformat()
    for d in days:
        test.assertEqual(set(d), {"d", "ads", "apps", "offSec", "kept"})
        test.assertGreaterEqual(d["d"], first, "only the last seven days")
        test.assertTrue(d["ads"] is None or (is_int(d["ads"]) and d["ads"] >= 0))
        apps(d["apps"])
        test.assertTrue(d["offSec"] is None or (is_int(d["offSec"]) and 0 <= d["offSec"] <= 25 * 3600), d)
        test.assertIn(d["kept"], (None, 0, 1))
        test.assertFalse(isinstance(d["kept"], bool))
        if data["keptSince"] is None or d["d"] < data["keptSince"]:
            test.assertIsNone(d["offSec"], "no off-time before the scheduler counted it")
            test.assertIsNone(d["kept"])
        if data["since"] is None:
            test.assertIsNone(d["ads"])
    tot = data["tot"]
    test.assertEqual(set(tot), {"ads", "apps", "offSec", "nights", "nightsKept"})
    test.assertEqual(tot["ads"] is None, data["since"] is None)
    test.assertEqual(tot["offSec"] is None, data["keptSince"] is None)
    apps(tot["apps"])
    test.assertTrue(is_int(tot["nights"]) and is_int(tot["nightsKept"]) and 0 <= tot["nightsKept"] <= tot["nights"])
    if tot["ads"] is not None:
        test.assertGreaterEqual(tot["ads"], sum(d["ads"] for d in days if d["ads"] is not None))
    if tot["offSec"] is not None:
        test.assertGreaterEqual(tot["offSec"], sum(d["offSec"] for d in days if d["offSec"] is not None))
    test.assertGreaterEqual(tot["nightsKept"], sum(1 for d in days if d["kept"] == 1))
    return data


# --------------------------------------------------------------------------- Pi-hole's databases, by hand
FTL_SCHEMA_LIST_ID = """
CREATE TABLE query_storage (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER NOT NULL, type INTEGER, status INTEGER,
                            domain INTEGER, client INTEGER, list_id INTEGER);
CREATE INDEX idx_queries_timestamps ON query_storage (timestamp);
CREATE TABLE domain_by_id (id INTEGER PRIMARY KEY, domain TEXT UNIQUE);
CREATE TABLE client_by_id (id INTEGER PRIMARY KEY, ip TEXT UNIQUE, name TEXT);
CREATE VIEW queries AS SELECT q.id, q.timestamp, q.type, q.status, d.domain AS domain, c.ip AS client, q.list_id AS list_id
    FROM query_storage q LEFT JOIN domain_by_id d ON q.domain = d.id LEFT JOIN client_by_id c ON q.client = c.id;
"""
# An FTL that kept its lookups in a plain table called queries (no query_storage), with list_id.
FTL_SCHEMA_TABLE = """
CREATE TABLE queries (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER NOT NULL, type INTEGER, status INTEGER,
                      domain TEXT, client TEXT, list_id INTEGER);
"""

# gravity.db: the ids of the two tables overlap on purpose: the status says which table a list_id is from.
ADLISTS = [  # id, address, enabled, comment, type (0 block, 1 allow)
    (1, "file:///opt/sinko/lists/tiktok.txt", 1, "pb:tiktok", 0),
    (2, "file:///opt/sinko/lists/youtube.txt", 1, "pb:youtube", 0),
    (3, "file:///opt/sinko/lists/guard.txt", 1, "pb:guard", 0),
    (4, "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts", 1, "StevenBlack's Unified Hosts List", 0),
    (5, "file:///opt/sinko/lists/retired.txt", 1, "pb:retired", 0),        # an app a newer release knew (rolled back)
    (6, "https://example.org/old-list.txt", 0, None, 0),                     # switched off: not counted as an ad list
    (7, "https://example.org/allow.txt", 1, "my allow list", 1),             # an allow list is no ad list
    (8, "https://example.org/more-ads.txt", 1, None, 0),                     # no comment: still an ad list
]
RULES = [  # id, type (1 exact deny, 3 regex deny), domain, enabled, comment
    (1, 3, "^.*$", 1, pb.BLOCK_ALL_COMMENT),
    (2, 3, r"(^|\.)tiktokv\.com$", 1, "pb-learned:tiktok 2026-10-01"),
    (3, 3, r"^ads?\.", 1, "my own regex"),
    (4, 1, "example.com", 1, "my own exact rule"),
    (5, 3, r"(^|\.)gone-app\.com$", 1, "pb-learned:retired 2026-10-01"),
]


class Databases:
    """gravity.db and pihole-FTL.db in a folder of their own; `rows` are (when, status, domain, list_id)."""

    def __init__(self, folder):
        self.gdb = os.path.join(folder, "gravity.db")
        self.fdb = os.path.join(folder, "pihole-FTL.db")

    def gravity(self, adlists=ADLISTS, rules=RULES):
        if os.path.exists(self.gdb):
            os.remove(self.gdb)
        con = sqlite3.connect(self.gdb)
        con.executescript(td.GRAVITY_SCHEMA)
        con.executemany("INSERT INTO adlist (id, address, enabled, comment, type) VALUES (?,?,?,?,?)", adlists)
        con.executemany("INSERT INTO domainlist (id, type, domain, enabled, comment) VALUES (?,?,?,?,?)", rules)
        con.commit()
        con.close()

    def ftl(self, rows, schema=FTL_SCHEMA_LIST_ID):
        if os.path.exists(self.fdb):
            os.remove(self.fdb)
        con = sqlite3.connect(self.fdb)
        con.executescript(schema)
        if "query_storage" not in schema:
            con.executemany("INSERT INTO queries (timestamp, type, status, domain, client, list_id) VALUES (?,1,?,?,?,?)",
                            [(int(t), s, d, "192.168.1.21", l) for t, s, d, l in rows])
        else:
            ids = {}
            for t, status, domain, list_id in rows:
                if domain not in ids:
                    ids[domain] = con.execute("INSERT INTO domain_by_id (domain) VALUES (?)", (domain,)).lastrowid
                cols = "timestamp, type, status, domain, client" + (", list_id" if "list_id" in schema.split("VIEW")[0] else "")
                values = (int(t), 1, status, ids[domain], 1) + ((list_id,) if "list_id" in schema.split("VIEW")[0] else ())
                con.execute("INSERT INTO query_storage (%s) VALUES (%s)" % (cols, ",".join("?" * len(values))), values)
        con.commit()
        con.close()


def settings(**values):
    """Stands in for ftl_try: what `pihole-FTL --config <key>` would answer (missing keys: as if it could not be asked)."""
    answers = {"database.maxDBdays": "30", "misc.privacylevel": "0"}
    answers.update({k.replace("__", "."): v for k, v in values.items()})

    def ask(key):
        if key in answers and answers[key] is not None:
            return answers[key], None
        return None, OSError("pihole-FTL is not here")
    return ask


def window(day, whole=False, gap=False, now=None):
    start = pb.day_start(day)
    end = pb.day_start(day + dt.timedelta(days=1)) if whole or now is None else now.timestamp()
    return (day.isoformat(), start, end, whole, gap)


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Databases(tmp.name)
        self.db.gravity()
        env = mock.patch.dict(os.environ, {"SINKO_GRAVITY_DB": self.db.gdb, "SINKO_FTL_DB": self.db.fdb,
                                           "SINKO_SQL_BACKEND": "python"})
        env.start()
        self.addCleanup(env.stop)
        self.now = dt.datetime(2026, 10, 21, 15, 0)
        self.today = self.now.date()

    def at(self, days_ago=0, hour=10, minute=0):
        return dt.datetime.combine(self.today - dt.timedelta(days=days_ago), dt.time(hour, minute)).timestamp()

    def read(self, windows=None, setting=None, **kw):
        return pb.read_stops(windows or [window(self.today, now=self.now)], SERVICES, setting=setting or settings(), **kw)


# --------------------------------------------------------------------------- what stopped a lookup
class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.adlists = {i: c or "" for i, _a, _e, c, _t in ADLISTS}
        self.rules = {i: c for i, _t, _d, _e, c in RULES}

    def source(self, status, list_id):
        return pb.stop_source(status, list_id, self.adlists, self.rules, SERVICES)

    def test_each_source_by_its_list_id(self):
        self.assertEqual(self.source(1, 1), ("app", "tiktok"), "the family's app list")
        self.assertEqual(self.source(9, 2), ("app", "youtube"), "also through a CNAME")
        self.assertEqual(self.source(1, 3), ("guard", None), "the guard list is not an ad list")
        self.assertEqual(self.source(1, 4), ("ads", None), "a general list")
        self.assertEqual(self.source(1, 8), ("ads", None), "a general list without a comment")
        self.assertEqual(self.source(4, 1), ("off", None), "the block-everything rule: internet off, not an ad")
        self.assertEqual(self.source(10, 2), ("app", "tiktok"), "a rule the box learned for an app")
        self.assertEqual(self.source(4, 3), ("own", None), "the owner's own regex")
        self.assertEqual(self.source(5, 4), ("own", None), "the owner's exact rule")
        self.assertEqual(self.source(11, 4), ("own", None))

    def test_the_status_says_which_table_the_id_is_from(self):
        self.assertEqual(self.source(1, 1), ("app", "tiktok"))           # adlist 1
        self.assertEqual(self.source(4, 1), ("off", None))               # domainlist 1

    def test_what_cannot_be_told_is_never_an_ad(self):
        self.assertEqual(self.source(1, 5), ("other", None), "the list of an app this release does not know")
        self.assertEqual(self.source(4, 5), ("own", None), "a rule learned for such an app")
        self.assertEqual(self.source(1, 99), ("other", None), "a list deleted since")
        self.assertEqual(self.source(1, None), ("other", None))
        self.assertEqual(self.source(4, 99), ("other", None))
        for status in (6, 7, 8, 18):
            self.assertEqual(self.source(status, None), ("upstream", None), "the upstream service refused it")
        for status in (0, 2, 3, 12, 15, 16, 17):
            self.assertEqual(self.source(status, 4)[0], "other", status)

    def test_classify_adds_up_and_skips_rows_that_make_no_sense(self):
        rows = [{"status": 1, "list_id": 4, "n": 100}, {"status": 9, "list_id": 4, "n": 5}, {"status": 1, "list_id": 1, "n": 7},
                {"status": 10, "list_id": 2, "n": 3}, {"status": 4, "list_id": 1, "n": 40}, {"status": 6, "list_id": None, "n": 2},
                {"status": 1, "list_id": 3, "n": 9}, {"status": 5, "list_id": 4, "n": 1},
                {"status": 1, "list_id": 4, "n": 0}, {"status": 1, "list_id": 4, "n": "5"}, {"status": None, "list_id": 4, "n": 5},
                {"status": 1, "list_id": 4, "n": True}]
        got = pb.classify_stops(rows, self.adlists, self.rules, SERVICES)
        self.assertEqual(got, {"ads": 105, "apps": {"tiktok": 10}, "off": 40, "guard": 9, "own": 1, "upstream": 2, "other": 0})

    def test_by_name_when_ftl_keeps_no_list_ids(self):
        names = pb.stop_names(SERVICES, [{"id": i, "type": t, "domain": d, "enabled": e, "comment": c} for i, t, d, e, c in RULES],
                              tm.LISTS)
        by = lambda status, name: pb.stop_by_name(status, name, names, SERVICES)
        self.assertEqual(by(1, "www.tiktok.com"), ("app", "tiktok"), "a name under an app's list")
        self.assertEqual(by(1, "dns.google"), ("guard", None))
        self.assertEqual(by(1, "ads.doubleclick.net"), ("ads", None))
        self.assertEqual(by(1, "www.instagram.com"), ("app", "instagram"))
        self.assertEqual(by(1, "www.netflix.com"), ("ads", None), "an app the box does not count is someone's ad list")
        self.assertEqual(by(4, "api.tiktokv.com"), ("app", "tiktok"), "under a zone the box learned")
        self.assertEqual(by(4, "www.example.org"), ("other", None), "the block-everything rule or the owner's: cannot be told")
        self.assertEqual(by(1, "hidden"), ("other", None))
        self.assertEqual(by(1, None), ("other", None))
        self.assertEqual(by(7, "x.example"), ("upstream", None))


# --------------------------------------------------------------------------- reading Pi-hole's database
class ReadStopsTests(DatabaseCase):
    def rows_today(self):
        return [(self.at(0, 9), 1, "ads.doubleclick.net", 4), (self.at(0, 9), 1, "ads.doubleclick.net", 4),
                (self.at(0, 10), 1, "www.tiktok.com", 1), (self.at(0, 11), 9, "www.youtube.com", 2),
                (self.at(0, 11), 4, "www.example.org", 1), (self.at(0, 12), 10, "api.tiktokv.com", 2),
                (self.at(0, 12), 1, "dns.google", 3), (self.at(0, 13), 6, "blocked.example", None),
                (self.at(0, 13), 2, "www.apple.com", None),                         # answered: not a stop
                (self.at(1, 23, 59), 1, "ads.doubleclick.net", 4),                 # yesterday
                (self.at(0, 15, 1), 1, "ads.doubleclick.net", 4)]                  # after "now": not yet

    def test_list_ids_are_used_when_the_database_has_them(self):
        self.db.ftl(self.rows_today())
        got = self.read()
        self.assertIsNone(got["why"])
        self.assertEqual(got["days"], {self.today.isoformat(): {"ads": 2, "apps": {"tiktok": 2, "youtube": 1}, "whole": False}})
        self.assertEqual(got["adLists"], 2, "switched-on block lists that are not Sinko's (StevenBlack and the one without a comment)")

    def test_a_plain_queries_table_with_list_ids_is_enough(self):
        self.db.ftl(self.rows_today(), schema=FTL_SCHEMA_TABLE)
        self.assertEqual(self.read()["days"][self.today.isoformat()]["apps"], {"tiktok": 2, "youtube": 1})

    def test_without_list_ids_the_names_decide(self):
        rows = [(t, s, d, None) for t, s, d, _l in self.rows_today()]
        self.db.ftl(rows, schema=td.FTL_SCHEMA)
        got = self.read(lists_dir=tm.LISTS)
        self.assertIsNone(got["why"])
        self.assertEqual(got["days"][self.today.isoformat()], {"ads": 2, "apps": {"tiktok": 2, "youtube": 1}, "whole": False},
                         "the guard name is not an ad, the regex stop of a name under no learned zone is not counted")

    def test_without_list_ids_a_privacy_level_that_hides_names_is_not_known(self):
        self.db.ftl([(t, s, d, None) for t, s, d, _l in self.rows_today()], schema=td.FTL_SCHEMA)
        for level in ("1", "2"):
            got = self.read(setting=settings(misc__privacylevel=level))
            self.assertEqual(got["days"][self.today.isoformat()], {"ads": None, "apps": None, "whole": False}, level)
            self.assertIn("privacy level", got["why"])

    def test_hidden_names_in_the_rows_are_not_known_either(self):
        self.db.ftl([(t, s, "hidden", None) for t, s, _d, _l in self.rows_today()], schema=td.FTL_SCHEMA)
        got = self.read()
        self.assertEqual(got["days"][self.today.isoformat()]["ads"], None)

    def test_with_list_ids_privacy_levels_one_and_two_still_count_and_three_keeps_nothing(self):
        self.db.ftl(self.rows_today())
        for level in ("1", "2"):
            self.assertEqual(self.read(setting=settings(misc__privacylevel=level))["days"][self.today.isoformat()]["ads"], 2)
        got = self.read(setting=settings(misc__privacylevel="3"))
        self.assertEqual(got["days"][self.today.isoformat()], {"ads": None, "apps": None, "whole": False})
        self.assertEqual(got["adLists"], 2, "the lists are still known")

    def test_a_database_that_is_off_is_not_known_never_zero(self):
        self.db.ftl(self.rows_today())
        got = self.read(setting=settings(database__maxDBdays="0"))
        self.assertEqual(got["days"][self.today.isoformat()]["ads"], None)
        self.assertIn("maxDBdays", got["why"])
        with mock.patch.dict(os.environ):
            del os.environ["SINKO_FTL_DB"]
            got = self.read(setting=settings(files__database=""))
        self.assertEqual(got["days"][self.today.isoformat()]["ads"], None)
        self.assertIn("files.database", got["why"])

    def test_the_database_pihole_names_is_the_one_read(self):
        self.db.ftl(self.rows_today())
        with mock.patch.dict(os.environ):
            del os.environ["SINKO_FTL_DB"]
            got = self.read(setting=settings(files__database=self.db.fdb + "\n"))
        self.assertEqual(got["days"][self.today.isoformat()]["ads"], 2)

    def test_unreadable_databases_are_not_known_and_nothing_raises(self):
        got = self.read()                                       # no pihole-FTL.db at all
        self.assertEqual(got["days"][self.today.isoformat()]["ads"], None)
        self.assertIn("cannot be read", got["why"])
        self.assertEqual(got["adLists"], 2)
        os.remove(self.db.gdb)
        self.db.ftl(self.rows_today())
        got = self.read()
        self.assertEqual((got["days"][self.today.isoformat()]["ads"], got["adLists"]), (None, None))
        self.assertIn("gravity.db", got["why"])
        with open(self.db.fdb, "w") as fh:
            fh.write("not a database")
        self.db.gravity()
        self.assertIsNone(self.read()["days"][self.today.isoformat()]["ads"])

    def test_only_whole_numbers_reach_the_sql(self):
        seen = []

        def sql(db, text):
            seen.append(text)
            return pb.sql_rows(db, text)
        self.db.ftl(self.rows_today())
        odd = (self.today.isoformat(), pb.day_start(self.today) + 0.75, self.now.timestamp() + 0.5, False, False)
        self.read(windows=[odd], sql=sql)
        counts = [s for s in seen if "COUNT(*)" in s]
        self.assertEqual(len(counts), 1)
        self.assertNotIn("'", "".join(seen), "no text is put into the SQL")
        self.assertRegex(counts[0], r"timestamp >= \d+ AND timestamp < \d+ AND status IN \(1,4,5,6,7,8,9,10,11,15,16,18\)")

    def test_a_locked_database_is_asked_again(self):
        self.db.ftl(self.rows_today())
        calls = []

        def sql(db, text):
            calls.append(text)
            if "COUNT(*)" in text and len([c for c in calls if "COUNT(*)" in c]) == 1:
                raise pb.SqlError("database is locked")
            return pb.sql_rows(db, text)
        with mock.patch.object(pb.time, "sleep") as slept:
            got = self.read(sql=sql)
        self.assertEqual(got["days"][self.today.isoformat()]["ads"], 2)
        slept.assert_called_once()

    def test_a_gap_is_counted_only_when_the_database_holds_the_whole_day(self):
        self.db.ftl([(self.at(2, 0, 30), 1, "ads.doubleclick.net", 4), (self.at(1, 8), 1, "ads.doubleclick.net", 4),
                     (self.at(0, 9), 1, "ads.doubleclick.net", 4)])
        days = [self.today - dt.timedelta(days=n) for n in (3, 2, 1)]
        got = self.read(windows=[window(d, whole=True, gap=True) for d in days] + [window(self.today, now=self.now)])
        self.assertEqual(sorted(got["days"]), [days[2].isoformat(), self.today.isoformat()],
                         "two days ago the database began at 00:30: that day is not whole, and a gap stays a gap")
        self.assertEqual(got["days"][days[2].isoformat()], {"ads": 1, "apps": {}, "whole": True})


# --------------------------------------------------------------------------- the ledger itself
class LedgerCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        env = mock.patch.dict(os.environ, {"SINKO_STATE_DIR": os.path.join(self.tmp, "state")})
        env.start()
        self.addCleanup(env.stop)
        self.ledger = pb.Ledger()
        self.now = dt.datetime(2026, 10, 21, 15, 0)
        self.today = self.now.date()

    def day(self, back):
        return (self.today - dt.timedelta(days=back)).isoformat()

    def result(self, counts, whole=(), lists=1):
        """read_stops' answer: {days_back: ads or None}, apps from the number."""
        days = {}
        for back, ads in counts.items():
            days[self.day(back)] = {"ads": ads, "apps": None if ads is None else {"tiktok": ads // 100}, "whole": back in whole}
        return {"days": days, "adLists": lists, "why": None}

    def payload(self, now=None):
        return self.ledger.payload(now or self.now, SERVICES, 1)

    def saved(self):
        with open(pb.state_path(pb.SAVINGS_FILE)) as fh:
            return json.load(fh)


class DaysTests(LedgerCase):
    def test_today_is_always_read_and_yesterday_only_five_minutes_after_midnight(self):
        self.ledger.merge(self.result({0: 100}), self.now)
        self.ledger.load()["since"] = self.day(0)
        early = dt.datetime.combine(self.today + dt.timedelta(days=1), dt.time(0, 3))
        self.assertEqual([w[0] for w in self.ledger.windows(early)], [early.date().isoformat()],
                         "FTL may not have written the last minutes of yesterday yet")
        later = early + dt.timedelta(minutes=3)
        got = self.ledger.windows(later)
        self.assertEqual([(w[0], w[3], w[4]) for w in got], [(later.date().isoformat(), False, False), (self.day(0), True, False)])
        self.assertEqual((got[1][1], got[1][2]), (pb.day_start(self.today), pb.day_start(self.today + dt.timedelta(days=1))))

    def test_a_day_read_whole_after_it_ended_is_final(self):
        self.ledger.merge(self.result({1: 500}), self.now)
        self.ledger.merge(self.result({1: 900}, whole={1}), self.now)
        self.assertTrue(self.ledger.load()["days"][self.day(1)]["final"])
        self.ledger.merge(self.result({1: 5000}, whole={1}), self.now)
        self.assertEqual(self.ledger.load()["days"][self.day(1)]["ads"], 900, "a final day never changes")
        self.assertNotIn(self.day(1), [w[0] for w in self.ledger.windows(self.now)], "and it is not read again")

    def test_a_smaller_count_keeps_what_was_counted(self):
        self.ledger.merge(self.result({0: 800}), self.now)
        self.ledger.merge(self.result({0: 10}), self.now)        # Pi-hole's history was flushed
        self.assertEqual(self.ledger.load()["days"][self.day(0)]["ads"], 800)

    def test_not_known_never_overwrites_a_count_and_never_makes_a_day(self):
        self.ledger.merge(self.result({0: 800}), self.now)
        self.ledger.merge(self.result({0: None, 3: None}), self.now)
        days = self.ledger.load()["days"]
        self.assertEqual(days[self.day(0)]["ads"], 800)
        self.assertNotIn(self.day(3), days)

    def test_since_is_the_earliest_day_counted(self):
        self.ledger.merge(self.result({0: 1}), self.now)
        self.assertEqual(self.ledger.load()["since"], self.day(0))
        self.ledger.merge(self.result({4: 1}, whole={4}), self.now)
        self.assertEqual(self.ledger.load()["since"], self.day(4))
        self.ledger.merge(self.result({2: 1}, whole={2}), self.now)
        self.assertEqual(self.ledger.load()["since"], self.day(4))

    def test_a_day_too_old_to_be_read_whole_again_is_final_as_it_is(self):
        self.ledger.merge(self.result({8: 50, 7: 60}), self.now)
        days = self.ledger.load()["days"]
        self.assertTrue(days[self.day(8)]["final"])
        self.assertFalse(days[self.day(7)]["final"])
        self.assertIn(self.day(7), [w[0] for w in self.ledger.windows(self.now)])

    def test_the_thirty_five_day_fold_keeps_the_totals(self):
        data = self.ledger.load()
        data["keptSince"] = self.day(40)
        for back in range(40, -1, -1):
            data["days"][self.day(back)] = {"ads": 1000 + back, "apps": {"tiktok": 3, "youtube": back}, "final": back > 0,
                                            "off": 3600.0, "seen": 86400.0, "kept": 1 if back % 3 else 0}
        data["since"] = self.day(40)
        before = self.payload()["tot"]
        self.ledger.fold(self.today)
        self.assertEqual(sorted(data["days"])[0], self.day(34), "35 days are kept, today included")
        self.assertEqual(len(data["days"]), 35)
        self.assertEqual(self.payload()["tot"], before, "the totals survive the fold")
        self.assertEqual(data["before"]["ads"], sum(1000 + b for b in range(35, 41)))
        self.assertEqual(data["before"]["nights"], 6)
        self.assertEqual(before["ads"], sum(1000 + b for b in range(41)))
        self.assertEqual(before["offSec"], 41 * 3600)
        self.assertEqual((before["nights"], before["nightsKept"]), (41, sum(1 for b in range(41) if b % 3)))
        self.assertEqual(before["apps"], {"youtube": sum(range(41)), "tiktok": 41 * 3})

    def test_the_week_has_gaps_and_ends_today(self):
        self.ledger.merge(self.result({5: 10, 2: 20}, whole={5, 2}), self.now)
        days = self.payload()["days"]
        self.assertEqual([d["d"] for d in days], [self.day(5), self.day(2), self.day(0)])
        self.assertEqual(days[-1], {"d": self.day(0), "ads": None, "apps": {}, "offSec": None, "kept": None})

    def test_only_apps_of_the_catalog_at_most_eight_biggest_first(self):
        apps = {"tiktok": 5, "youtube": 9, "roblox": 9, "instagram": 1, "netflix": 50}
        self.ledger.merge({"days": {self.day(0): {"ads": 1, "apps": apps, "whole": False}}}, self.now)
        self.assertEqual(list(self.payload()["days"][-1]["apps"].items()), [("roblox", 9), ("youtube", 9), ("tiktok", 5), ("instagram", 1)])
        many = {"app%02d" % i: i + 1 for i in range(20)}
        self.ledger.merge({"days": {self.day(0): {"ads": 2, "apps": many, "whole": False}}}, self.now)
        got = self.ledger.payload(self.now, set(many), 1)["days"][-1]["apps"]
        self.assertEqual(list(got), ["app%02d" % i for i in range(19, 11, -1)])


class BackfillTests(DatabaseCase):
    def ledger(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return pb.Ledger(os.path.join(tmp.name, "savings.json"))

    def fill(self, first_days_ago):
        rows = []
        for back in range(first_days_ago, -1, -1):
            for hour in (0, 12, 14):
                rows.append((self.at(back, hour, 30 if back == first_days_ago else 0), 1, "ads.doubleclick.net", 4))
            rows.append((self.at(back, 13), 1, "www.tiktok.com", 1))
        self.db.ftl(rows)

    def test_the_first_run_fills_the_week_from_what_the_database_holds(self):
        self.fill(20)
        ledger = self.ledger()
        ledger.merge(self.read(windows=ledger.windows(self.now)), self.now)
        payload = ledger.payload(self.now, SERVICES, 1)
        self.assertEqual([d["d"] for d in payload["days"]], [(self.today - dt.timedelta(days=b)).isoformat() for b in range(6, -1, -1)])
        self.assertEqual([d["ads"] for d in payload["days"]], [3] * 7)
        self.assertEqual(payload["since"], (self.today - dt.timedelta(days=6)).isoformat())
        self.assertTrue(all(ledger.load()["days"][d["d"]]["final"] for d in payload["days"][:-1]))
        self.assertIsNone(payload["keptSince"], "the time off was not watched on those days")
        check_contract(self, pb.ledger_text(payload), SERVICES)

    def test_a_day_the_database_does_not_hold_whole_stays_a_gap(self):
        self.fill(3)                                             # began at 00:30 three days ago
        ledger = self.ledger()
        ledger.merge(self.read(windows=ledger.windows(self.now)), self.now)
        self.assertEqual(sorted(ledger.load()["days"]), [(self.today - dt.timedelta(days=b)).isoformat() for b in (2, 1, 0)])

    def test_there_is_no_backfill_once_something_was_counted(self):
        self.fill(20)
        ledger = self.ledger()
        ledger.merge(self.read(windows=[window(self.today, now=self.now)]), self.now)
        self.assertEqual([w[0] for w in ledger.windows(self.now)], [self.today.isoformat()])


class OffTimeTests(LedgerCase):
    SCHED = {"enabled": True, "start": "21:00", "end": "06:00", "days": [0, 1, 2, 3, 4, 5, 6]}

    def run_passes(self, start, seconds, every=15, offline=lambda t: False, kids=True, active=None, mono=0.0):
        """Passes of the scheduler from `start` for `seconds`, every `every` seconds. Returns what observe() said."""
        events = []
        t = 0
        while t <= seconds:
            at = start + dt.timedelta(seconds=t)
            on = pb.in_schedule(self.SCHED, at) if active is None else active(at)
            events.append(self.ledger.observe(at, mono + t, offline(at), kids, on, self.SCHED))
            t += every
        return events

    def row(self, day):
        return self.ledger.load()["days"][day.isoformat()]

    def test_off_time_counts_only_while_pb_offline_is_on_and_a_child_device_exists(self):
        start = dt.datetime(2026, 10, 21, 15, 0)
        self.run_passes(start, 3600, offline=lambda t: t.hour == 15 and t.minute < 30)
        self.assertAlmostEqual(self.row(start.date())["off"], 1800, delta=15)
        self.assertAlmostEqual(self.row(start.date())["seen"], 3600, delta=15)
        self.ledger = pb.Ledger.in_memory()
        self.run_passes(start, 3600, offline=lambda t: True, kids=False)
        self.assertEqual(self.row(start.date())["off"], 0, "with no child's device, nobody's internet was off")

    def test_a_long_gap_counts_at_most_two_minutes(self):
        start = dt.datetime(2026, 10, 21, 15, 0)
        self.ledger.observe(start, 0, True, True, False, self.SCHED)
        self.ledger.observe(start + dt.timedelta(hours=3), 3 * 3600, True, True, False, self.SCHED)
        self.assertEqual(self.row(start.date())["off"], pb.LEDGER_STEP_MAX)
        self.ledger.observe(start + dt.timedelta(hours=3, seconds=15), 3 * 3600 + 15, True, True, False, self.SCHED)
        self.assertEqual(self.row(start.date())["off"], pb.LEDGER_STEP_MAX + 15)

    def test_the_first_pass_counts_nothing_and_sets_kept_since(self):
        start = dt.datetime(2026, 10, 21, 15, 0)
        self.ledger.observe(start, 5000, True, True, False, self.SCHED)
        self.assertEqual(self.row(start.date())["off"], 0)
        self.assertEqual(self.ledger.load()["keptSince"], "2026-10-21")

    def test_a_step_across_midnight_is_shared_by_the_two_days(self):
        late = dt.datetime(2026, 10, 21, 23, 59, 30)
        self.ledger.observe(late, 0, True, True, False, self.SCHED)
        self.ledger.observe(late + dt.timedelta(seconds=60), 60, True, True, False, self.SCHED)
        self.assertEqual(self.row(late.date())["off"], 30)
        self.assertEqual(self.row(late.date() + dt.timedelta(days=1))["off"], 30)

    def test_a_kept_night_crossing_midnight_belongs_to_the_day_it_started(self):
        start = dt.datetime(2026, 10, 21, 20, 0)
        events = self.run_passes(start, 11 * 3600, offline=lambda t: pb.in_schedule(self.SCHED, t))
        self.assertEqual(self.row(start.date())["kept"], 1)
        self.assertIsNone(self.row(start.date() + dt.timedelta(days=1))["kept"])
        self.assertIsNone(self.ledger.load()["night"])
        self.assertTrue(any(events), "the end of the night is news for the page")
        self.assertAlmostEqual(self.row(start.date())["off"], 3 * 3600, delta=30)
        self.assertAlmostEqual(self.row(start.date() + dt.timedelta(days=1))["off"], 6 * 3600, delta=30)

    def test_a_night_with_the_internet_switched_back_on_was_not_kept(self):
        start = dt.datetime(2026, 10, 21, 20, 0)
        self.run_passes(start, 11 * 3600, offline=lambda t: pb.in_schedule(self.SCHED, t) and t.hour >= 21 and t.hour < 23)
        self.assertEqual(self.row(start.date())["kept"], 0)

    def test_a_night_the_scheduler_saw_too_little_of_is_not_known(self):
        start = dt.datetime(2026, 10, 21, 20, 0)
        self.run_passes(start, 2 * 3600, offline=lambda t: pb.in_schedule(self.SCHED, t))
        off = dt.datetime(2026, 10, 22, 4, 0)                    # the box was off from 22:00 to 04:00
        self.ledger._last = None                                 # a new process: it does not know what happened meanwhile
        self.run_passes(off, 3 * 3600, offline=lambda t: pb.in_schedule(self.SCHED, t), mono=99999)
        self.assertIsNone(self.row(start.date())["kept"])
        self.assertIsNone(self.ledger.load()["night"])

    def test_a_night_with_no_child_device_is_not_counted(self):
        start = dt.datetime(2026, 10, 21, 20, 0)
        self.run_passes(start, 11 * 3600, offline=lambda t: pb.in_schedule(self.SCHED, t), kids=False)
        self.assertIsNone(self.row(start.date())["kept"])

    def test_an_open_night_survives_a_restart(self):
        start = dt.datetime(2026, 10, 21, 20, 0)
        self.run_passes(start, 4 * 3600, offline=lambda t: pb.in_schedule(self.SCHED, t))
        self.ledger.save()
        self.assertEqual(self.saved()["night"]["d"], "2026-10-21")
        self.ledger = pb.Ledger()                                # the scheduler started again a minute later
        self.run_passes(start + dt.timedelta(hours=4, minutes=1), 7 * 3600, offline=lambda t: pb.in_schedule(self.SCHED, t), mono=50000)
        self.assertEqual(self.row(start.date())["kept"], 1)

    def test_the_page_sees_off_time_only_from_kept_since_and_the_nights_in_the_totals(self):
        self.ledger.merge(self.result({3: 100, 2: 100, 1: 100}, whole={3, 2, 1}), self.now)    # the first run's backfill
        start = dt.datetime.combine(self.today - dt.timedelta(days=1), dt.time(20, 0))
        self.run_passes(start, 20 * 3600, every=60, offline=lambda t: pb.in_schedule(self.SCHED, t))
        p = self.payload(dt.datetime.combine(self.today, dt.time(16, 0)))
        by_day = {d["d"]: d for d in p["days"]}
        self.assertIsNone(by_day[self.day(3)]["offSec"])
        self.assertIsNone(by_day[self.day(2)]["offSec"])
        self.assertEqual(p["keptSince"], self.day(1))
        self.assertEqual(by_day[self.day(1)]["kept"], 1)
        self.assertEqual((p["tot"]["nights"], p["tot"]["nightsKept"]), (1, 1))
        self.assertEqual(p["tot"]["offSec"], by_day[self.day(1)]["offSec"] + by_day[self.day(0)]["offSec"])
        check_contract(self, pb.ledger_text(p), SERVICES)


class SavingsFileTests(LedgerCase):
    def write(self, text):
        os.makedirs(os.path.dirname(pb.state_path(pb.SAVINGS_FILE)), exist_ok=True)
        with open(pb.state_path(pb.SAVINGS_FILE), "w") as fh:
            fh.write(text)

    def test_it_is_private_and_reads_back_what_was_written(self):
        self.ledger.merge(self.result({1: 1234}, whole={1}), self.now)
        self.ledger.observe(self.now, 0, True, True, False, OffTimeTests.SCHED)
        self.ledger.observe(self.now + dt.timedelta(seconds=15), 15, True, True, False, OffTimeTests.SCHED)
        self.ledger.save()
        self.assertEqual(os.stat(pb.state_path(pb.SAVINGS_FILE)).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.dirname(pb.state_path(pb.SAVINGS_FILE))).st_mode & 0o777, 0o700)
        again = pb.Ledger()
        self.assertEqual(again.payload(self.now + dt.timedelta(seconds=15), SERVICES, 1),
                         self.ledger.payload(self.now + dt.timedelta(seconds=15), SERVICES, 1))
        self.assertFalse(again.dirty)
        self.assertEqual(self.saved()["v"], 1)

    def test_a_corrupt_or_foreign_file_is_replaced(self):
        for text in ("{not json", "[1, 2]", json.dumps({"v": 2, "days": {}}), json.dumps({"v": 1, "days": []}), "9" * 5000):
            self.write(text)
            ledger = pb.Ledger()
            with self.assertLogs("sinko", level="WARNING"):
                data = ledger.load()
            self.assertEqual(data["days"], {})
            self.assertTrue(ledger.dirty, "so that the next save replaces it")
            ledger.save()
            self.assertEqual(self.saved()["v"], 1)

    def test_a_field_that_makes_no_sense_loses_only_itself(self):
        good = {"ads": 5, "apps": {"tiktok": 2, "BAD ID": 3, "youtube": -1, "roblox": True}, "final": True, "off": 60, "seen": 60,
                "kept": 1}
        self.write(json.dumps({"v": 1, "since": "2026-13-01", "keptSince": "2026-10-01", "adLists": "1", "night": {"d": "x"},
                               "days": {"2026-10-20": good, "2026-02-30": good, "yesterday": good,
                                        "2026-10-19": {"ads": 1.5, "apps": {"tiktok": 1}, "kept": True, "off": "x", "seen": None}},
                               "before": {"ads": 10 ** 13, "nights": 3, "kept": 2, "apps": [], "off": -5}}))
        data = pb.Ledger().load()
        self.assertEqual(sorted(data["days"]), ["2026-10-19", "2026-10-20"])
        self.assertEqual(data["days"]["2026-10-20"]["apps"], {"tiktok": 2})
        self.assertEqual(data["days"]["2026-10-19"], {"ads": None, "apps": None, "final": False, "off": 0.0, "seen": 0.0, "kept": None})
        self.assertEqual((data["since"], data["keptSince"], data["adLists"], data["night"]), (None, "2026-10-01", None, None))
        self.assertEqual(data["before"], {"ads": 0, "apps": {}, "off": 0.0, "nights": 3, "kept": 2})


# --------------------------------------------------------------------------- the scheduler's side and the page's copy
class PublishFixture(tm.Fixture):
    """The maintenance fixture with the ledger switched on: read_stops is a fake that answers `self.stops`."""

    def setUp(self):
        super().setUp()
        self.now = dt.datetime(2026, 10, 21, 15, 0)
        self.stops = {"ads": 1200, "apps": {"tiktok": 30, "youtube": 4}}
        self.stop_calls = []
        self.ledger_writes = []
        for name in ("add_group", "put_group"):
            real = getattr(self.api, name)
            setattr(self.api, name, self.recorder(real))
        self.lm = self.maintenance()

    def recorder(self, real):
        def call(group, comment, enabled, *a, **k):
            if group == pb.G_LEDGER:
                self.ledger_writes.append((comment, enabled))
            return real(group, comment, enabled, *a, **k)
        return call

    def maintenance(self, job_factory=tm.InlineJob, stops=None):
        return pb.Maintenance(self.api, config_path=self.config_path, monotonic=lambda: self.mono, job_factory=job_factory,
                              clock_ok=lambda: self.clock_trusted, check=lambda conf: None, default_ip=lambda: self.ip,
                              box_info=self.fake_box_info, catalog=lambda: self.catalog, ledger=pb.Ledger(),
                              stops=stops or self.fake_stops)

    def fake_stops(self, windows, services):
        self.stop_calls.append((windows, services))
        days = {day: dict(self.stops, whole=whole) for day, _s, _e, whole, gap in windows if not gap}
        return {"days": days, "adLists": 1, "why": None}

    def lpass(self, m=None):
        return (m or self.lm).run(self.now)

    def published(self):
        group = next((g for g in self.store.groups if g["name"] == pb.G_LEDGER), None)
        return None if group is None else json.loads(group["comment"])

    def add_kid(self):
        gid = {g["name"]: g["id"] for g in self.store.groups}
        self.api.request("POST", "/api/clients", {"client": "AA:BB:CC:00:00:01", "comment": "Sara", "groups": pb.kid_groups(gid, self.catalog)})

    def internet_off(self, off):
        self.api.put_group(pb.G_OFFLINE, "", off)


class PublishTests(PublishFixture):
    def test_the_first_copy_waits_for_the_first_counts_and_is_a_disabled_group(self):
        self.lpass()
        self.assertEqual(len(self.stop_calls), 1, "the stops are read right after the start")
        self.assertIsNone(self.published(), "not before the first counts are in")
        self.advance(15)
        self.lpass()
        group = next(g for g in self.store.groups if g["name"] == pb.G_LEDGER)
        self.assertFalse(group["enabled"])
        data = check_contract(self, group["comment"], {s["id"] for s in self.catalog["services"]})
        self.assertEqual(data["days"][-1]["ads"], 1200)
        self.assertEqual(data["tot"]["apps"], {"tiktok": 30, "youtube": 4})
        self.assertEqual(data["adLists"], 1)
        self.assertEqual(len(self.ledger_writes), 1)
        self.assertFalse(any(c.get("client") for c in self.store.clients if group["id"] in c.get("groups", [])),
                         "no client is ever in it")

    def test_not_more_often_than_once_an_hour(self):
        self.lpass()
        self.advance(15)
        self.lpass()
        self.add_kid()
        self.internet_off(True)
        for _ in range(int(59 * 60 / 15)):
            self.advance(15)
            self.lpass()
        self.assertEqual(len(self.ledger_writes), 1, "the off-time grew, but the hour is not over")
        for _ in range(8):
            self.advance(15)
            self.lpass()
        self.assertEqual(len(self.ledger_writes), 2)
        self.assertGreater(self.published()["days"][-1]["offSec"], 3500)

    def test_the_stops_are_read_every_fifteen_minutes_and_savings_json_with_them(self):
        self.lpass()
        self.assertFalse(os.path.exists(pb.state_path(pb.SAVINGS_FILE)))
        self.advance(15)
        self.lpass()
        self.assertTrue(os.path.exists(pb.state_path(pb.SAVINGS_FILE)), "written with each read of the stops")
        for _ in range(int(30 * 60 / 15)):
            self.advance(15)
            self.lpass()
        self.assertEqual(len(self.stop_calls), 3, "at the start, after 15 and after 30 minutes")

    def test_nothing_new_is_not_written_again(self):
        self.lpass()
        self.advance(15)
        self.lpass()
        for _ in range(3):
            self.advance(3600)
            self.lpass()
        self.assertEqual(len(self.ledger_writes), 1, "every group write makes Pi-hole reload its lists")

    def test_a_new_day_is_published_at_once(self):
        self.now = dt.datetime(2026, 10, 21, 23, 50)
        self.lpass()
        self.advance(15)
        self.lpass()
        self.assertEqual(len(self.ledger_writes), 1)
        self.advance(15 * 60)
        self.lpass()
        self.assertEqual(len(self.ledger_writes), 2)
        self.assertEqual(self.published()["today"], "2026-10-22")

    def test_the_end_of_an_off_period_and_of_a_bedtime_night_are_published_at_once(self):
        self.add_kid()
        self.lpass()
        self.advance(15)
        self.lpass()
        self.internet_off(True)
        for _ in range(8):
            self.advance(15)
            self.lpass()
        self.assertEqual(len(self.ledger_writes), 1)
        self.internet_off(False)
        self.advance(15)
        self.lpass()
        self.assertEqual(len(self.ledger_writes), 2, "the internet came back: the page hears of it now")
        self.set_state(lambda s: s.update(scheduleActive=True, schedule={"enabled": True, "start": "15:00", "end": "16:00",
                                                                        "days": [0, 1, 2, 3, 4, 5, 6]}))
        self.internet_off(True)
        for _ in range(4):
            self.advance(15)
            self.lpass()
        self.set_state(lambda s: s.update(scheduleActive=False))      # bedtime is over; the internet stays off by hand
        self.advance(15)
        self.lpass()
        self.assertEqual(len(self.ledger_writes), 3, "a bedtime night that ended is news too")

    def test_a_restored_backup_is_put_right_at_the_next_moment_and_at_once_after_a_start(self):
        self.lpass()
        self.advance(15)
        self.lpass()
        mine = self.published()
        old = dict(mine, tot=dict(mine["tot"], ads=7))
        self.api.put_group(pb.G_LEDGER, json.dumps(old), False)            # what a restored backup brings back
        self.ledger_writes.clear()
        self.advance(15)
        self.lpass()
        self.assertEqual(self.ledger_writes, [], "not before the hour is over")
        self.advance(3600)
        self.lpass()
        self.assertEqual(self.published()["tot"]["ads"], 1200)
        self.api.put_group(pb.G_LEDGER, "a hand edit", False)
        self.ledger_writes.clear()
        restarted = self.maintenance()
        self.lpass(restarted)
        self.advance(15)
        self.lpass(restarted)
        self.assertEqual(len(self.ledger_writes), 1, "right after a start, the group is put right")
        check_contract(self, next(g for g in self.store.groups if g["name"] == pb.G_LEDGER)["comment"])

    def test_a_group_someone_switched_on_is_switched_off_again(self):
        self.lpass()
        self.advance(15)
        self.lpass()
        group = next(g for g in self.store.groups if g["name"] == pb.G_LEDGER)
        group["enabled"] = True
        self.advance(3600)
        self.lpass()
        self.assertFalse(group["enabled"])

    def test_never_while_an_update_runs_nor_after_sinko_was_removed(self):
        self.set_state(lambda s: s["update"].update(status="running", at=self.now.timestamp()))
        for _ in range(4):
            self.advance(15)
            self.lpass()
        self.assertEqual(self.ledger_writes, [])
        self.set_state(lambda s: s["update"].update(status="ok"))
        os.makedirs(self.state_dir, exist_ok=True)
        with open(pb.state_path("removed"), "w") as fh:
            fh.write("1\n")
        for _ in range(4):
            self.advance(15)
            self.lpass()
        self.assertEqual(self.ledger_writes, [])
        self.assertIsNone(self.published(), "a removed Sinko does not make its group again")
        os.remove(pb.state_path("removed"))
        self.advance(15)
        self.lpass()
        self.assertEqual(len(self.ledger_writes), 1)

    def test_a_clock_that_is_not_believed_or_a_failed_tick_counts_nothing(self):
        self.clock_trusted = False
        for _ in range(4):
            self.advance(15)
            self.lpass()
        self.lm.tick_ok = False
        self.clock_trusted = True
        for _ in range(4):
            self.advance(15)
            self.lpass()
        self.assertEqual(self.stop_calls, [])
        self.assertIsNone(self.lm.ledger.data, "the ledger was not even read")
        self.assertIsNone(self.published())

    def test_the_off_time_needs_a_child_device(self):
        self.internet_off(True)
        for _ in range(9):
            self.advance(15)
            self.lpass()
        self.assertEqual(self.lm.ledger.load()["days"]["2026-10-21"]["off"], 0)
        self.add_kid()
        self.advance(60)                                        # the look at the children's devices is a minute old
        for _ in range(5):
            self.advance(15)
            self.lpass()
        self.assertGreater(self.lm.ledger.load()["days"]["2026-10-21"]["off"], 0)

    def test_a_corrupt_savings_json_never_stops_the_scheduler(self):
        os.makedirs(self.state_dir, exist_ok=True)
        with open(pb.state_path(pb.SAVINGS_FILE), "w") as fh:
            fh.write("\x00garbage")
        with self.assertLogs("sinko", level="WARNING"):
            self.lpass()
            self.advance(15)
            self.lpass()
        with open(pb.state_path(pb.SAVINGS_FILE)) as fh:
            self.assertEqual(json.load(fh)["v"], 1)
        check_contract(self, next(g for g in self.store.groups if g["name"] == pb.G_LEDGER)["comment"])

    def test_the_ad_list_count_comes_from_pihole_until_the_ledger_knows_it(self):
        self.store.lists.append({"id": 900, "address": "https://example.org/ads", "type": "block", "comment": None, "enabled": True,
                                 "groups": [0], "number": 0})
        self.lm.stops = lambda windows, services: {"days": {}, "adLists": None, "why": "gravity.db cannot be read"}
        self.lpass()
        self.advance(15)
        self.lpass()
        self.assertEqual(self.published()["adLists"], 1, "the one list that is not Sinko's")

    def test_the_stops_are_never_read_on_the_tick_thread(self):
        seen = []
        done = threading.Event()

        def stops(windows, services):
            seen.append(threading.current_thread())
            done.set()
            return {"days": {}, "adLists": 0, "why": None}
        m = self.maintenance(job_factory=pb.BackgroundJob, stops=stops)
        self.lpass(m)
        self.assertTrue(done.wait(10))
        self.assertIsNot(seen[0], threading.current_thread())
        self.assertTrue(seen[0].name.startswith("sinko-"))

    def test_a_clean_stop_keeps_what_was_counted(self):
        self.lpass()
        self.advance(15)
        self.lpass()
        self.add_kid()
        self.internet_off(True)
        for _ in range(10):
            self.advance(15)
            self.lpass()
        self.lm.close()
        with open(pb.state_path(pb.SAVINGS_FILE)) as fh:
            self.assertGreater(json.load(fh)["days"]["2026-10-21"]["off"], 100)

    def test_the_scheduler_closes_its_maintenance_and_builds_it_with_a_ledger(self):
        sched = pb.Scheduler(clock=pb.ClockGuard(uptime=lambda: None, synchronized=lambda: None), maintenance=self.lm)
        self.lpass()
        self.advance(15)
        self.lpass()
        self.lm.ledger.dirty = True
        sched.close()
        self.assertFalse(self.lm.ledger.dirty)
        built = {}

        class Spy:
            def __init__(self, **kw):
                built.update(kw)
        with mock.patch.object(pb, "Maintenance", Spy):
            pb.Scheduler()
        self.assertIsInstance(built["ledger"], pb.Ledger)
        self.assertIsNone(pb.Maintenance(self.api).ledger, "off unless given: a test about something else adds no group")

    def test_remove_takes_pb_ledger_away_with_the_other_groups(self):
        self.lpass()
        self.advance(15)
        self.lpass()
        self.assertIsNotNone(self.published())
        self.ctl.remove()
        self.assertFalse([g for g in self.store.groups if g["name"].startswith("pb-")])


class TextTests(unittest.TestCase):
    def payload(self, apps_per_day, sid_length=30):
        names = ["a%s%02d" % ("x" * (sid_length - 3), i) for i in range(apps_per_day)]
        today = dt.date(2026, 10, 21)
        days = [{"d": (today - dt.timedelta(days=b)).isoformat(), "ads": 12345678, "offSec": 86000, "kept": 1,
                 "apps": {n: 100000 - i for i, n in enumerate(names)}} for b in range(6, -1, -1)]
        return {"v": 1, "at": int(dt.datetime(2026, 10, 21, 12).timestamp()), "today": today.isoformat(), "since": "2026-01-01",
                "keptSince": "2026-01-01", "adLists": 3, "days": days,
                "tot": {"ads": 99999999999, "apps": dict(list(days[0]["apps"].items())[:8]), "offSec": 99999999, "nights": 300,
                        "nightsKept": 290}}

    def test_the_comment_stays_under_four_thousand_characters_and_the_apps_of_each_day_go_first(self):
        payload = self.payload(8, sid_length=60)
        self.assertGreater(len(json.dumps(payload, separators=(",", ":"))), 4000)
        text = pb.ledger_text(payload)
        data = check_contract(self, text)
        self.assertEqual(len(data["days"]), 7, "the days stay")
        self.assertEqual(data["tot"], payload["tot"], "the totals stay")
        self.assertTrue(all(len(d["apps"]) < 8 for d in data["days"]))
        for d in data["days"]:
            self.assertEqual(list(d["apps"]), list(payload["days"][0]["apps"])[:len(d["apps"])], "the biggest are kept")

    def test_a_small_week_is_untouched(self):
        payload = self.payload(3, sid_length=8)
        self.assertEqual(json.loads(pb.ledger_text(payload)), payload)

    def test_parse_and_compare(self):
        self.assertIsNone(pb.parse_ledger("a hand edit"))
        self.assertIsNone(pb.parse_ledger("[1]"))
        self.assertIsNone(pb.parse_ledger(None))
        self.assertIsNone(pb.parse_ledger('{"v": NaN}'))
        a = self.payload(2, 8)
        self.assertTrue(pb.same_ledger(a, dict(a, at=1)), "only the time it was made apart")
        self.assertFalse(pb.same_ledger(a, dict(a, adLists=0)))
        self.assertFalse(pb.same_ledger(None, a))


class DiagnoseSummaryTests(td.DiagnoseBase):
    def test_diagnose_prints_counts_only_and_not_the_group(self):
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        env = mock.patch.dict(os.environ, {"SINKO_STATE_DIR": state.name})
        env.start()
        self.addCleanup(env.stop)
        ledger = pb.Ledger()
        today = dt.date.fromtimestamp(self.now).isoformat()
        ledger.merge({"days": {today: {"ads": 4321, "apps": {"youtube": 12}, "whole": False}}, "adLists": 2},
                     dt.datetime.fromtimestamp(self.now))
        ledger.save()
        self.api.add_group(pb.G_LEDGER, "{}", False)
        _facts, _findings, text = self.diagnose()
        section = text.split("What the box counted for the family")[1].split("\nFindings")[0]
        self.assertIn("4321", section)
        self.assertIn("youtube 12", section)
        self.assertIn("2 block list(s)", section)
        self.assertNotIn(pb.G_LEDGER, text.split("Block lists")[0], "the copy for the page is not one of the rules")


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    unittest.main()
