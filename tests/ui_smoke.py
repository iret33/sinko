"""Headless-browser smoke test of the parent page against a fresh mock Pi-hole.

    python3 tests/ui_smoke.py [--shots DIR]

Requires: pip install playwright && playwright install chromium
"""
import argparse
import importlib.machinery
import importlib.util
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import mock_pihole  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--shots", default=None)
args = ap.parse_args()

httpd, store = mock_pihole.serve(0, os.path.join(ROOT, "web"))
loader = importlib.machinery.SourceFileLoader("pb", os.path.join(ROOT, "bin", "sinko"))
spec = importlib.util.spec_from_loader("pb", loader)
pb = importlib.util.module_from_spec(spec)
loader.exec_module(pb)
api = pb.Api("http://127.0.0.1:%d" % httpd.server_port, password=mock_pihole.PASSWORD)
api.login()
pb.Controller(api, pb.load_catalog(os.path.join(ROOT, "lists")), os.path.join(ROOT, "lists")).setup(run_gravity=False)
api.logout()
args.url = "http://127.0.0.1:%d/" % httpd.server_port
errors = []
failures = []


def shot(page, name, full=False):
    if args.shots:
        os.makedirs(args.shots, exist_ok=True)
        page.evaluate("() => Promise.all(document.getAnimations().filter(a => { const t = a.effect && a.effect.getComputedTiming(); return t && isFinite(t.endTime); }).map(a => a.finished.catch(() => {})))")   # a sheet still sliding in is see-through
        page.screenshot(path=os.path.join(args.shots, name), full_page=full)


