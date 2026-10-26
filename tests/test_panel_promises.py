"""What the control panel promises is what the box does.

The page's sentence "back on at ...", "bedtime ends at ..." or "bedtime starts at ... and ends it" comes from PBCore.comesBack
(web/pb-core.js); the box's scheduler (bin/sinko, Controller.tick with in_schedule) decides when the children's internet really
comes back. This runs both over hundreds of bedtimes, timers and moments, and fails on any disagreement: the page must never
say a time the box will not keep. Needs node. The box's wall clock is UTC here (the page is told offset 0).
"""
import datetime as dt
import importlib.machinery
import importlib.util
import json
import os
import random
import shutil
import subprocess
import time
import unittest

import mock_pihole

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

loader = importlib.machinery.SourceFileLoader("sinko_cli_promises", os.path.join(ROOT, "bin", "sinko"))
spec = importlib.util.spec_from_loader("sinko_cli_promises", loader)
pb = importlib.util.module_from_spec(spec)
loader.exec_module(pb)

NODE = r"""
const C = require(%s); const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
for (const c of cases) {
  if (c.kind === 'morning') c.until = C.nextWallTime(c.now, c.sc.end, 0);
  c.promise = C.comesBack(c.kind === 'morning' ? 'break' : c.kind, c.sc, c.now, c.until, 0);
  c.inBed = C.inBedtime(c.sc, c.now, 0);
}
console.log(JSON.stringify(cases));
""" % json.dumps(os.path.join(ROOT, "web", "pb-core.js"))


def hhmm(m):
    return "%02d:%02d" % (m // 60, m % 60)


@unittest.skipUnless(shutil.which("node"), "needs node")
class ThePanelSaysWhatTheBoxDoes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"                         # the scheduler reads naive local times: make local time UTC
        time.tzset()
        cls.httpd, cls.store = mock_pihole.serve()
        cls.api = pb.Api("http://127.0.0.1:%d" % cls.httpd.server_port, password=mock_pihole.PASSWORD)
        cls.api.login()
        cls.ctl = pb.Controller(cls.api, pb.load_catalog(os.path.join(ROOT, "lists")), "https://lists.example/l")
        cls.ctl.setup(run_gravity=False)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        if cls.tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = cls.tz
        time.tzset()

    def group(self, name):
        return next(g for g in self.store.groups if g["name"] == name)

    def cases(self, seed, count):
        rnd = random.Random(seed)
        out = []
        for _ in range(count):
            s, e = rnd.randrange(0, 288) * 5, rnd.randrange(0, 288) * 5
            if s == e:
                e = (e + 60) % 1440
            sc = {"enabled": True, "start": hhmm(s), "end": hhmm(e), "days": sorted(rnd.sample(range(7), rnd.randint(1, 7)))}
            now = (dt.datetime(2026, 10, 26) + dt.timedelta(minutes=rnd.randrange(0, 7 * 288) * 5)).timestamp()
            kind = rnd.choice(["break", "free", "off", "morning"])
            until = now + rnd.choice([30, 60, 120, 240, 600, 900]) * 60 if kind != "off" else None
            out.append({"kind": kind, "sc": sc, "now": now, "until": until, "window": pb.in_schedule(sc, dt.datetime.fromtimestamp(now))})
        done = subprocess.run(["node", "-e", NODE], input=json.dumps(out), capture_output=True, text=True, check=True)
        return json.loads(done.stdout)

    def run_box(self, c):
        """Leaves the box as the page would, then plays every moment that can change something; returns when it comes back."""
        sc, now, until, kind = c["sc"], c["now"], c["until"], c["kind"]
        services = {"tiktok": True}
        if kind in ("break", "morning"):
            timer = {"mode": "block", "until": until, "snapshot": {"services": services, "offline": False}}
            offline = True
        elif kind == "free":
            timer = {"mode": "free", "until": until, "snapshot": {"services": services, "offline": False}}
            offline = False
        else:
            timer, offline = None, True
        state = json.loads(json.dumps(pb.DEFAULT_STATE))
        state.update(schedule=sc, scheduleActive=c["window"], timer=timer)
        self.ctl.write_state(state)
        self.api.put_group("pb-offline", "", offline)
        moments = {until} if until else set()
        first = dt.datetime.fromtimestamp(now).date()
        for k in range(-1, 10):
            day = dt.datetime.combine(first + dt.timedelta(days=k), dt.time())
            for at in (sc["start"], sc["end"]):
                ts = (day + dt.timedelta(hours=int(at[:2]), minutes=int(at[3:]))).timestamp()
                if ts > now:
                    moments.add(ts)
        for ts in sorted(moments):
            self.ctl.tick(dt.datetime.fromtimestamp(ts))
            off = self.group("pb-offline")["enabled"]
            if kind == "free":
                if off or pb.parse_state(self.group("pb-state")["comment"])["timer"] is None:
                    return ts
            elif not off:
                return ts
        return None

    def test_the_page_and_the_scheduler_agree(self):
        checked = 0
        for c in self.cases(seed=7, count=240):
            self.assertEqual(c["inBed"], c["window"], "PBCore.inBedtime and in_schedule disagree: %r" % c)
            if c["window"] and c["kind"] in ("free", "off"):
                continue        # in bedtime the panel says "ends automatically at <bedtime end>", not comesBack (and free time is not offered then)
            want = c["promise"]["at"]
            got = self.run_box(c)
            self.assertEqual(got, want, "%s, bedtime %s, now %s: the panel promises %s, the box does it at %s" % (
                c["kind"], c["sc"], time.strftime("%a %H:%M", time.gmtime(c["now"])),
                want and time.strftime("%a %H:%M", time.gmtime(want)), got and time.strftime("%a %H:%M", time.gmtime(got))))
            checked += 1
        self.assertGreater(checked, 150)


if __name__ == "__main__":
    unittest.main()
