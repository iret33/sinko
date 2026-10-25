# The factory test: every ready-made box tests itself

*For sellers who flash many boxes ([`product-image.md`](product-image.md) is the method). The commands here run on the golden
unit, which you can still log in to. A box that leaves the factory has no login.*

Each card is flashed from the golden unit's image. The first time it starts, the box tests its board and the whole Sinko stack
on it, and shows the result on the board's two lights. A box that passes seals itself for its customer and switches itself
off. At the bench you only plug in Ethernet and power, watch the lights, and unplug the box when every light is off.

Contents: [The lights](#the-lights) · [1. The golden unit](#1-the-golden-unit) · [2. Test, seal and arm it](#2-test-seal-and-arm-it) ·
[3. Copy the card, flash the batch](#3-copy-the-card-flash-the-batch) · [4. At the bench](#4-at-the-bench) ·
[5. A box that failed](#5-a-box-that-failed) · [What is tested](#what-is-tested) · [When a box passes](#when-a-box-passes) ·
[Keep the image for the factory](#keep-the-image-for-the-factory) · [Tailscale](#tailscale) · [Files](#files) ·
[What it cannot tell](#what-it-cannot-tell)

```
golden unit ── prepare-golden-master.sh ──► tested, sealed, factory test armed ── copy ──► image ── flash ──► every card

every card, at the bench:   first start (its own keys, name and address)
                            └─► factory test ─┬─ passed: sealed again for its customer, switches itself off
                                              └─ failed: SOS on the lights, a report; the test runs again at the next start

at the customer's:          no factory test (its flag is gone); the box makes its own keys, name and address; welcome screen
```

## The lights

On an Orange Pi Zero 3 with Armbian the two lights are `green:power` and `red:status`.

| The lights | What it means | What you do |
|---|---|---|
| One light after the other, a slow double beat | The test is running (a few minutes; the seal at the end rebuilds the block lists from the internet) | Wait |
| A fast chase for 8 seconds, then both lights flash five times | **Passed.** The box is sealed for its customer | Wait: both lights stay on while the box shuts down |
| Every light off | Switched off | Unplug it. It is ready to be boxed |
| Both lights together: S O S (· · · — — — · · ·), over and over | **Failed** | See [5. A box that failed](#5-a-box-that-failed) |
| No light changes for ten minutes, or no light at all | The test cannot show its result | Treat it as failed |

To learn the three patterns, run `sudo /opt/sinko/tools/factory-qa.sh --leds` on the golden unit before you seal it: it shows each
one and puts the lights back as they were.

## 1. The golden unit

Build it as [`product-image.md`](product-image.md), section 1, says: Armbian minimal (Debian Trixie), Sinko from the latest
release, `sudo sinko doctor` and `sudo sinko selfcheck` all `ok`, and the checks of step 5 there. Use a **small card (8 GB)**:
the image is as big as the golden unit's card, and every card you ship must be at least that big (a 32 GB golden card makes
a 32 GB image that takes far longer to copy and to flash, and some cards sold as "32 GB" are a little smaller).

The golden unit needs Ethernet with internet, like every box at the bench.

## 2. Test, seal and arm it

From the console, or from an SSH session that you keep open until it has finished:

```bash
sudo /opt/sinko/tools/prepare-golden-master.sh --dry-run    # the checks and the plan; changes nothing
sudo /opt/sinko/tools/prepare-golden-master.sh              # the same, then the seal asks you to type SEAL
```

It does four things, in this order:

1. **The factory test's checks, on the golden unit** (`factory-qa.sh --check`: the checks of [What is tested](#what-is-tested),
   without the seal). A golden unit that fails them would make a batch of boxes that all fail, so nothing is changed when one
   fails. Two checks are only for a flashed box: the golden unit's own parent password is noted (the seal removes it), and its
   first start is not asked about.
2. **The seal** (`tools/seal.sh`, [`product-image.md`](product-image.md), section 2). It refuses a unit that is not ready, and
   it locks root and SSH password logins last.
3. **The factory test is armed**: the flag `/var/lib/sinko/factory-qa` (the boxes' host name, whether the golden unit has
   Tailscale, the date) and `sinko-factory-qa.service`, enabled. Nothing is armed when the seal stopped.
4. **The commands that copy the card**, with its exact size.

Options: `--hostname NAME` (every box answers at `http://NAME.local/`; default `sinko`), `--yes` (no question). For a test image
only: `--no-zerofill` and `--keep-ssh-access`, which the seal applies to the golden unit and, through the flag, to every box
that passes.

Then switch the unit off as it says (`unset HISTFILE; poweroff`), and do not start it again before the card is copied: its next
start would run the factory test, which seals it for a customer and switches it off.

## 3. Copy the card, flash the batch

On a Linux computer with a card reader (the end of `prepare-golden-master.sh` prints these lines with your card's size and
version):

```bash
lsblk -b -d -o NAME,SIZE,MODEL,TRAN                                        # the card is the disk of the size it printed
sudo dd if=/dev/sdX of=sinko-3.2.0-orangepizero3.img bs=4M status=progress conv=fsync
xz -T0 -9 sinko-3.2.0-orangepizero3.img
sha256sum sinko-3.2.0-orangepizero3.img.xz > sinko-3.2.0-orangepizero3.img.xz.sha256
```

Check `sdX` twice: `dd` overwrites a disk without asking. On a Mac, find the card with `diskutil list` (`/dev/diskN`), run
`diskutil unmountDisk /dev/diskN` and copy from `/dev/rdiskN` with `bs=4m`. Flash every card with balenaEtcher (it reads back
what it wrote), or `xzcat sinko-3.2.0-orangepizero3.img.xz | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress`.

## 4. At the bench

For each box: the card in, the **Ethernet cable first** (to a switch or router with DHCP and internet), **then the power**, and
watch the lights ([The lights](#the-lights)). Several boxes at once are fine: each gets its own address, and avahi names them
`sinko`, `sinko-2`, and so on.

The bench network must give an address by DHCP, reach the internet (GitHub, for the block lists that the seal rebuilds, and the
upstream DNS service), and let the box reach a time server (NTP, UDP port 123): the board has no clock battery, and bedtime
needs the right time.

The test starts after the box's own first start (its SSH keys, name, box id and address) and waits up to 60 seconds for Pi-hole,
the network, the page, the scheduler and the clock. A managed switch that holds a new link back for half a minute (spanning tree)
is fine: when the first start ended before the network was up, the test runs it once more. A box that passes takes a few minutes
in all.

## 5. A box that failed

What failed is written in two places:

* **on the card**, in `/root/FAILED_QA_REPORT.txt` (mount the card on a Linux computer: it is the first partition), with every
  check, the failing ones first, and the longer output of what failed;
* **on the bench network**, while Pi-hole runs: `http://<the box's address>/pb/factory-qa.txt` (the address is in your router's
  list of devices).

The flag stays, so the test runs again at every start until it passes. Fix the cause and pull the power, then plug it in again
(a box that failed was not sealed, so there is nothing to lose). A box that fails again on a good network gets a freshly
flashed card; a board that fails on a fresh card is set aside.

| The report says | Usually |
|---|---|
| `network ... has no link` | The cable, the switch port, or the box's port |
| `network ... at only 10 Mbit/s` | A damaged cable, port or switch |
| `clock not set from a time server` | The bench network blocks NTP |
| `github.com does not resolve` | The bench network has no internet |
| `temp SoC at ... °C` | The board is in the sun, or its heatsink or fan is missing |
| `memory ... the 1.5 GB Orange Pi Zero 3` | The wrong board: use one with 1, 2 or 4 GB |
| `storage ...` | The card: flash a new one |
| `seal tools/seal.sh stopped` | Read the lines under `--- tools/seal.sh` in the report; often the internet went away while the block lists were rebuilt |

## What is tested

| Area | Check | Why |
|---|---|---|
| lights | The board's own lights are found (by their `leds-gpio` driver) | The test shows its result on them |
| board | `aarch64`; the device tree names an Allwinner H616 or H618 (the Zero 3 has the H618, the newer member of the H616 family); 4 Cortex-A53 cores running | The right board and image; a core that did not start is a board fault |
| temp | The SoC (its `cpu-thermal` sensor) below 75 °C | A board that runs hot on the bench runs hotter in a closed case |
| memory | At least 900 MB, and not the 1.5 GB board | A 1 GB board shows a little less than 1024 MB; current kernels crash on the 1.5 GB board ([`selling.md`](selling.md)) |
| storage | The system is mounted read-write, at least 1024 MB free on the card, and 4 MB written to the card, forced onto it and read back unchanged | A card that turned read-only, or loses what it is given, fails here and not at the customer's |
| network | The wired port (found by the default route: `end0` on Armbian, else `eth0`) has a link of at least 100 Mbit/s, an IPv4 address from DHCP and a default route | The port does 1000 Mbit/s; 10 means damage |
| clock | Set from a time server | Bedtime, timers and HTTPS need it |
| pihole | `pihole-FTL` runs; `database.DBinterval` is 60 (Pi-hole's default, in `pihole.toml`); `gravity.db` passes SQLite's own check and holds Sinko's groups and TikTok's block list with its entries | Pi-hole's settings and database came through the copy intact |
| dns | Pi-hole answers on port 53 (`pi.hole`); the page's local name (`family.lan`) points at this box; `github.com` resolves through the upstream DNS service | Every phone at home will ask it; updates and block lists come from GitHub |
| blocking | A made-up device (the address `127.0.0.2`, which no device at home can have) joins Sinko's TikTok group. With TikTok allowed, `tiktok.com` resolves for it; blocked, Pi-hole stops it (`0.0.0.0` in Pi-hole's default blocking mode) and `github.com` still resolves for it; allowed again, it resolves again. The switch is made the way the page makes it (Pi-hole's API, the DNS cache cleared after each change) and read back from Pi-hole's database. The device and the switch are put back afterwards | What a parent does with one tap really stops an app, and only that app |
| page | The page is served at `/` as this Sinko version; `/pb/box.json` names this version, the box's own id and its address | The parent's phone and the Sinko app find the box |
| sinko | `sinko selfcheck` (the check every update runs); the `sinko` command; **no password is set**, so the customer gets the welcome screen; the box's first start finished | The box is the customer's to claim, with its own keys, name and address |
| tailscale | Only when the golden unit had it: installed, and **not logged in** ("READY FOR FIRST-TIME USER AUTH") | See [Tailscale](#tailscale) |

`pihole-FTL.conf` and its `DBINTERVAL` (in minutes) were Pi-hole v5's. Pi-hole v6 moves that file away when it upgrades and keeps
the setting in `pihole.toml` as `database.DBinterval`, in seconds. The test reads it with `pihole-FTL --config`.

The questions to Pi-hole are plain DNS questions on UDP port 53, the way a phone asks, from Python's standard library: they need
neither `dig` nor `nslookup`.

## When a box passes

1. `tools/seal.sh --yes --no-zerofill --hostname <the golden unit's>` seals it again, exactly as the golden unit was sealed:
   Sinko's objects in Pi-hole are made again from nothing (the block lists are rebuilt), there is no password, the SSH host
   keys, machine id, box id, HTTPS key, query history and logs of this start are deleted, and the box's first start is armed
   again. There is no zero-fill: the golden unit's image was zero-filled, what this start wrote is nobody's private data, and
   writing over the whole free card would take many minutes for every box.
2. When Tailscale is installed, its identity (`/var/lib/tailscale/tailscaled.state` and its log id) is deleted, so each box makes
   its own at the customer's first start.
3. The flag, the report and the unit file are removed, and the unit is disabled: a customer's box never runs the test. (An update
   of Sinko brings the unit file back, disabled and without its flag: it never runs.)
4. The lights dance, then both stay on. Armbian saves the lights' state when it shuts down and restores it at every start
   (`armbian-led-state.service`, in `/etc/armbian-leds.conf`): the test stops that service, which saves "both on" one last
   time, and puts back the file the box started with, so the customer's box starts with the lights as the golden unit had them.
5. `sync`, then the box switches off. When every light is off, it is safe to unplug.

The few lines the shutdown itself writes to the journal stay on the card, as on the golden unit. They name nothing of the
customer's or yours.

## Keep the image for the factory

Every card flashed from the armed image tests itself at its first start, and switches itself off when it passes. Do not give that
image to a customer for a re-flash: copy a card that has **passed** the test instead (it is sealed for a customer, and starts
straight away with the welcome screen). Rebuild the golden unit, and run `prepare-golden-master.sh` again, for every Sinko release
and every Pi-hole security fix ([`product-image.md`](product-image.md), section 3).

## Tailscale

Sinko does not install Tailscale, and a ready-made box has no login, so a customer could never log it in. If you add it to the
golden unit anyway, the test makes sure that no box leaves the factory **logged in**: a logged-in box would share one Tailscale
identity with every box from the same image, and your tailnet would reach into the customer's home network (see "Support access"
in [`product-image.md`](product-image.md)). Log the golden unit out (`tailscale logout`) before you prepare it.

## Files

| What | Where |
|---|---|
| The test, and the script that prepares the golden unit | `/opt/sinko/tools/factory-qa.sh`, `/opt/sinko/tools/prepare-golden-master.sh` |
| The unit (installed on every box, enabled only on the golden unit) | `/etc/systemd/system/sinko-factory-qa.service` |
| The flag: the test runs only while it exists | `/var/lib/sinko/factory-qa` (`hostname=`, `tailscale=`, `keep_ssh=`, `made=`) |
| The report of a box that failed | `/root/FAILED_QA_REPORT.txt`, and `http://<the box's address>/pb/factory-qa.txt` |
| The SOS of a box that failed | `sinko-factory-qa-sos.service`, started by the test, until the power is cut |
| What the test keeps while it runs | `/run/sinko-factory-qa` (in memory, gone at the next start) |

## What it cannot tell

* **A light that does not work.** The test cannot see its own lights: no change for ten minutes, or no light at all, is a
  failure.
* **Wi-Fi, HDMI and USB** are not tested: a Sinko box uses none of them.
* **The whole card.** Only 4 MB are written and read back. A fake card (smaller than it says) is caught by balenaEtcher, which
  reads the whole image back after it wrote it.
* **The power supply.** A weak supply can pass a few minutes on the bench and fail under load at home: buy tested ones
  ([`selling.md`](selling.md), section 4).
* What only the real board shows (the lights' patterns, the power-off, Armbian's light file) is in
  [`hardware-test-checklist.md`](hardware-test-checklist.md), section E.