def expect(cond, msg):
    print(("ok    " if cond else "FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def pressed(page, sid):
    """The app's row says Block (its "Block" key is the pressed one of the two)."""
    return page.get_attribute("[data-id=%s] [data-want=block]" % sid, "aria-pressed") == "true"


def settle(page):
    # The page's CSP forbids eval, so wait with selectors instead of JS predicates.
    page.wait_for_timeout(100)
    page.locator("body:not(.is-busy)").wait_for()
    page.wait_for_timeout(250)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    # 401s are expected (auth probe before sign-in, wrong-password check).
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "401" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(args.url)
    page.wait_for_selector("#login:not([hidden])")
    shot(page, "01-login.png")
    page.fill("#pw", "wrong")
    page.click("#loginBtn")
    page.locator("#loginErr:not(:empty)").wait_for()
    expect("not right" in page.inner_text("#loginErr"), "wrong password is rejected")

    page.fill("#pw", "test")
    page.click("#loginBtn")
    # The first sign-in shows the terms of use, with both choices switched on, before the page itself.
    page.wait_for_selector("#terms:not([hidden])")
    expect(page.is_hidden("#app"), "the page waits until the terms are agreed to")
    expect(page.is_checked("#termsLearn") and page.is_visible("#termsCounterRow") and page.is_checked("#termsCounter"),
           "both choices start switched on (this box has a counter address)")
    expect(store.state().get("telemetry", {}).get("on") is None and store.state().get("learn", {}).get("on") is not True,
           "nothing is decided, and nothing learned or sent, before the parent agrees")
    page.locator("#termsLinkTerms:not([hidden])").wait_for()
    expect(page.get_attribute("#termsLinkTerms", "href").endswith("/docs/terms.md")
           and page.get_attribute("#termsLinkPrivacy", "href").endswith("/docs/privacy.md"), "it links to the full terms and the privacy statement")
    shot(page, "01b-terms.png", full=True)
    page.click("#termsBtn")
    page.wait_for_selector("#app:not([hidden])")
    agreed = store.state()
    expect({k: agreed.get(k) for k in ("terms", "learn", "telemetry")} == {"terms": {"agreed": 1}, "learn": {"on": True}, "telemetry": {"on": True}},
           "agreeing records the terms and both choices: %r" % {k: agreed.get(k) for k in ("terms", "learn", "telemetry")})
    page.wait_for_selector(".tile")
    expect(page.inner_text("#heroTitle") == "Children\u2019s internet is on", "the control panel says the children's internet is on")
    expect(page.locator(".tile").count() == 19, "19 app rows")
    expect(page.locator(".tile [data-want=allow][aria-pressed=true]").count() == 19, "every app starts allowed, said by its Allow key")
    expect(page.is_hidden("#heroFor"), "no device yet: no 'off for a while' keys")
    expect("not shared its numbers yet" in page.inner_text("#savedBody"), "the savings card says the box has not counted yet (no ledger)")
    expect(page.is_hidden("#liveView") and page.locator("#live").count() == 1, "the live picture waits behind its own button")
    expect(page.inner_text("#heroBtn") == "Add device", "first run: hero asks to add a device")
    shot(page, "02-home.png", full=True)

    page.click("[data-act=openAdd]")
    page.wait_for_selector("#picker .pick")
    expect("This device" in page.inner_text("#picker"), "picker marks the current device")
    shot(page, "03-add.png")
    page.click("[data-act=addDevice]")
    expect("Pick a device" in page.inner_text("#addErr"), "add without selection explains what to do")
    page.click("#addForm .manual summary")
    page.fill("#manualAddr", "not-an-address")
    page.click("[data-act=addDevice]")
    expect("MAC address" in page.inner_text("#addErr"), "invalid manual address is rejected")
    page.fill("#manualAddr", "")
    page.click("#picker .pick >> nth=0")
    page.fill("#devName", "Sara's iPad")
    page.click("[data-act=addDevice]")
    settle(page)
    expect("Sara's iPad" in page.inner_text("#devices"), "device added from picker")

    restarts = store.dns_restarts
    page.click("[data-id=youtube] [data-want=block]")
    settle(page)
    expect(pressed(page, "youtube"), "YouTube blocked with its Block key")
    expect("tile-blocked" in (page.get_attribute("[data-id=youtube]", "class") or ""), "and its row is marked blocked")
    expect(store.dns_restarts == restarts + 1, "a rule change clears the box's DNS cache so it applies at once (%d -> %d)" % (restarts, store.dns_restarts))

    page.click("[data-act=homework]")
    settle(page)
    expect(pressed(page, "tiktok") and not pressed(page, "whatsapp"), "homework blocks TikTok, keeps WhatsApp")

    page.click("[data-act=timer][data-mode=free]")
    page.click("#timerChips .chip >> nth=1")
    shot(page, "04-timer-sheet.png")
    page.click("[data-act=startTimer]")
    settle(page)
    expect(page.inner_text("#heroKicker") == "Free time", "free-time timer running")
    expect(not pressed(page, "tiktok"), "free time allows TikTok")
    expect(page.is_disabled("[data-id=tiktok] [data-want=allow]") and page.is_disabled("[data-id=tiktok] [data-want=block]"),
           "apps are locked while a timer runs")
    clock = page.inner_text("#heroClock")
    expect(clock.startswith("59:") or clock.startswith("1:00:"), "countdown shows ~1 hour (%s)" % clock)
    shot(page, "05-timer.png", full=True)

    page.click("#heroBtn")
    settle(page)
    expect(page.inner_text("#heroTitle") == "Children\u2019s internet is on", "timer ended")
    expect(pressed(page, "tiktok") and pressed(page, "youtube") and not pressed(page, "whatsapp"),
           "rules from before the timer restored")

    page.click("#heroBtn")
    settle(page)
    expect(page.inner_text("#heroTitle") == "Children\u2019s internet is off", "internet off")
    expect("is-off" in page.get_attribute("#hero", "class") and page.inner_text("#heroBtn") == "Turn it back on",
           "the whole panel goes dark and its key says how to undo it")
    expect(page.is_hidden("#heroFor"), "no 'off for a while' keys while it is already off")
    shot(page, "06-off.png")
    page.click("#heroBtn")
    settle(page)
    expect(page.inner_text("#heroTitle") == "Children\u2019s internet is on", "and back on")

    # --- the 'off for a while' keys: an offline break of a set length, or until the morning (the end of bedtime, else 07:00 on the box)
    expect("key-off" in page.get_attribute("#heroBtn", "class") and page.is_visible("#off30"), "the big key is the orange one, with the keys for a while")
    page.click("#off30")
    settle(page)
    tm = store.state()["timer"]
    expect(tm and tm["mode"] == "block" and abs(tm["until"] - (time.time() + 1800)) < 30, "Off for 30 min starts a 30-minute break (%r)" % tm)
    expect(page.inner_text("#heroKicker") == "Offline break" and page.inner_text("#heroTitle") == "Children\u2019s internet is off",
           "the panel says it is off, for a break")
    expect("Back on at" in page.inner_text("#heroSub"), "and when it comes back")
    page.click("#heroBtn")
    settle(page)
    expect(store.state()["timer"] is None and page.inner_text("#heroTitle") == "Children\u2019s internet is on", "Turn it back on ends the break")
    # The third key: in the evening and at night "Off until <morning>" (the end of bedtime, else 07:00 on the box's clock); in the
    # daytime, when the morning is more than 15 hours away, "Off for 2 hours" instead.
    label = page.inner_text("#offMorning")
    third = page.get_attribute("#offMorning", "data-act")
    page.click("#offMorning")
    settle(page)
    tm = store.state()["timer"]
    sched = store.state()["schedule"]
    morning = sched["end"] if sched.get("enabled") and sched.get("days") else "07:00"
    off = store.box_info["utcOffset"]                            # the box's zone (box.json), which is not this machine's
    off_s = (1 if off[0] == "+" else -1) * (int(off[1:3]) * 3600 + int(off[4:6]) * 60)
    if third == "offMorning":
        expect(tm and tm["mode"] == "block" and time.strftime("%H:%M", time.gmtime(tm["until"] + off_s)) == morning and 60 < tm["until"] - time.time() <= 15 * 3600 + 60,
               "Off until morning ends at %s on the box's clock (%s, %r)" % (morning, label, tm and time.ctime(tm["until"])))
    else:
        expect(label == "Off for 2 hours" and tm and tm["mode"] == "block" and abs(tm["until"] - (time.time() + 7200)) < 30,
               "in the daytime the third key is a two-hour break (%s, %r)" % (label, tm))
    expect(page.evaluate("() => document.activeElement && document.activeElement.id") == "heroBtn",
           "the pressed key is gone while it is off: focus moves to the big key, not to the page")
    page.click("#heroBtn")
    settle(page)

    page.click("[data-act=timer][data-mode=block]")
    page.fill("#timerMinutes", "2")
    page.click("[data-act=startTimer]")
    expect("5 to 720" in page.inner_text("#toast"), "too-short timer rejected")
    page.fill("#timerMinutes", "45")
    page.click("[data-act=startTimer]")
    settle(page)
    expect(page.inner_text("#heroKicker") == "Offline break", "offline break running")
    page.click("#heroBtn")
    settle(page)

    page.click("[data-act=pause]")
    settle(page)
    expect("Paused" in page.inner_text("#devices"), "device paused")
    page.click("[data-act=pause]")
    settle(page)

    # Everything the scheduler (or the My box sheet) keeps in the shared state must survive a bedtime save.
    state_group = next(g for g in store.groups if g["name"] == "pb-state")
    seeded = json.loads(state_group["comment"])
    seeded["update"].update({"auto": True, "latest": "3.1.0", "notes": "https://github.com/iret33/sinko/releases/tag/v3.1.0",
                             "checked": 1800000000, "status": "ok", "from": "3.0.0", "to": "3.1.0", "at": 1800000100})
    seeded["telemetry"] = {"on": True}
    seeded["community"] = {"online": 42, "at": 1800000000}
    seeded["setup"] = {"done": True}
    state_group["comment"] = json.dumps(seeded)
    page.check("#bedOn")
    settle(page)
    expect(store.state()["schedule"]["enabled"], "the bedtime switch takes effect at once")
    expect("every night" in page.inner_text("#bedSentence"), "and the sentence says when: %r" % page.inner_text("#bedSentence"))
    page.click("#bedEdit summary")
    page.fill("#bedStart", "21:30")
    page.click("[data-act=saveBed]")
    settle(page)
    kept = json.loads(state_group["comment"])
    expect(kept["schedule"]["start"] == "21:30" and kept["schedule"]["enabled"], "the bedtime itself was saved")
    expect(all(kept[k] == seeded[k] for k in ("update", "telemetry", "community", "setup", "learn", "terms")),
           "saving bedtime keeps every field the scheduler wrote (update, counter answer, community, setup, learning, terms)")
    page.reload()
    page.wait_for_selector(".tile")
    expect(page.input_value("#bedStart") == "21:30" and page.is_checked("#bedOn"), "bedtime saved and session kept")

    # --- What Sinko did for you: the box's ledger (the disabled group pb-ledger, which only the box writes), worded for a parent
    day = lambda back: time.strftime("%Y-%m-%d", time.gmtime(time.time() + off_s - back * 86400))
    week = [13102, 14880, 12450, 16920, 15230, 11622, 14208]
    ledger = {"v": 1, "at": int(time.time()) - 300, "today": day(0), "since": day(200), "keptSince": day(200), "adLists": 1,
              "days": [{"d": day(6 - i), "ads": n, "apps": {"tiktok": 60 + i, "roblox": 30}, "offSec": 32400, "kept": 1 if i < 6 else None}
                       for i, n in enumerate(week)],
              "tot": {"ads": 3100000, "apps": {"tiktok": 12840, "roblox": 9115}, "offSec": 6854400, "nights": 199, "nightsKept": 190}}
    store.groups.append({"id": next(store.ids), "name": "pb-ledger", "comment": json.dumps(ledger), "enabled": False})
    page.evaluate("() => { try { localStorage.removeItem('pb.period'); localStorage.removeItem('pb.price'); } catch (e) {} }")
    page.reload()
    page.wait_for_selector(".tile")
    saved = page.inner_text("#savedBody")
    expect("98,412" in saved and "Less waiting for ads" in saved and "1 hr 22 min" in saved,
           "this week: ads stopped, and about 50 ms of waiting for each (%r)" % saved[:160])
    expect("1 GB" in saved and "TikTok tried to open" in saved and "6 of 6 nights" in saved, "data saved, app tries and bedtime nights")
    expect(page.locator("#savedBody .bar").count() == 7 and page.locator("#savedBody .bar.is-today").count() == 1, "seven bars, today's marked")
    page.click("[data-period=today]")
    expect("14,208" in page.inner_text("#savedBody"), "Today shows today's row")
    page.click("[data-period=since]")
    expect("3,100,000" in page.inner_text("#savedBody") and "190 of 199 nights" in page.inner_text("#savedBody"), "Since shows the running totals")
    page.reload()
    page.wait_for_selector(".tile")
    expect(page.get_attribute("[data-period=since]", "aria-pressed") == "true", "the chosen period is remembered on this phone")
    expect("at your price" not in page.inner_text("#savedBody"), "no money without a price the parent typed")
    page.click("#priceBtn")
    page.locator("#priceDialog[open]").wait_for()
    page.fill("#priceValue", "0")
    page.click("[data-act=priceSave]")
    expect("above 0" in page.inner_text("#priceErr"), "a price of 0 is refused")
    page.fill("#priceValue", "0.5")
    page.fill("#priceCurrency", "BHD")
    page.press("#priceValue", "Enter")
    page.locator("#priceDialog[open]").wait_for(state="detached")
    page.click("[data-period=week]")
    money = page.inner_text("#savedBody")
    expect("\u20660.492 BHD\u2069 at your price" in money, "with a price, the data saved is also said in money, kept in one piece for Arabic: %r" % money[:200])
    shot(page, "05b-saved.png")
    store.groups[:] = [g for g in store.groups if g["name"] != "pb-ledger"]

    # --- the live picture lives behind "See it live", over the page, and Escape (or Back) brings the page back
    page.click("#liveOpen")
    page.locator("#liveView:not([hidden])").wait_for()
    expect(page.is_visible("#live #stage"), "the live picture opens with its drawing")
    expect(page.evaluate("() => document.activeElement && document.activeElement.id") == "liveViewTitle", "focus moves to its title")
    expect(page.evaluate("() => document.getElementById('cols').inert === true"), "the page behind it cannot be reached meanwhile")
    page.keyboard.press("Escape")
    page.locator("#liveView[hidden]").wait_for(state="attached")
    expect(page.evaluate("() => document.activeElement && document.activeElement.id") == "liveOpen", "closing returns focus to the button that opened it")

    page.click(".topbar [data-act=lang]")
    expect(page.get_attribute("html", "dir") == "rtl", "Arabic switches to right-to-left")
    expect(page.inner_text("#heroTitle") == "إنترنت الأطفال يعمل", "Arabic hero text")
    shot(page, "07-arabic.png", full=True)
    page.click("#bedEdit summary")
    page.click("#bedDays label >> nth=0")
    page.click(".topbar [data-act=lang]")

    page.click("[data-act=remove]")
    page.click("#confirmYes")
    settle(page)
    expect("No devices yet" in page.inner_text("#devices"), "device removed")

    page.click(".topbar [data-act=logout]")
    page.wait_for_selector("#login:not([hidden])")
    expect(True, "signed out")

    # --- another Pi-hole client row that overrides a child's MAC row (FTL prefers IP/subnet rows)
    catalog = pb.load_catalog(os.path.join(ROOT, "lists"))

    def pb_api(method, path, body=None):
        api.login()
        try:
            return api.request(method, path, body)
        finally:
            api.logout()

    pb_api("POST", "/api/clients", {"client": "192.168.1.0/24", "comment": "", "groups": [0]})
    page.fill("#pw", "test")
    page.click("#loginBtn")
    page.wait_for_selector(".tile")
    page.click("[data-act=openAdd]")
    page.wait_for_selector("#picker .pick")
    page.click("#picker .pick >> nth=0")                         # Sara-iPad, 192.168.1.21
    page.click("[data-act=addDevice]")
    page.locator(".device-warn").wait_for()
    expect("192.168.1.0/24" in page.inner_text(".device-warn"), "a subnet row that overrides the child is called out")
    expect("overrides it" in page.inner_text("#toast"), "adding such a device warns right away")
    shot(page, "09-shadowed.png", full=True)
    page.click(".topbar [data-act=lang]")
    expect("لوحة Pi-hole" in page.inner_text(".device-warn"), "the warning is translated")
    page.click(".topbar [data-act=lang]")
    pb_api("DELETE", "/api/clients/" + api.q("192.168.1.0/24"))
    page.reload()
    page.wait_for_selector(".tile")
    expect(page.locator(".device-warn").count() == 0, "no warning once the overriding row is gone")

    store.devices.append({"id": 40, "hwaddr": "aa:bb:cc:00:00:04", "macVendor": "", "lastQuery": int(time.time()) - 20,
                          "numQueries": 9, "ips": [{"ip": "fe80::4", "name": ""}, {"ip": "2001:db8::4", "name": ""}]})
    gid = {g["name"]: g["id"] for g in pb_api("GET", "/api/groups")["groups"]}
    pb_api("POST", "/api/clients", {"client": "AA:BB:CC:00:00:04", "comment": "Tablet", "groups": pb.kid_groups(gid, catalog)})
    pb_api("POST", "/api/clients", {"client": "2001:db8::/32", "comment": "", "groups": [0]})
    page.reload()
    page.wait_for_selector(".tile")
    expect(page.locator(".device-warn").count() == 1, "an IPv6 subnet row is detected too")

    # --- IPv6-only network-table entries are not offered; typing an IPv6 address asks first
    now_ts = int(time.time())
    store.devices.append({"id": 41, "hwaddr": "ip-fd00::1234", "macVendor": "", "lastQuery": now_ts - 5,
                          "numQueries": 3, "ips": [{"ip": "fd00::1234", "name": ""}]})
    store.devices.append({"id": 42, "hwaddr": "ip-fd00::2", "macVendor": "", "lastQuery": now_ts - 6,
                          "numQueries": 3, "ips": [{"ip": "fd00::2", "name": ""}, {"ip": "192.168.1.88", "name": ""}]})
    page.reload()
    page.wait_for_selector(".tile")
    page.click("[data-act=openAdd]")
    page.wait_for_selector("#picker .pick")
    expect(page.locator("#picker [data-addr*=fd00]").count() == 0, "an IPv6-only entry is not offered in the picker")
    expect(page.locator("#picker [data-addr='192.168.1.88']").count() == 1, "an entry with an IPv4 address is offered by it")
    page.click("#addForm .manual summary")
    page.fill("#manualAddr", "fd00::5")
    page.click("[data-act=addDevice]")
    page.locator("#confirmDialog[open]").wait_for()
    expect("IPv6" in page.inner_text("#confirmText"), "typing an IPv6 address asks for confirmation")
    page.click("#confirmDialog button[value=no]")
    page.wait_for_timeout(300)
    expect("fd00::5" not in [c["client"] for c in store.clients], "cancelling adds nothing")
    page.click("[data-act=addDevice]")
    page.locator("#confirmDialog[open]").wait_for()
    page.click("#confirmYes")
    settle(page)
    expect("fd00::5" in [c["client"] for c in store.clients], "confirming adds the device")

    # --- the phone's clock is wrong by two hours: timers must still follow the BOX's clock
    skew = browser.new_page(viewport={"width": 390, "height": 844})
    skew.clock.set_fixed_time(int(time.time()) + 2 * 3600)
    skew.goto(args.url)
    skew.fill("#pw", "test")
    skew.press("#pw", "Enter")
    skew.wait_for_selector(".tile")
    skew.click("[data-act=timer][data-mode=free]")
    skew.click("#timerChips .chip >> nth=1")
    skew.click("[data-act=startTimer]")
    skew.locator("#heroClock:not([hidden])").wait_for()
    import json as _json
    state = next(g for g in store.groups if g["name"] == "pb-state")
    until = _json.loads(state["comment"])["timer"]["until"]
    expect(abs(until - (time.time() + 3600)) < 30, "a timer started on a phone with a wrong clock ends an hour from now on the box (off by %ds)" % (until - time.time() - 3600))
    clock = skew.inner_text("#heroClock")
    expect(clock.startswith("59:") or clock.startswith("1:00:"), "and its countdown shows about an hour, not three (%s)" % clock)
    skew.click("#heroBtn")
    skew.close()

    dark = browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme="dark")
    dark.goto(args.url)
    dark.fill("#pw", "test")
    dark.press("#pw", "Enter")
    dark.wait_for_selector(".tile")
    shot(dark, "08-desktop-dark.png", full=True)
    dark.close()

    # --- the terms on a box where the parent already said no to the counter, in Arabic, and on an older box with no counter address
    store.edit_state(lambda st: st.update(terms={"agreed": 0}, telemetry={"on": False}, learn={"on": False}))
    ar = browser.new_page(viewport={"width": 390, "height": 844}, locale="ar-BH")
    ar.goto(args.url)
    ar.fill("#pw", "test")
    ar.press("#pw", "Enter")
    ar.wait_for_selector("#terms:not([hidden])")
    expect(ar.get_attribute("html", "dir") == "rtl" and ar.inner_text("#termsTitle") == "قبل أن تبدأ", "the terms are in Arabic, right to left")
    expect(ar.is_checked("#termsLearn") and not ar.is_checked("#termsCounter"),
           "learning starts switched on, the counter stays off where the parent already said no")
    shot(ar, "01c-terms-ar.png", full=True)
    ar.click("#termsLearn")
    ar.click("#termsBtn")
    ar.wait_for_selector(".tile")
    after = store.state()
    expect({k: after.get(k) for k in ("terms", "learn", "telemetry")} == {"terms": {"agreed": 1}, "learn": {"on": False}, "telemetry": {"on": False}},
           "a choice switched off before agreeing is recorded as off: %r" % {k: after.get(k) for k in ("terms", "learn", "telemetry")})
    ar.reload()
    ar.wait_for_selector(".tile")
    expect(ar.is_hidden("#terms"), "once agreed, the terms are not asked again")
    ar.close()
    store.edit_state(lambda st: st.update(terms={"agreed": 0}, telemetry={"on": None}))
    store.box_info = None
    old = browser.new_page(viewport={"width": 390, "height": 844})
    old.goto(args.url)
    old.fill("#pw", "test")
    old.press("#pw", "Enter")
    old.wait_for_selector("#terms:not([hidden])")
    expect(old.is_hidden("#termsCounterRow"), "a box that does not say it has a counter address does not offer the counter")
    old.click("#termsBtn")
    old.wait_for_selector(".tile")
    expect(store.state().get("telemetry") == {"on": None}, "and agreeing leaves the counter undecided")
    old.close()
    browser.close()

expect(not errors, "no console errors %s" % (errors or ""))
print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
