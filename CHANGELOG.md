# Changelog

All notable changes to Sinko. Versions follow [Semantic Versioning](https://semver.org); the newest release is at the top.
Boxes learn about a release from this repository's GitHub releases, whose notes are the section of this file.

## [3.3.0] - Unreleased

### Changed
- **A new look for the page, built around one button.** The page now looks like the control panel of a home appliance:
  a calm warm grey, flat panels, keys you can see are keys, and one orange key at the top: **Turn internet off**. It
  switches the internet off for the children's devices at once; the whole panel goes dark, and the key says **Turn it
  back on**. The panel always says, in one sentence, whether the children's internet is on or off and when it comes back:
  at the end of a break, when bedtime ends, or when you turn it back on. Light and dark, in English and Arabic.
- **Off for a while, from the same panel.** Beside the big key: **Off for 30 min**, **Off for 1 hour** and, in the
  evening and at night, **Off until** the morning (when your bedtime ends, or 7:00 without one); in the daytime that key
  is **Off for 2 hours**. **Another length** sets any other length. The *Offline break* quick mode is gone: these keys
  do the same. The quick modes left are *Homework* and *Free time*.
- **Apps: Allow or Block, in words.** Each app has two keys, **Allow** and **Block**, instead of a tile that changed
  colour. The blocked ones stand out down the list.
- **Bedtime in one sentence.** "Off at 21:00, back on at 6:30, Sunday to Thursday." The switch takes effect at once;
  the times and nights are under **Change times and nights**.
- **The live picture moved behind See it live.** The animated picture of what the box checks and stops now opens over
  the page, from **See it live** (in the new card and at the bottom of the page), so the page itself stays calm. The
  phone's Back button closes it.

### Added
- **What Sinko did for you.** A new card on the page, for *Today*, *This week* and *since the box started counting*:
  how much less you waited for ads, how much data that saved, how many ads and trackers the box stopped, how often each
  blocked app tried to open, how many nights bedtime was kept, how long the children's internet was off, and a chart of
  the ads stopped each day. **How we count** explains every number: about 50 ms of waiting and about 10 KB of data for
  each ad or tracker stopped (low estimates, the first one Brave's published figure). Type what 1 GB of data costs you
  and the card also says what the data saved was worth; that price stays on your phone.
- **The box keeps a small daily summary for this card.** Counts only (by app for the blocked apps): no websites,
  addresses or device names. It is kept on the box (and in its backups) for as long as Sinko is installed and never sent
  anywhere. The privacy statement says exactly what it holds.

### Fixed
- After saving a bedtime, later changes made elsewhere (another phone, a timer that ended) now show in the bedtime
  fields again without reloading the page.

## [3.2.1] - 2026-10-26

### Added
- **Terms of use at first set-up.** After you choose the parent password (or the first time you sign in after this update),
  the page shows short terms of use, in English and Arabic, before it opens. **I agree, continue** accepts them. The full
  text is in [`docs/terms.md`](docs/terms.md), linked from that screen and from *My box*, *About*.

### Changed
- **Learning new addresses of blocked apps and the anonymous counter now start switched on.** Both are choices on the
  terms screen, already switched on; switch either off there before you agree, or at any time later in *My box*. The
  counter still sends nothing until you have answered, starts switched off on a box where you already said no to it, and
  is not offered at all on a box that has no counter address. The setup list no longer asks about the counter.
- The installer's counter question now suggests yes (`[Y/n]`).

## [3.2.0] - 2026-10-23

### Added
- **The Sinko app can find the box at home.** The box announces itself on the home network (Bonjour, the way printers
  do) with its name, its Sinko version and where its page is, so the coming Sinko app for phones can list it without
  being told an address. On your own box, `SINKO_MDNS=0` when you install switches it off, together with the `.local`
  name, and removing Sinko removes the announcement.
- The box's small information file (`/pb/box.json`, which any device at home can read) now also gives the box's name
  (the one that ends in `.local`), a random number the box makes for itself so that the app knows it again after the
  router gave it a new address, and the number of the contract between the box and the app. That number is not the
  counter's code and is never sent anywhere; a ready-made box makes its own when it is first started. On a box you set
  up yourself the name is the one you gave the computer, so if it says something about your family, devices at home can
  read it, as they already could through the `.local` name. The privacy statement says this.

### Fixed
- **Changing the password with two-factor sign-in on.** When the 6-digit code was wrong, or had just been used, *My box*
  said nothing and the button simply came back. It now says "Enter the password and the 6-digit code." and puts you in
  the code field.

### Known limits
- A box that has no password yet opens its welcome screen at `http://sinko.local/` and at its address. With Pi-hole's
  FTL 6.8 or newer, `http://family.lan/` shows the sign-in instead until a password is chosen, because Pi-hole then
  answers only for its own names.

## [3.1.0] - 2026-10-14

### Added
- **The box can learn new addresses of the apps you block** (optional, and off until you switch it on in *My box*). Apps
  keep adding new addresses, and the block lists cannot always keep up. When this is on, a small AI model on the box
  looks out for them: when a child's device has just been stopped from opening an app you blocked and then asks for a new
  address that belongs to that app, the box blocks that address too, for as long as the app is blocked. At most 20 new
  addresses of an app a day. *My box* lists what was learned, with **Allow again** for each, and a line under the apps
  says which apps learned something. What it learns stays on the box as rules and is not sent anywhere. On your own box,
  `sudo sinko learn` does the same from the command line.
- For maintainers: `tools/suggest-hosts.py` trains the same model on the block lists and lists the popular names it
  believes the lists miss, for a person to check on a device; a workflow runs it once a month. How it works and what it
  gets wrong: `docs/maintainers/host-model.md`.

## [3.0.4] - 2026-10-08

### Fixed
- **Blocked apps are blocked on more of what they use.** Instagram, YouTube, X, TikTok, Facebook, ChatGPT, Fortnite,
  PUBG and Discord now have the hosts their apps were seen to use that the lists missed (for example Instagram and
  YouTube video and sign-in servers). Every list was checked against a real Pi-hole with each service blocked on its own
  device: every listed host and every subdomain of it is blocked, and no service blocks another.
- Nine names that no longer resolve on public DNS were removed from the PlayStation, Xbox and Discord lists.

### Known limits
- A block stops new lookups. An app that already has a connection open keeps working until that connection drops.
- A device has to be added on the box before a block applies to it.
- Instagram images come from a host under the shared `fbcdn.net` domain. It is not blocked as a whole, because that would
  also block Facebook and Messenger images.

## [3.0.3] - 2026-10-07

### Changed
- **The live picture is now a circuit board.** Each device is a chip, the family box sits in the middle and the internet
  is a connector at the bottom. The wires now show what really happens: a device asks the box, and the answer always comes
  back from the box along the edge of the board, never straight from the internet. When the box needs to look an address
  up, it asks the internet on one wire and gets the reply on another. A blocked app falls into a black hole and goes
  nowhere. Small lights travel the wires: amber for a question, green for an answer, blue for an answer the box already
  knew, and red with ✕ for a no. The picture mirrors for Arabic and fits a phone screen.

### Added
- The project website has a step-by-step setup guide for parents: plugging in the box, powering it from the router's USB
  port, finding it, pointing the router to it and adding the children's devices.
- `tools/mirror/` sets up a copy of the releases on `updates.ioai.bh`. Boxes on this version still update from GitHub.

## [3.0.2] - 2026-10-07

### Fixed
- **My box no longer says an update failed when it did not.** After a rollback by hand (`sudo sinko rollback`) and then an
  update by hand (`sudo sinko update`) that worked, the page kept saying "the update did not finish, the previous version is
  back" for a week, although the newer version was running. An update by hand now tells the page that it worked, as an update
  from the page always did; and the page no longer shows "the previous version is back" when the version that failed is the
  one running.

## [3.0.1] - 2026-10-07

### Added
- **The anonymous "boxes online" counter is running** (`https://sinko-counter.sabdulla.workers.dev`). A box on this version asks the
  parent once, in *My box* and in the first-run checklist, whether it may be counted; until the parent says yes it sends
  nothing, and switching it off deletes the box's record at the counter. What is sent and when is unchanged from
  [`docs/privacy.md`](docs/privacy.md). The README badge and the project website show the count.

### Changed
- Every action in the project's GitHub workflows is pinned to a commit, and `lists/` has its own line in `CODEOWNERS`,
  so a change to the block lists that every box downloads is reviewed like code.

## [3.0.0] - 2026-10-06

Sinko 3.0 is the first public release: the project has a new name, a parent page that looks after the box by itself, and
everything needed to ship it on a ready-made Orange Pi Zero 3.

### Changed
- **New name: Sinko** (was pihole-bahrain, then "Family Internet"). The command is `sinko`, the code lives in
  `/opt/sinko`, settings in `/etc/sinko/config`, the services are `sinko.service` and `sinko-lists.*`, and the
  installer variables start with `SINKO_` instead of `PB_`. Pi-hole groups, lists and rules keep their internal `pb-`
  prefix, so nothing already set up is lost.
- Installing and updating now use a **checksum-verified release archive** from GitHub Releases instead of cloning the
  repository; `SINKO_REF=master` still installs a branch for developers. The checksum comes from the same place as the
  archive, so it protects against a damaged download, not against whoever controls the repository: `SECURITY.md` now says
  who is trusted when a box updates, and that releases are not signed yet.
- **The privacy statement says what leaves the box.** Pi-hole passes the names of sites it cannot answer itself to its
  upstream DNS service (Cloudflare for Families on a new Pi-hole that the installer sets up), which therefore sees site
  names and the home's internet address; the statement, the FAQ, the seller's guide and the website said otherwise. It
  also states the retention of Pi-hole's own history precisely (30 days only on a Pi-hole the installer sets up). It says
  how often the box asks GitHub (about two minutes after it starts, about daily, and again within the hour when GitHub could
  not be reached) and that an update also refreshes the block lists and fetches the one small file the doctor check uses.
- The install command is written in one form everywhere (`--proto '=https' --proto-redir '=https'`, also on the website);
  the README has its **Install** section again; the page, the README, the website and the social preview say one tagline
  per language ("Calm internet for the family" · «إنترنت هادئ للعائلة»).

### Added
- **My box** in the parent page: update (check, update now, automatic at night), box health, addresses, change the
  parent password, backup and restore, restart and shut down, the anonymous counter question, and About.
- **Updates from the page**, with checksum verification, a cached copy of the previous version, an automatic self-check
  and automatic rollback if the new version does not work. `sudo sinko update`, `sinko rollback`, `sinko selfcheck`.
  The page says "the previous version is back" only when it is; an update that stops halfway (a power cut) is judged by
  a self-check after about three minutes. `sudo sinko update --ref v3.0.1` **pins** the box to a version (the command says
  so, and `--ref latest` follows releases again). A request from the page is for now: the box ignores one that is more than
  15 minutes old by its own clock, which keeps the old "update" or "restart" inside a restored backup from firing.
- **First-run set-up** for ready-made boxes: a welcome screen to choose the parent password, and a short checklist
  (router, first device, counter question).
- The box **keeps its local name working** when the router gives it a new address, and is reachable as
  `<hostname>.local` (Avahi).
- An **optional, anonymous "boxes online" counter**, off until the parent says yes (see `docs/privacy.md`), a download
  count from GitHub Releases, and a project website. Switching the counter off **deletes the box's record** at the counter
  (the box asks it to forget its code; no shell is needed). The project's counter service is not running yet, so a 3.0.0
  box never asks the question and never sends anything; a later release switches it on.
- `tools/seal.sh` and `tools/firstboot.sh` to prepare and personalise the ready-made image (`docs/product-image.md`).
  A ready-made box has **no login**: help comes from the page, the router, the power cable or re-flashing (see the new
  "Ready-made box" section of `docs/troubleshooting.md`). Pi-hole on it is updated by re-flashing a newer image.
- Debian security updates are switched on by default (`SINKO_OS_UPDATES=0` to skip), and bedtime and timers wait for the
  clock to be set on boards without a real-time clock (for at most about ten minutes after the box starts, so a box that
  never reaches the network still follows its schedule).
- A scheduler that **cannot be crashed by an odd value** in the shared state (the page and the box normalise it identically, with
  one shared list of test cases), that gives its Pi-hole session back on every error, repairs a missing block list by itself
  (at most once an hour), and tells the page it is alive (`/pb/box.json`, which also carries the box's address and time zone so
  the router help can show a number, never a name). The page warns when that heartbeat stops.
- The installer **proves the new scheduler runs** before it retires the old one, installs every file by rename so a power cut
  cannot leave an empty one, and keeps your own Pi-hole rules (even an existing `^.*$` deny rule) untouched.
- Sealing a ready-made image also wipes the free space by default (`--no-zerofill` for test units), removes Wi-Fi profiles, the
  on-disk copy of the logs, Pi-hole's HTTPS key, application password and TOTP secret, and locks the root login last.
- An update needs **more than 200 MB free** and says plainly when it does not (nothing is changed, and the page says the
  previous version is back only after the box checked itself); a first installation needs more than 1 GB. A failed
  `sinko update --ref vX` leaves the choice of what the box follows as it was.
- A box whose **page and program were left of two versions** by a power cut during an update repairs itself from the copy it
  keeps (`sinko repair`, started by the scheduler after ten quiet minutes, at most once an hour); a failed night is tried
  again the same night when it was only the network or the disk.
- Every `pihole -g` that Sinko starts, and the nightly refresh, takes one lock, so two never rebuild Pi-hole's lists together.
- `sinko remove` no longer deletes a device that also holds a group of the owner's own in Pi-hole.
- **My box → About** shows the Pi-hole version; the page's scripts carry the release in their addresses, so a phone never
  runs a new page with old scripts after an update; the "boxes online" line is shown from two boxes up.
- The installer asks apt and dpkg in English whatever the system's language, asks the counter question only when a counter
  address exists, sets up `systemd-timesyncd` on a box with no time service, and uses `pihole setpassword` (the password
  briefly in that program's arguments, which the install guide says) for a Pi-hole that already has a password.
- The seal refuses a unit with another console login, without automatic security updates or a time service, or pinned to a
  version or a branch; its read-back of the SSH lock-down asks `sshd -G` (the host keys are gone by then); its zero-fill
  fails on anything but a full disk.
- GPL-3.0-or-later licence (lists: CC0), security policy, contribution guide, code of conduct, issue templates.

### Migrating from pihole-bahrain 2.x
Run `sudo pihole-bahrain update` (or the new install command). The installer moves your settings, keeps your devices,
rules and password, replaces the old services and leaves a `pihole-bahrain` command that points to `sinko`. The old updater
fetches the `master` branch, but a box that follows releases gets the checksum-verified release instead as soon as one is
published (and keeps a copy of it to go back to). A 2.x box
followed the `master` branch (the old default); after migrating it follows **releases**, like a new install.

## [2.2.0] - 2026-10-03
### Added
- **The live picture**: a card that draws, in plain words, what the family box is doing: devices on top, the box in the
  middle, the internet below, with the numbers checked and stopped in the last 24 hours, a guided tour and a detail
  sheet. Arabic is drawn right to left. It never changes a rule.
- The page follows the box's clock for timers and "last online".

## [2.1.0] - 2026-10-03
### Added
- `diagnose` and `watch` commands to find out why a blocked app still works; `use-mac` to re-register children added by IP.
- `doctor` checks that DNS really reaches the box for each child device.
- Troubleshooting and hardening advice in the README.
### Changed
- Device identities use the MAC address, never a rotating IPv6 address; the generated parent password never reaches the
  install log; IP or subnet client rows that override a child's rules are detected and reported.

## [2.0.1] - 2026-09-25
### Fixed
- Installer on an existing Pi-hole v6, stale host names, failed downloads.

## [2.0.0] - 2026-09-17
### Changed
- Rewritten as a standalone add-on for Pi-hole v6: one Pi-hole group and list per service, timers and bedtime enforced by a
  service on the box, parent page served at `/`.
