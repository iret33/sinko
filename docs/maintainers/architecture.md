# Sinko — architecture and contracts (3.0)

This file is the single source of truth for how the parts of Sinko talk to each other.
If code and this file disagree, fix one of them in the same change.

Sinko (Arabic: سينكو) is a parental-controls page and scheduler on top of Pi-hole v6.
It ships as free software for people with their own hardware, and as a ready-made, pre-flashed
Orange Pi Zero 3.

## Pieces

| Piece | Where | Runs as | Notes |
|---|---|---|---|
| Parent page | `web/` → `/var/www/html/index.html` + `/pb/*` | browser (phone) | static files served by Pi-hole's web server; talks only to the Pi-hole API on the same origin |
| `sinko` CLI + scheduler | `bin/sinko` → `/opt/sinko/bin/sinko`, symlink `/usr/local/bin/sinko` | root (systemd `sinko.service` runs `sinko run`) | Python 3 standard library only |
| Installer | `install.sh` | root | idempotent: install, update and migrate |
| Appliance tools | `tools/seal.sh`, `tools/firstboot.sh`, `systemd/sinko-firstboot.service` | root | prepare / personalise the ready-made image |
| Release build | `tools/build-release.sh`, `.github/workflows/release.yml` | CI | produces the three release assets |
| Counter service | `telemetry/` (Cloudflare Worker + D1) | Cloudflare | anonymous "boxes online" count, sent only after the parent's answer (the terms screen offers it switched on) |
| Project site | `site/` → GitHub Pages | browser | landing page with live counters |
| Host suggestions | `tools/suggest-hosts.py`, `.github/workflows/host-suggestions.yml` | maintainer / CI | a small AI model trained from `lists/` suggests hosts the lists miss, for a person to check ([`host-model.md`](host-model.md)) |
| Host model and learner | `model/host-model.json` → `/opt/sinko/model/`, `Learner` in `bin/sinko` | root (inside the scheduler) | runs while `learn.on` (the terms screen offers it switched on): blocks a new name of a blocked app when the model and the app's own behaviour agree (see *Learning new addresses*) |

Pi-hole objects created by Sinko keep the **internal prefix `pb-`** (groups `pb-kids`, `pb-svc-<id>`, …; list
comments `pb:<id>`). The prefix is historical and is not user-facing; do not rename it (it would orphan existing
rules).

## Names, paths, environment

* Command `sinko`; repo `iret33/sinko` (`SINKO_REPO_SLUG`); units `sinko.service`, `sinko-lists.service`, `sinko-lists.timer`,
  `sinko-firstboot.service`; transient unit `sinko-update`.
* `/opt/sinko` (code; `/opt/sinko/src` is the last downloaded source), `/etc/sinko/config` (settings, shell-compatible
  `KEY=value`), `/var/lib/sinko/` (runtime data owned by root, see below), `/var/log/sinko-install.log`.
* Legacy (pihole-bahrain ≤ 2.2.x): `/opt/pihole-bahrain`, `/etc/pihole-bahrain`, units `pihole-bahrain*.service|timer`,
  command `pihole-bahrain`, config keys `PB_*`, page marker `<meta name="generator" content="pihole-bahrain">`.
  The installer migrates these (see *Migration*). `read_config` in the CLI also accepts legacy `PB_X` for any missing
  `SINKO_X`.
* Test/override hooks: `SINKO_ROOT` (installer fake root), `SINKO_APP_DIR`, `SINKO_CONFIG_FILE`, `SINKO_STATE_DIR`
  (default `/var/lib/sinko`), `SINKO_API_URL`, `SINKO_RELEASE_BASE`, `SINKO_RELEASE_API`, `SINKO_TELEMETRY_URL`.

### `/etc/sinko/config` keys

`SINKO_HOSTNAME`, `SINKO_LISTS_BASE`, `SINKO_REPO` (git URL), `SINKO_REPO_SLUG` (`owner/name`), `SINKO_REF`
(`latest` by default), `SINKO_IP`, `SINKO_TELEMETRY` (`1` / `0` / absent = not decided at install time),
`SINKO_TELEMETRY_URL` (empty = counter not configured), `SINKO_MDNS`, `SINKO_OS_UPDATES`.

### `/var/lib/sinko/` (root only, never reachable from the page)

| File | Purpose |
|---|---|
| `install-id` | random 128-bit hex used by the optional counter; created lazily, removed by `seal` |
| `box-id` | random 128-bit hex shown as `boxId` in `/pb/box.json`, so the app knows the box again at another address; made by the first box.json write (the installer's, or `firstboot.sh` on a ready-made box), removed by `seal`. Never the `install-id`: that one is the counter's, forgotten when the counter is switched off, and must not be readable on the home network |
| `handled.json` | `{"update": <nonce>, "check": <nonce>, "power": <nonce>}`: last request markers acted on |
| `update-result.json` | written by the update runner when it ends: `{"status":"ok|failed","from","to","error","at"}` |
| `cache/sinko-<version>.tar.gz` | the installed release and the newest older one (the rollback target); offline rollback |
| `lock` | the update runner's lock (the installer's own is `install.lock`: they must differ, the runner holds `lock` while it runs the installer) |
| `update-failure.json` | when and how the last update failed (retry rule: a transient failure may retry the same night after 30 minutes, others wait a week) |
| `gravity.lock` | the flock that every `pihole -g` which Sinko starts takes first (the program's own runs, and `sinko-lists.service` through `flock(1)`), so two runs never rebuild Pi-hole's one temporary database together; a run waits for the one before it for up to 30 minutes. Pi-hole's own weekly run and the page's restore cannot take it |
| `repair.json` | when the last `sinko repair` was started: the scheduler starts one at most once an hour, and its restart forgets everything else |
| `counter-sent` | marks that the current `install-id` was sent to the counter (a never-sent id is just deleted when the counter is switched off) |
| `forget-pending` | the counter's id waiting for its "forget me" request to succeed (retried every ping interval; no pings meanwhile) |
| `removed` | set by `sinko remove` so a running scheduler does not repair what was removed on purpose; cleared by `setup` |
| `savings.json` | the savings ledger behind the page's *What Sinko did for you* (see *Savings ledger (pb-ledger)*): daily counts for 35 days, running totals before them; written by the scheduler with each read of Pi-hole's database and when it stops; removed by `seal` (and with the folder by `uninstall.sh`) |
| `firstboot` | flag file: the ready-made image still has to personalise itself |

`/run/sinko/heartbeat.json` (memory, no card wear) is written by the scheduler after each good pass; the self-check reads it.

## Release assets

Tag `vX.Y.Z` with `VERSION` = `X.Y.Z` (CI checks). `tools/build-release.sh` builds, reproducibly:

* `sinko.tar.gz`: one top-level directory `sinko/` containing `bin/ lists/ model/ web/ systemd/ tools/seal.sh tools/firstboot.sh
  install.sh uninstall.sh VERSION LICENSE NOTICE` (no tests, docs, site, telemetry or development tools).
* `sinko.tar.gz.sha256`: one line, `<hex>  sinko.tar.gz`.
* `install.sh`: byte-identical to the file in the tag (the one-liner).

Stable asset names, so these URLs work: `https://github.com/<slug>/releases/latest/download/<asset>` and
`https://github.com/<slug>/releases/download/vX.Y.Z/<asset>`. Every download of an asset is counted by GitHub
(`download_count`): that is the project's download count (README badge, site counter).

Latest-release metadata: `https://api.github.com/repos/<slug>/releases/latest` (`tag_name`, `html_url`,
`prerelease`, `draft`). Overridable with `SINKO_RELEASE_API`; asset base overridable with `SINKO_RELEASE_BASE`
(default `https://github.com/<slug>/releases`) so tests can serve fake releases from a local HTTP server.

`SINKO_REF`: `latest` (default) = newest release; `vX.Y.Z` = that release; anything else (a branch such as `master`)
= developer path: `git clone --depth 1 --branch <ref> $SINKO_REPO`.

## Installer contract (`install.sh`)

* `curl --proto '=https' --proto-redir '=https' -fsSL https://github.com/<slug>/releases/latest/download/install.sh | sudo bash`
  (also still works from raw `master`). This one hardened form is the only one written anywhere (README, docs, the website):
  `--proto-redir` keeps a redirect from leaving https.
* Fetches the release tarball + `.sha256`, verifies it (refuses on mismatch), extracts to `/opt/sinko/src`, then runs
  the `install.sh` shipped inside it (existing re-exec behaviour). `SINKO_SRC=<dir>` uses an already extracted tree and
  skips fetching (used by `sinko update`, tests and the image build). Always non-interactive when `SINKO_NONINTERACTIVE=1`.
* Idempotent. Exit status ≠ 0 on failure, progress to stdout, full log in `/var/log/sinko-install.log` (the generated
  parent password never reaches the log).
* `SINKO_TELEMETRY=1|0` records the install-time answer (interactive installs ask: default *yes*, **and only when the program
  says a counter address is configured** (`sinko box-info` → `"counter": true`); without one nothing is asked or saved;
  non-interactive installs without the variable record nothing, so the page asks later, on the terms screen).
* Free space: more than **1 GB** for a first installation, more than **200 MB** for an update, a rollback or a move from
  pihole-bahrain (the scheduler's unit or what pihole-bahrain left says which); the refusal exits with status 75 and changes
  nothing. `bin/sinko` asks for the same 200 MB (`MIN_FREE_BYTES`) before it starts the installer.
* The parent password reaches Pi-hole by its API (`PATCH /api/config`, from standard input, never in a program's arguments)
  only while Pi-hole **has no password** yet: FTL refuses config changes from a command-line session (403), so there is no
  `cli_pw` sign-in. Otherwise `pihole setpassword`, whose argument list holds the password for a moment. An update never
  chooses a password. `docs/install.md` says both.
* Apt and dpkg answers that are read are asked for in the C locale (`LC_ALL=C`), and "installed" means
  `dpkg-query` says `install ok installed`.
* Installs `avahi-daemon` so the box answers to `<hostname>.local` and announces itself to the app (`SINKO_MDNS=0` skips both; see
  *Finding the box*), `unattended-upgrades` for Debian
  security updates (`SINKO_OS_UPDATES=0` skips; left alone when already installed, switched on or off) and, when the box has
  no time service at all, `systemd-timesyncd` (no battery-backed clock; another service that is installed but off is left to
  the owner, with a warning).
* `index.html` is installed with `@VERSION@` replaced by the release's version in the addresses of the page's scripts and
  style sheet (`/pb/app.js?v=3.0.0`) and in `<meta name="sinko-version">`: Pi-hole's web server lets a browser keep a static
  file for an hour, so every release changes every address. The web server ignores the query string.

### Migration from pihole-bahrain

Detected by `/opt/pihole-bahrain` or `/etc/pihole-bahrain` or the old units. Done by the new installer in this order:
read the old config (`PB_*` → `SINKO_*`, keep hostname/ip/lists/ref), stop + disable + delete the old units, install
the new files, `sinko setup` (re-registers every list under the new address, keeps groups, devices, rules, state),
install the new units, leave `/usr/local/bin/pihole-bahrain` as a symlink to `sinko` (with a one-line notice), and only at
the very end delete `/opt/pihole-bahrain` and `/etc/pihole-bahrain` (the running installer may live inside the old
`/opt/pihole-bahrain/src`). The old page (`generator` = `pihole-bahrain`) is replaced, never backed up as a user page.
Old boxes update themselves by running `pihole-bahrain update`, which clones `master` into `/opt/pihole-bahrain/src` (GitHub
redirects the old name) and runs the `install.sh` it finds there. When that checkout is inside the old program folder and the
box follows the releases (`SINKO_REF` latest or a version), the installer does not install the checkout: it fetches and
verifies the release first and lets the release's own installer do the work, so the box ends with a checksummed version, an
`/opt/sinko/src` and a rollback copy. If the release cannot be had (none published yet, no connection) it installs the checkout
as before and says so. A git checkout anywhere else, and a developer's `SINKO_REF=master`, are installed as they are.

## Shared state (`pb-state` group description, JSON)

Read and written by the page **and** by the scheduler. Both normalise with `parse_state` (Python, `bin/sinko`) /
`parseState` (JS, `web/`), unknown top-level keys are dropped, so every key must be known to both.
`tests/fixtures/state-cases.json` is the executable spec: `tests/test_state_contract.py` and
`tests/state-contract.test.js` run the same file against both parsers.

```jsonc
{
  "v": 1,
  "timer": null, "schedule": {...}, "scheduleActive": false,      // unchanged since 2.x
  "update": {
    "auto": false,            // page: install updates by itself, 03:00–05:00 box time
    "request": null,          // page: marker of "Update now": the time of the request, ms on the box's clock
    "checkRequest": null,     // page: marker of "Check again" (the same kind of marker)
    "latest": null,           // scheduler: newer version available ("3.1.0") or null
    "notes": null,            // scheduler: https://github.com/<slug>/releases/tag/v3.1.0 (the page only links this)
    "checked": 0,             // scheduler: epoch seconds of the last successful check
    "status": "idle",         // scheduler: idle | running | ok | failed
    "from": null, "to": null, // versions of the current/last attempt
    "at": 0,                  // epoch seconds of the last status change
    "error": null             // short reason when failed (≤ 200 chars, no secrets)
  },
  "power": {"request": null, "action": null},   // page: "reboot" | "poweroff" with a request marker (a time, as above)
  "telemetry": {"on": null},                    // null = not asked, true/false = the parent's answer (authoritative)
  "community": null,                            // scheduler: {"online": n, "at": epoch} after a successful ping
  "setup": {"done": false},                     // page: first-run checklist dismissed
  "learn": {"on": false},                       // page or `sinko learn on|off`: learning new addresses of blocked apps
  "terms": {"agreed": 0}                        // page: the version of the terms of use the parent agreed to (0 = none, 0-9999)
}
```

**The app's contract number (`api` in `/pb/box.json`, `BOX_API` in `bin/sinko`).** Raise it whenever `pb-state` gains or
changes a key, or any other behaviour the app relies on changes (a request it may send, what a field means, an address it
reads). The app refuses to write `pb-state` to a box whose `api` is higher than the one it knows, because every parser drops
the keys it does not know: an app that wrote back what it read would wipe the box's new fields. A lower or missing `api` (a box
older than 3.2) is the app's to handle. The page needs no such rule: it is installed with the program it belongs to.

**Request protocol.** A request marker is the time of the request in milliseconds on the **box's** clock: the page takes
the box's time from the `Date` header of Pi-hole's answers, so a phone with a wrong clock is no problem. The scheduler acts
when it is non-null and different from the value stored in `/var/lib/sinko/handled.json`; it first stores the marker there,
then clears it in the state, then acts (so a reboot request cannot repeat after the box comes back). The page never decides
anything: it only asks. Nothing in the state is ever used as a URL, path or command; updates always come from the repo
configured in `/etc/sinko/config`.

**A request is for now.** While the box's clock is believed, a marker that is a time (10^11 or more) and lies more than 15
minutes before or after the box's clock is dropped like a handled one (cleared from the state, never acted on; the log says so). A
marker that is not a time stays opaque and is acted on once, as before. The case this exists for is a restored backup: the
restore puts the backup's `pb-state` back, with every request that was waiting when the backup was made, until the page writes
today's fields over it again (`keepBoxFields`), and a scheduler pass can land in between. A request this box never handled
(a backup from another box, or from before later requests) looks new to the "different from handled" rule; its age tells it
apart. `tests/test_page_scheduler.py` makes a pass land in exactly that window.

The scheduler writes the state only when something changed (a write makes Pi-hole reload), and re-reads right
before writing (existing pattern in `Controller.tick`) so it never overwrites what the page just wrote.

## Update flow

1. **Check** (scheduler, 2 minutes after every start of the scheduler (the start after a power cut and the restart the
   installer causes included; nothing is persisted) and then every 24 h, or on `checkRequest`): GET the release API
   with a 10 s timeout in a background thread (never block the tick). Ignore drafts and prereleases. Semver compare
   against `VERSION`. Offline or rate-limited = silently keep the old answer, and ask again after `CHECK_RETRY` (30 minutes)
   plus up to as much, not tomorrow. Write `latest/notes/checked` if they changed or `checked` is older than a day. A box
   pinned to `vX.Y.Z` makes no API call (the release is the pin) and a box on a branch is never checked. Every number a
   parent-facing document quotes for this (`docs/privacy.md`, `docs/updating.md`, `docs/faq.md`) is pinned to the constants
   by `tests/test_docs.py`.
2. **Run** (on `update.request`, or `auto` inside the 03:00–05:00 window when `latest` is set and this version has
   not failed lately: a failure of the network or the disk (`transient`) is tried again after 30 minutes, any other
   failure waits 7 days): minimum 5 minutes between runs. Set `status=running, from, to, at`, clear the
   request, then start `sinko update --yes --from-panel` as a detached transient unit (`systemd-run --unit sinko-update
   --collect`; fall back to a detached subprocess). The runner survives the scheduler restart the installer causes.
3. **`sinko update`**: first require **more than 200 MB free** (`MIN_FREE_BYTES`, the installer's own number for an update, a
   rollback or a move from pihole-bahrain; a first installation needs more than 1 GB), before anything is downloaded and
   again after the downloads and the unpacked tree have used some of it: that failure is `transient`, says how much is free
   and that nothing was changed, and is `rolledBack` = `true` only after a self-check of the untouched box. Then download
   `sinko.tar.gz` + `.sha256` from the configured repo; verify the checksum; refuse any
   archive with a link, device, absolute or `..` member path, too many members or too much unpacked size, or without
   `sinko/VERSION`, `sinko/install.sh`, `sinko/bin/sinko`; refuse a version that is not newer unless `--force`; copy the
   tarball to `/var/lib/sinko/cache/` (the installed release plus the newest older one are kept); flush everything to disk;
   run the extracted `install.sh` with `SINKO_SRC` and `SINKO_NONINTERACTIVE=1`; then `sinko selfcheck --wait 90` in a **new
   process of the newly installed program**. If the installer or the self-check fails, **roll back** automatically by
   re-installing the previously cached version and checking that, and report `failed` with `rolledBack` = `true` only when
   the old version is back and passes its check (`false` when it is not, or there was no copy to go back to). A failure
   before the installer ran (download, checksum, space) is `rolledBack` = `true` only after a self-check of the untouched
   box passes. The stored `error` is short English for whoever helps, never a command. Finally write
   `update-result.json` (`status`, `from`, `to`, `error`, `at`, `rolledBack`, `transient`).
4. **Reconcile** (scheduler, every tick): if `status == running` and `update-result.json` exists (and is not older than the
   run), copy it into the state (`ok`/`failed`, `to`, `error`, `at`, `rolledBack`), delete the file, and clear `latest` when
   it is now installed. If `running` and the runner is gone (the update lock is free) for more than 3 minutes, a
   background self-check of the box decides: the new version in place and passing = `ok`; the old version still working =
   `failed` with `rolledBack` true; otherwise `failed` with `rolledBack` false ("did not finish").
5. `sinko rollback` re-installs the previous cached version by hand. `sinko update --ref vX.Y.Z` pins a release; the choice is
   saved only by an update that worked, and a failed `--ref` update (also after its rollback installer ran) leaves
   `SINKO_REF` as it was.
6. **Repair** (scheduler, a background look once a minute at `pb/version.txt`): an update cut off between the program's
   replacement and the page's swap leaves a program of one version and a page of another. When they have differed for
   `REPAIR_AFTER` (10 minutes) with nothing installing (no update lock, no installer lock, state not `running`), the box
   not removed on purpose, a believed clock and `/opt/sinko/src` holding this very version, the scheduler starts
   `sinko repair` as a unit of its own (the installer restarts the scheduler, so it cannot run inside it), at most once an hour
   (`repair.json`). `sinko repair` takes the update lock, requires the free space, runs the installer from `/opt/sinko/src`
   with the ref the box follows (nothing of Sinko is downloaded; the installer's `sinko setup` still runs `pihole -g`), checks
   the installed program and marks the cut-off update finished in the state (`ok`, or `rolledBack` true when it was the way
   back that was cut). A cut after the page swap, with page and program already agreeing, is not covered: the 3-minute check
   of step 4 reports it, and the scheduler's self-heal puts back missing groups and lists (once an hour).

`sinko selfcheck [--wait N]` (no DNS probing, exit ≠ 0 on failure, one line per check, waits up to N seconds for
"starting" to become "ok"): API reachable and logged in with the CLI password, the `pb-*` groups exist, every catalog list is
registered, **the scheduler has run: the same process up for at least 20 s, at least 2 finished passes of this version, a
heartbeat under 60 s old, and not crash-looping** (a unit that is merely "active" for a second between crashes does not
pass), every file `index.html` loads exists and is not empty (and every file the installer copies from the release's web
folder when the source is that version: the files directly in `web/` and in `web/fonts/`, no dotfiles; the check and
`install_files` must learn about a new web sub-folder together), and `pb/version.txt` equals `VERSION`. A check that cannot run
(an answer cut off by an FTL restart, say) is a failed check, and with `--wait` it is tried again.

## Learning new addresses

`Learner` (in `bin/sinko`, run by the scheduler's `Maintenance` once a minute while `learn.on` is true and the clock is
believed) reads the lookups since its last look from `/api/queries` and blocks a name for app *A* only when: the name was
answered and no list covers it; the model (`model/host-model.json`, read once) gives it at least `MODEL_THRESHOLD` for *A*;
*A*'s group is enabled; the name carries one of *A*'s own words (`zone()`); the same client address was refused a name of
*A*'s list within `Learner.WINDOW` (120 s, either way); the zone is not in `NEVER`, no enabled allow rule of the owner's
matches the name, and no taken-back rule covers it; *A* has learned fewer than `PER_APP_DAY` (20) today and the box holds
fewer than `MAX_RULES` (200). Pi-hole's privacy level hides names or clients: nothing is learned.

A learned rule is a deny **regex** `(^|\.)<zone with dots escaped>$` in group `pb-svc-<A>` (so it blocks exactly while *A*
is blocked), enabled, comment `pb-learned:<A> <YYYY-MM-DD>` (box time). Taking one back (`sinko learn forget NAME`) keeps
the rule, switched off, with comment `pb-learned-no:<A> <day>`, so it is never learned again. After a look that learned
something the DNS cache is cleared once. `setup` and the self-heal leave both kinds alone; `remove` deletes both; backup and
restore carry them like any rule. Nothing about it is sent anywhere.

The page reads the rules with the rest of its model (`GET /api/domains`, `PBCore.learnedRules`; `tests/fixtures/learned-rule-cases.json`
is the contract both readers run), shows them in *My box* (card `boxLearnCard`) with the switch (`learn.on`), and **Allow
again** writes what `sinko learn forget` writes (`PUT /api/domains/deny/regex/<regex>`: the same rule, switched off,
comment `pb-learned-no:<A> <day>`). Under the apps, one line counts what each app learned and opens that card.

## Savings ledger (pb-ledger)

The page's card *What Sinko did for you* shows, for today, this week and since its first day: ads and trackers stopped (and
what that saved: the page counts 50 ms of waiting and 10 KB of data per stop), how often each blocked app tried to open,
the nights bedtime was kept, the hours the children's internet was off. Pi-hole alone cannot give that: its long-term
database keeps only `database.maxDBdays` days (30 on a box Sinko set up, 91 by default), and nothing in it says how long
the internet was off or whether bedtime was kept. So the scheduler keeps a small private daily ledger and hands the page a
compact copy behind the parent password. **Never in a file under `/pb/`**: every device at home reads those without a
password, and `docs/privacy.md` (*What the box tells devices at home*) promises they say nothing about the children or the
rules. The copy is the comment of the group `pb-ledger`, which the page already reads with every `GET /api/groups` (every
30 s, signed in).

**Stops** (`read_stops`, run by `Maintenance._ledger` in a `BackgroundJob`, never on the tick thread). Right after the start
and then every `LEDGER_REFRESH` (15 minutes), read-only through `sql_rows` (`pihole-FTL sqlite3 -readonly`, the standard
library's `sqlite3` without it), with only whole numbers in the SQL:
`SELECT status, list_id, COUNT(*) AS n FROM query_storage WHERE timestamp >= <start> AND timestamp < <end> AND status IN
(<BLOCKED_STATUS>) GROUP BY status, list_id`, for [box-local midnight, now) and, from `LEDGER_SETTLE` (5 minutes) after
midnight, for the whole of every day of the last week that the ledger holds and has not read whole since it ended; such a
day is then final, but only once FTL has written its end to disk: FTL writes every `database.DBinterval` (a minute unless the
owner set more; a Pi-hole 5 setting in minutes becomes an hour) and keeps its last 30 seconds back, so a day is read "whole"
from `DBinterval` + `LEDGER_WRITE_LAG` (90 s) after it ended, and counted as it stands (and read again) before that. FTL 6 notes in `list_id` the list (for a
block-list status) or the rule (for a regex or denylist status) that stopped a lookup, in one column: a rule by its own
`domainlist` id (0 and up), a list as `-(adlist id + 2)` (-2 is list 0, -3 list 1; -1 is none; `adlist_of`, the same in
every FTL 6). The comments in `gravity.db` say whose:

| Status (QUERY_STATUS) | `list_id` points at | Counted as |
|---|---|---|
| 1, 9 (gravity, also by CNAME) | `adlist` `-list_id - 2` with comment `pb:<sid>`, `<sid>` in the catalog | `apps[sid]` |
| | `adlist` `pb:guard` | not counted (the outside-DNS guard) |
| | any other `adlist` (not `pb:`) | `ads` |
| | an unknown id, or `pb:` of an app this release does not know | not counted |
| 4, 10 (regex) | the block-everything rule `^.*$` (comment in `BLOCK_ALL_OURS`) | not counted (internet off, bedtime, pause) |
| | a rule with comment `pb-learned:<sid> <day>` | `apps[sid]` |
| | any other rule (the owner's) | not counted |
| 5, 11 (denylist) | the owner's exact rule | not counted |
| 6, 7, 8, 18 (upstream), 15, 16 | | not counted |

FTL names one list or rule, the first that matched, and two of its rules decide which: an exact entry on any of the client's
lists beats an ABP pattern (Sinko's app lists are ABP only, so a tracker name of an app that StevenBlack's list also holds
counts as an ad, which is what the card calls it), and of the deny regexes the first by id wins (Sinko's `^.*$`, made at
setup, comes before every learned rule, so while the internet is off a stop in a learned zone counts as internet off).

The table is the one with `list_id` (`PRAGMA table_info` of `query_storage`, then of `queries`). An FTL without it is read
`GROUP BY status, domain`: a block-list stop of a name on an app's list (`service_domain_map`) is that app's, of a name on the
guard list nobody's, of any other name an ad; a regex stop is an app's only under a zone the box learned for it. At a privacy
level of 1 or more (names hidden) that is impossible and the day is `null`. `null`, never 0, also when the database is off
(`database.maxDBdays` 0 or `files.database` empty), at privacy level 3 (no history), or when a database cannot be read. A
`null` never overwrites a count, and a day's count only grows (a smaller one means Pi-hole lost rows: a flush, its days limit).
**First run** (nothing counted yet): the `LEDGER_BACKFILL` (6) whole days before today are read too, each only when the
database holds the whole day (its oldest timestamp is before that day's midnight), so the week is full on the first day;
`since` is the earliest day counted. Such a day that is still missing later and came before `keptSince` is offered again (a
first run in the `LEDGER_SETTLE` after midnight must leave yesterday for its next read, and the days before it set `since`).
A past day the ledger holds without counts (only its time off) is read the same way. A day the box has nothing for is a gap.

**Time off and nights** (`Ledger.observe`, on every pass whose tick worked while `ClockGuard` believes the clock). `dt` is the
monotonic time since the last counted pass, at most `LEDGER_STEP_MAX` (120 s; the first pass after a start counts nothing),
shared between two days when it crosses midnight. It is added to the day's watched seconds, and to its off seconds while
`pb-offline` is enabled and at least one client is in `pb-kids` (asked of Pi-hole once a minute while it matters). While
`scheduleActive` is true, the night is the day bedtime started (`in_schedule`'s rule: a window that crosses midnight belongs to
the day it starts); `dt` is added to its watched seconds while a child's device exists, and to its off seconds while
`pb-offline` is enabled. `scheduleActive` is the tick's decision, made with its own clock a moment before the pass's: while it
is true and `in_schedule` says the window is already over (the last second of a bedtime, or times the parent has just edited),
the open night goes on under its own day, and no night is opened. The night closes when `scheduleActive` turns false or the
night's day changes: planned = the real seconds from that day's start time to the end time (`bedtime_seconds`: the night the
clocks go forward is an hour shorter than end − start, the night they go back an hour longer); `kept` = 1 when watched ≥ 0.9 ×
planned and off ≥ 0.97 × watched, 0 when watched ≥ 0.9 × planned, else `null`. A night that began before `keptSince` (the
first start ever came in the middle of it) is closed without a verdict. An open night is kept in the file across a restart.
`keptSince` is the first day this counting ran. (A night needs a child's device: with none, bedtime kept nobody's internet
off, and the card would claim kept nights for an empty home.)

**`/var/lib/sinko/savings.json`** (root only, 0600, `atomic_write`; a corrupt or foreign file is logged and replaced, it never
stops the scheduler). Written with each read of the stops (or every 15 minutes should that job hang) and on a clean stop
(`Scheduler.close` → `Maintenance.close`), so a power cut loses at most 15 minutes. Version 1:

```jsonc
{
  "v": 1,
  "counted": 2,                        // how the stops were counted (LEDGER_COUNTED); see below
  "since": "YYYY-MM-DD" | null,        // first day with stop counts
  "keptSince": "YYYY-MM-DD" | null,    // first day the scheduler counted time off and nights
  "adLists": 1 | null,                 // switched-on block lists that are not Sinko's, from gravity.db
  "days": {                            // box-local days; LEDGER_KEEP_DAYS (35), today included
    "YYYY-MM-DD": {"ads": 12345 | null, "apps": {"tiktok": 40} | null, "final": true,   // read whole after the day ended
                   "off": 32400.0, "seen": 86400.0,                                       // seconds off, seconds watched
                   "kept": 1 | 0 | null,                                                  // the night that started that day
                   "recount": true}                                // only while it waits to be counted again (below)
  },
  "night": {"d": "YYYY-MM-DD", "seen": 3600.0, "off": 3600.0, "planned": 32400} | null,  // the bedtime that is on
  "before": {"ads": 0, "apps": {}, "off": 0.0, "nights": 0, "kept": 0}                   // the rows folded away
}
```

`counted` says how the stops were counted. 3.3.0 wrote none and read a block list's `list_id` as the list's own id, so its
ads and app tries are 0 where they were not: a file without `counted: 2` keeps its time off, nights and start days, and its
stop counts (`ads`, `apps`, `before.ads`, `before.apps`) become `null`. Each of its days is marked `"recount": true` (kept in
the file until it is read) and not final; `windows` offers every such day, however old, `fold` does not close it, and
`read_stops` reads it while the database holds any of it (a day from `keptSince` on, which 3.3.0 read as it went; `"part"`)
or the whole of it (a day before, as the first run's backfill), the mark going with the first count. What the database no
longer holds stays `null`.

Rows older than 35 days are folded into `before`, so the totals outlive both the rows and Pi-hole's own limit; a row older than
a week that was never read whole is final as it is.

**Publishing** (`Maintenance._publish_ledger`, main thread). The group `pb-ledger` is made when missing (disabled, and no client
ever joins it). It is written only when what it would say differs from what the group holds (the time `at` apart) **and**
`LEDGER_PUBLISH_EVERY` (60 minutes) has passed since the last write, or it is the first look since the start (once the first
stops are in), or the box's day changed, or an off period or a bedtime night just ended. Every group write makes Pi-hole reload
its lists: never more often. Because it compares with the group itself, a restored backup or a hand edit is put right at the
next such moment (at once after a start). Never while an update runs (`update.status` running or the update lock held, as for
`box.json`), never after `sinko remove` (the `removed` flag). **After midnight** nothing is written, whatever made it due,
until a read of the stops that began in the new day is back (one that fails or finds the database off counts too): a copy
made earlier would say that today's stops are `null` (not known), and the card would show that until the next write, an hour
later. The day's first read is made due for `LEDGER_SETTLE` after midnight, so it also reads yesterday whole and the new day's
first copy has both; should it not come back, the copy goes `LEDGER_REFRESH` after it was due. Meanwhile the page still has
the copy of the day before (`today` is yesterday) and says that today's numbers are not in yet. A write that fails (Pi-hole
busy, its database locked by a list rebuild) changes none of this bookkeeping: it is tried again on the next pass. The
comment, compact JSON, version 1:

```jsonc
{
  "v": 1,
  "at": 1793000000,                  // epoch seconds, box clock, when these numbers were computed
  "today": "YYYY-MM-DD",             // box-local day of "at"
  "since": "YYYY-MM-DD" | null,      // first box-local day that has stop counts (ads/apps); null = none yet
  "keptSince": "YYYY-MM-DD" | null,  // first day the scheduler itself counted off-time and bedtime nights
  "adLists": 1,                      // enabled block lists (adlists) that are NOT Sinko's own (comment not starting "pb:");
                                     // 0 => the page says there is no ad list
  "days": [                          // the last 7 box-local days at most, OLDEST FIRST, the last one is "today";
                                     // a day the box has nothing for is simply absent (a gap)
    {"d": "YYYY-MM-DD",
     "ads": 12345 | null,            // stops by general block lists (any adlist not "pb:..."), whole home; null = unknown
     "apps": {"tiktok": 40},         // stops by the family's app lists ("pb:<sid>") and learned rules ("pb-learned:<sid>"),
                                     // catalog apps only, at most 8, biggest first; {} when none or unknown
     "offSec": 32400 | null,         // seconds the children's internet was off that day, as the scheduler saw it;
                                     // null before keptSince, and on a past day the scheduler did not watch
     "kept": 1 | 0 | null}           // the bedtime night that STARTS on this day: 1 kept, 0 planned and watched but not
                                     // kept, null no bedtime that night or not watched enough (also while it is on)
  ],
  "tot": {"ads": 3000000 | null, "apps": {"tiktok": 9000}, "offSec": 6500000 | null, "nights": 200, "nightsKept": 187}
                                     // running totals since "since" (ads, apps) and "keptSince" (offSec, nights)
}
```

Integers only, under `LEDGER_MAX_CHARS` (4000) characters: a long one loses each day's smallest apps first, then the oldest
days; the totals stay. The page validates everything strictly and ignores unknown keys; `tests/test_savings.py`
(`check_contract`) checks every copy the box and the mock make against the same rules. `pb-ledger` is not part of the app's
contract (`BOX_API` is unchanged): the page that reads it is installed with the program.

**Lifecycle.** A Pi-hole backup carries `pb-ledger` like every group; `sinko remove` deletes it with every `pb-` group;
`uninstall.sh` deletes the state folder; `tools/seal.sh` removes `savings.json` (named in its plan even before the stopping
scheduler writes it, and checked at the end) and resets Sinko's objects in Pi-hole with `remove` and `setup`, so a ready-made
box does not ship the golden unit's history. Pi-hole's own older copies of `gravity.db` (`gravity_backups`, renewed one by one
at each list refresh) still hold the group after an uninstall, which leaves Pi-hole's files alone: `docs/privacy.md` says so
and how to delete them; `seal` empties that folder. `sinko diagnose` prints a summary (counts only). `tests/mock_pihole.py`
`seed_ledger()` makes a demo week through the same classifier, ledger and serialiser (on a set-up store whose bedtime is off it
switches the demo bedtime on, so the page and the card agree; the totals before the week follow the store's bedtime).

## Terms of use

After the claim screen or a sign-in, and before the app, the page shows `#terms` while `terms.agreed` is below
`TERMS_VERSION` in `web/app.js` (now 1; the text is the four points on the screen and [`docs/terms.md`](../terms.md), linked
from it and from *About* through `links.json` `terms`). It carries two switches: `learn.on` and, only when `box.json` says
`"counter": true`, `telemetry.on`. The first time (`terms.agreed == 0`) both start on, except the counter when
`telemetry.on` is already `false`; on a later version they start as the state has them. **I agree, continue** writes
`terms.agreed = TERMS_VERSION`, `learn.on` and (when shown) `telemetry.on` in one `writeState`, then opens the app. Neither
the scheduler nor the CLI reads `terms`: the two switches keep their own fields as the only authority, so the counter still
sends nothing while `telemetry.on` is `null`. A restore keeps the box's own `terms` (`keepBoxFields`), and a sealed image
starts with the default state, so a buyer is asked. Raise `TERMS_VERSION` (and the version line in `docs/terms.md`) only
for a change of the terms that a parent should see again.

## Power requests

`power.action` `reboot` → `systemctl reboot`; `poweroff` → `systemctl poweroff`, executed after the marker is stored
and the state cleared. The page warns that the children's internet stops while the box is off. **A request that arrives
while an update runs is dropped** (marker stored as handled, cleared, logged), never held and never fired later; the page
disables the two buttons while an update runs or is requested, and withdraws an unanswered request.

## Address watch

The scheduler compares the default-route IPv4 with `SINKO_IP` every 5 minutes; when it changed it runs the equivalent of
`sinko configure --ip <new> --hostname <name>` and rewrites `SINKO_IP`, so the local name keeps pointing at the box after
the router hands out a new address (and after a ready-made unit is switched on in a different network).

## Finding the box (Bonjour)

The app finds boxes on the home network by DNS-SD over mDNS. When `SINKO_MDNS=1` (the default) and avahi is installed, every
installer run writes `/etc/avahi/services/sinko.service` (mode 644, through a temporary `sinko.service.sinko-new` that avahi
does not read, and only when the content changed):

* service type `_sinko._tcp`, port 80 (where Pi-hole serves the page as it installs itself; an own Pi-hole moved to another
  port is not followed), instance name `<name replace-wildcards="yes">%h</name>`, so a new host name needs nothing more (`firstboot.sh` restarts avahi). When two
  boxes share a name, avahi renames the second host (`sinko-2.local`) and the instance follows; box.json's `hostname` still
  says the system's name then, so the app goes by the host the service resolves to and tells boxes apart by `boxId`;
* TXT `v=1` (the version of these records), `version=<x.y.z>` (the installed release), `path=/` (the page), `info=/pb/box.json`
  (what to read next: the version, `api`, `boxId` and the rest are there, and box.json is what the app believes; the records are
  only what a list shows before it asks).

avahi-daemon notices the file by itself: on Linux it watches its services folder with inotify (`avahi-daemon/main.c`) and on
every change reloads each service file whose modification time (whole seconds) differs from the one it loaded
(`static_service_load`). The installer also runs `systemctl --no-block try-reload-or-restart avahi-daemon.service` when it
wrote or removed the file, which costs nothing and covers an avahi that runs without the watch (it warns and goes on when it is
out of inotify instances). The step runs after the new scheduler has proved itself, so a failed update does not announce its
version. `SINKO_MDNS=0` and `uninstall.sh` remove the file (only one that carries the installer's comment) and ask avahi to
reload; avahi itself is left alone, as before. A box rolled back to a release older than 3.2 keeps the file of the newer one
until its next update (its version record is then wrong, which is why the app reads box.json).

**Not announced as `_http._tcp`.** It would be harmless (another record on the network, the same port and path) but it buys
nothing: no phone browser lists `_http._tcp` services, parents open the box by `<hostname>.local`, and the app looks for
`_sinko._tcp`. What it would add is the box in every list of web devices on the network (home-automation hubs, network
scanners, NAS tools), which then probe it, and a second record to keep right.

## Optional anonymous counter ("boxes online")

* Nothing is sent until the parent says yes (`telemetry.on == true` in the state). The terms screen at first sign-in asks,
  with the switch on (off where `telemetry.on` is already `false`), and so does the installer prompt (default yes);
  `sinko telemetry on|off|status|payload|reset-id` mirrors it. Endpoint from `SINKO_TELEMETRY_URL` (https, or http to
  loopback in tests); empty = not configured: nothing is ever sent, and `box.json` says `"counter": false`, so the page
  hides the card and the choice on the terms screen. Switching off sends the forget request below.
* Every 6 h ± 30 min (first one 5 minutes after start) in a background thread with a 10 s timeout:
  `POST {url}/v1/ping`, `Content-Type: application/json`, body ≤ 512 bytes:
  `{"id": "<32 lowercase hex>", "v": "3.0.0", "hw": "orangepi-zero3|raspberrypi|x86|other"}`.
  `id` is random, stored in `/var/lib/sinko/install-id`, derived from nothing on the device. Nothing else is sent: no
  domains, device names, addresses, children, rules, language or timezone.
  `hw` comes from `/proc/device-tree/model` ("Orange Pi Zero 3" → `orangepi-zero3`, "Raspberry Pi" → `raspberrypi`)
  or the CPU architecture (`x86_64` → `x86`), else `other`.
* Response: `{"online": <int>, "total": <int>}`; stored as `community` in the state when the numbers are sane.
* Worker (`telemetry/`) stores `id, first_seen, last_seen, version, hw, country` (country from Cloudflare's
  `CF-IPCountry`; the IP is never stored or logged by the Worker) in D1. Ignores a ping from an id seen < 10 minutes
  ago, rejects malformed bodies, purges ids unseen for 180 days (cron).
  * `GET /v1/stats` → `{"online","active7d","total","countries","versions":{},"hw":{},"downloads":<int|null>,"generatedAt"}`
    (online = seen within 12 h; downloads = sum of GitHub release asset downloads, cached 15 min; CORS `*`,
    `Cache-Control: public, max-age=60`).
  * `GET /badge/online.json`, `/badge/total.json`, `/badge/downloads.json`: shields.io endpoint JSON
    (`{"schemaVersion":1,"label":"…","message":"1.2k","color":"0F766E"}`).

## Parent page contract

* Same-origin Pi-hole API only (`/api/...`); logic stays dependency-free vanilla JS, English + Arabic (RTL), no
  build step. Every string exists in both languages, with the same `{placeholders}`; the copy test bans technical
  words outside the "how it works" sheet.
* New in 3.0: **My box** sheet (update, health, network addresses, change password, backup/restore, restart/shut
  down, anonymous counter, about; since then also learning new addresses of blocked apps), **first-run claim** screen, **setup checklist** card, update banner when a newer
  version exists. Since then also the **terms screen** (see *Terms of use* below).
* Pi-hole API calls used by the new features (from the FTL OpenAPI specs; copies in the maintainers' scratch notes,
  upstream: `pi-hole/FTL/src/api/docs/content/specs/*.yaml`):
  `GET /api/auth` (no `sid` + `session.valid` true ⇒ no password set ⇒ claim screen; FTL v6.8 and later answer a box that
  has no password this way only for a `Host` that is an address, `localhost`, `pi.hole`, `webserver.domain` or the host name
  (alone, or followed by `.local` or `dns.domain.name`), and 401 otherwise, so the claim screen opens by the address or
  `<hostname>.local`, not by the local name `SINKO_HOSTNAME`. Sinko does not set `webserver.domain` to that name: FTL redirects
  `/` on `webserver.domain` to `/admin/` and names the HTTPS certificate it makes after it),
  `PATCH /api/config` with `{"config":{"webserver":{"api":{"password":"…"}}}}` (write-only property; the session is
  invalidated afterwards, so sign in again), `POST /api/auth` to check the current password before a change (with two-factor
  sign-in: a wrong password is 401 with a `session`; a missing code 400, a wrong or reused code 401 with only an `error`,
  `Invalid 2FA token` or `Reused 2FA token`; `src/api/auth.c`), `GET /api/info/system`, `/api/info/sensors`, `/api/info/host`,
  `GET /api/teleporter` (zip), `POST /api/teleporter` (multipart `file` + `import` JSON), `GET /api/dns/blocking`, and
  `GET /api/info/version` for **About** (the core's local version, read each time the sheet opens, shown as "Pi-hole v6.x"
  only when it is a plain release number; a failure or a development build leaves the row out), and `GET /api/domains` and
  `PUT /api/domains/deny/regex/<regex>` for what the box learned (*Learning new addresses*).
* **What Sinko did for you** reads the comment of the group `pb-ledger` (see *Savings ledger (pb-ledger)*) from the
  `GET /api/groups` the page makes every 30 s anyway; nothing else is asked for it. A missing or malformed group (an older box,
  nothing counted yet, a hand edit) shows no numbers. The card never writes the group.
* Backup = the whole Teleporter archive (it contains the password hash: the page says to keep it private).
  Restore imports **only** the gravity tables (`group, adlist, adlist_by_group, domainlist, domainlist_by_group,
  client, client_by_group`) and not `config`, so a restore never changes the address, upstreams or password.
* Update links: only `update.notes` values that `parseState` accepted are rendered as links.
* The page knows its own release from `<meta name="sinko-version">` (the installer stamps it; the placeholder stays in
  development and the page then goes by the box's `pb/version.txt`). A stamped page that finds the box on another version
  reloads itself once per version per tab (at start and when the phone returns to it, never while a dialog is open, a
  bedtime is typed or an update runs). The addresses of its scripts and style sheet carry `?v=<version>`.
* The counter line ("This box is one of N Sinko boxes online.") is shown from two boxes up, exactly two has its own wording,
  and the Arabic puts the number last. One tagline per language, from `tools/make-brand.py` (`TAGLINE_EN`, `TAGLINE_AR`);
  `tests/test_docs.py` and `tests/test_copy.py` compare the README, the site and the page with it.

## Ready-made image (Orange Pi Zero 3)

Golden-unit method: install Sinko on a fresh Armbian minimal (Debian Trixie) image, run `tools/seal.sh`, copy the SD
card to an `.img`, compress, flash many cards. Sealing removes everything that must be unique or private (SSH host keys,
machine-id, install-id, the box id and the page's `box.json` that shows it, query history, what the scheduler counted for the
family (`savings.json`; `pb-ledger` goes with Sinko's other objects), parent password so the page offers the **claim screen**,
shell history, logs),
locks the default root password / password SSH logins, removes Armbian's first-login wizard file, and arms
`sinko-firstboot.service`. First boot regenerates host keys, sets the host name, makes the box its own box id and writes
`box.json` with it (`sinko box-info --write`, once, before the address: a retry keeps the id the app may know already),
repairs the local name/address for the actual network (`sinko configure`), refreshes `SINKO_IP`, then deletes the flag.
`docs/product-image.md` is the seller's procedure.

The seal refuses a unit that is not ready (it names every problem; the account check is made again before the last step so
`--skip-checks` cannot bypass it): a service or timer not enabled, no avahi, automatic security updates not installed or not
switched on (unless `SINKO_OS_UPDATES=0`), no time service, a unit pinned to a version or following a branch (its boxes would
never be offered an update), a fixed address, another account than root that can log in on the console. Its watchdog drop-in
sets `RuntimeWatchdogSec=15` and `RebootWatchdogSec=15` (the Allwinner driver takes 16 s at most). In systemd 257 PID 1
disarms the watchdog before a power-off (`watchdog_timer` stays 0 for `poweroff` and `halt`, and `watchdog_setup(0)`
disarms) and keeps it armed for a reboot, where systemd-shutdown feeds it once per unmount pass and not during its first
sync; whether the board's driver lets it be disarmed (`CONFIG_WATCHDOG_NOWAYOUT`) only the board shows. The zero-fill counts
as done only on "No space left on device"; a leftover zero file is deleted by the next seal and by `firstboot.sh`.

## Things only real hardware can prove

Listed in `docs/hardware-test-checklist.md`; nothing in CI exercises: a real Pi-hole v6 (password config, teleporter,
sensors), systemd behaviour (`systemd-run`, reboot from the service), Armbian first boot, mDNS on phones and the app finding
`_sinko._tcp`, the Orange Pi Zero 3's thermal sensor path, and a real GitHub release round trip. Also the things that depend on how slow a
real card and board are (the 20-second self-check, the restore window, the 15-second watchdog during a restart), on the
board's driver (Shut down and `CONFIG_WATCHDOG_NOWAYOUT`), on the real web server (the one-hour cache and the `?v=` addresses),
and on a cut of the power at the one moment between the program's replacement and the page's swap.

## Amendments agreed after the first review (these override the text above where they differ)

**State**: `update.rolledBack` is `true` (the previous version was put back and passes the self-check), `false` (the update
failed and going back did not work, or there was nothing to go back to, or the runner died) or `null` (not known / no
failure). Only the page decides what a parent reads from it: "the previous version is back" is shown only when it is
`true`. `update.error` is technical text for whoever helps (English, at most 200 characters, **never a command to type**);
the page does not print it as the reason in the parent's language. Both parsers are strict (ASCII digits, whole-string
regular expressions, no NaN/Infinity tokens, `timer.snapshot.services` must be an object, and an integer too big for a double
(more than 308 digits, which the page's JavaScript reads as Infinity) is refused by both, losing only its own field and never
the whole state); `tests/fixtures/state-cases.json` is the spec. The parsers drop top-level keys they do not know, so an older
component (after a rollback, or a phone that still holds the old page) wipes a field that a newer release added: that is
accepted, and it is why every key must be known to both sides in the release that introduces it.

**`/pb/box.json`** (written by the box program as root, mode 644, atomically; read by the page and the app without signing in):
`{"v":1,"api":1,"version":"3.2.0","boxId":"<32 hex>","hostname":"sinko","ip":"192.168.1.50","tz":"Asia/Bahrain","utcOffset":"+03:00","counter":true,"mdns":true,"at":1790000000}`.
`api`, `boxId` and `hostname` are additions of 3.2, so `v` stays 1, and a reader treats each as absent when it is missing or
malformed (`parseBoxInfo` gives 0 or ''). `api` is the app's contract number (*Shared state*). `boxId` is the box's own random
number (`/var/lib/sinko/box-id`), so the app knows the box again after its address changed. `hostname` is the system's host
name as avahi announces it (`/etc/hostname`, the part before the first dot, small letters; null when it is not a plain
name), so the app can show and try `<hostname>.local`. Until 3.1 the file identified nothing; it now tells one box from
another, on purpose. It is public on the home network, and the host name on an own install is the owner's choice and can say
something about the family, but avahi already announces that name to the same network. Nothing else about the family is in
it: not the local name `SINKO_HOSTNAME`, the children, the rules, or the counter's id or address.
`ip` is the default-route IPv4 (what the router's DNS setting needs; the page never puts a *name* there), `counter` is
"the counter address is configured", `mdns` is "avahi answers for this host", `at` is the box clock when it was written.
Written by `sinko box-info --write` (the installer calls it after the page swap; `sinko configure` and the address watch call
the same code) and refreshed by the scheduler every 5 minutes (only content changes or a 10-minute age cause a write: it is
also the **heartbeat**: the page treats a box.json whose `at` is more than 20 minutes behind the box's own clock as "the
scheduler is not running"). A missing file (an older box) disables every feature that needs it; nothing breaks.

**Counter: switching off forgets.** When the answer becomes "no" (page, `sinko telemetry off`, or `reset-id`), the box sends
`POST {url}/v1/forget` with `{"id":"<32 hex>"}` (same validation, same transport rules as a ping; answer `200 {"forgotten":true}`
whether or not the id was known), then deletes its `install-id`. If the request fails it keeps the id plus a
`forget-pending` marker in the state dir and retries every ping interval until it succeeds. The Worker deletes the row.
No shell is needed anywhere in this procedure (ready-made boxes have no login).

**Update source**: `SINKO_RELEASE_BASE` and `SINKO_RELEASE_API` must be https (http only to a loopback address under the test
hooks). The installer's and the updater's lock lives in the state dir, never in `/run/lock`. `sinko update --ref X` pins the box
(it is saved as `SINKO_REF`); `--ref latest` follows releases again; the command says so.

**Migration**: a legacy `PB_REF=master` is the 2.x default, not a choice: for the official project it becomes
`SINKO_REF=latest`. A kept lists address (the old `raw.githubusercontent.com/iret33/pihole-bahrain/...`) is **kept**, so
no list is deleted or re-registered during migration (zero unfiltered window; GitHub's rename redirect serves it); a lists
address inside the old app folder is rewritten to `/opt/sinko/lists`. The old scheduler is stopped (not disabled) until the
new one runs. A pre-existing `^.*$` deny rule that is not Sinko's (by comment) keeps its comment and enabled flag, gains
Sinko's groups, and is never deleted by `remove`.
