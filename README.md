<p align="center">
  <img src="docs/img/wordmark-en.svg" alt="Sinko" height="72">
</p>

<p align="center"><strong>Calm internet for the family.</strong><br>
<span dir="rtl" lang="ar"><strong>إنترنت هادئ للعائلة</strong></span><br>
Parental controls that live on a small box in your home, in Arabic and English.<br>
<a href="https://iret33.github.io/sinko/">Website</a> · <a href="docs/install.md">Install</a> · <a href="docs/faq.md">FAQ</a> · <a href="docs/privacy.md">Privacy · الخصوصية</a></p>

<p align="center">
  <a href="https://github.com/iret33/sinko/releases"><img alt="Total downloads" src="https://img.shields.io/github/downloads/iret33/sinko/total?label=downloads&logo=github&color=1B1B19&style=flat-square"></a>
  <a href="https://github.com/iret33/sinko/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/iret33/sinko?color=1B1B19&style=flat-square&label=release"></a>
  <a href="https://github.com/iret33/sinko/releases/latest"><img alt="Downloads of the latest release" src="https://img.shields.io/github/downloads/iret33/sinko/latest/total?label=this%20release&color=1B1B19&style=flat-square"></a>
  <a href="https://github.com/iret33/sinko/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/iret33/sinko?color=1B1B19&style=flat-square"></a>
</p>
<p align="center">
  <a href="https://github.com/iret33/sinko/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/iret33/sinko/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/iret33/sinko/commits/master"><img alt="Last commit" src="https://img.shields.io/github/last-commit/iret33/sinko?color=1B1B19&style=flat-square"></a>
  <a href="COPYING.md"><img alt="Licence: GPL-3.0-or-later" src="https://img.shields.io/badge/licence-GPL--3.0--or--later-1B1B19?style=flat-square"></a>
  <img alt="Pi-hole v6" src="https://img.shields.io/badge/Pi--hole-v6-96060C?style=flat-square&logo=pihole&logoColor=white">
  <img alt="Orange Pi Zero 3" src="https://img.shields.io/badge/Orange%20Pi-Zero%203-F26B21?style=flat-square">
  <img alt="Languages: Arabic and English" src="docs/img/badge-languages.svg">
  <a href="CONTRIBUTING.md"><img alt="Contributions welcome" src="https://img.shields.io/badge/contributions-welcome-1B1B19?style=flat-square"></a>
</p>
<p align="center">
  <a href="docs/privacy.md"><img alt="Boxes online" src="https://img.shields.io/endpoint?url=https://sinko-counter.sabdulla.workers.dev/badge/online.json&style=flat-square&color=1B1B19"></a>
</p>

<p align="center">
  <a href="hardware/case/README.md"><img src="hardware/case/img/hero.jpg" alt="The Sinko box case: a white lid with a round fan grille and the Sinko logo engraved on top, on a thin teal base, with small vent holes in the front" width="480"></a><br>
  <sub><b>The Sinko box case</b> (version 1.1), free to print: closed on every side except power and Ethernet, with a small silent fan.<br>
  <a href="hardware/case/README.md">Files, parts list and how to put it together</a> · <a href="https://www.pcbway.com/project/shareproject/Sinko_box_a_minimal_fan_cooled_case_for_the_Orange_Pi_Zero_3_508ebe8e.html#cnclink">Get it printed on PCBWay</a><br>
  <span dir="rtl" lang="ar">علبة صندوق سينكو، مجانية للطباعة، مع قائمة القطع وطريقة التجميع</span></sub>
</p>

<p align="center">
  <img src="docs/img/desktop-en.png" alt="The main page on a computer, in three columns. Left: the control panel says Children’s internet is on, with a green dot, an orange Turn internet off key and smaller keys for 30 minutes, an hour or until the morning; under it the Homework and Free time keys and the card What Sinko did for you, with this week’s numbers and a chart of the ads stopped each day. Middle: every app with an Allow and a Block key, the blocked ones filled in. Right: the children’s devices with Pause keys, and bedtime in one sentence" width="760"><br>
  <sub>The main page on a computer: the one big key, what Sinko did this week, the apps, the devices and bedtime</sub>
</p>

<p align="center">
  <img src="docs/img/panel-en.png" alt="Phone: the main page in English. Children’s internet is on; the orange Turn internet off key, with Off for 30 min, Off for 1 hour and Off until the morning beside it; Homework and Free time; and the top of What Sinko did for you" height="460">
  &nbsp;
  <img src="docs/img/live-en.png" alt="Phone: the live picture, opened with See it live. A circuit board with Sara’s iPad, Ali’s phone and everyone else at the top, the family box in the middle with a black hole beside it, and the internet at the bottom; under it, how many checks the box made and stopped for the whole home in the last 24 hours" height="460">
  &nbsp;
  <img src="docs/img/panel-ar.png" alt="Phone: the same main page in Arabic, laid out right to left" height="460"><br>
  <sub>On a phone: the main page, the live picture behind <b>See it live</b>, and the main page in Arabic</sub>
</p>

<details align="center"><summary><b>My box</b>: updates, health and addresses (tap to see)</summary>
<p align="center"><img src="docs/img/box-en.png" alt="My box on a phone: a newer Sinko ready to install, how the box is doing (filtering on, running for 3 days, its temperature, memory and clock) and the addresses that open the page" width="300">
&nbsp;<img src="docs/img/box-ar.png" alt="The same My box sheet in Arabic, laid out right to left" width="300"></p>
</details>

<p align="center"><sub>The pictures come from a demo box (<a href="tools/make-screenshots.py"><code>tools/make-screenshots.py</code></a>): the names, the numbers, the savings and the update on offer are examples.</sub></p>

Sinko is a simple page for parents, on top of [Pi-hole](https://pi-hole.net) v6. Every phone, tablet and console at home
asks a small box in your house "where is this app?" first, and the box says yes or no. The page looks like the control
panel of a home appliance, and the first thing on it is one big key. From your phone you can:

- **turn the children's internet off** with that key, and back on with the same key; or off **for 30 minutes**, **an
  hour** or **until the morning**. The panel always says, in one sentence, whether it is on or off and when it comes back;
- **allow or block apps** (YouTube, TikTok, Roblox, Instagram, Snapchat, …): every app has an **Allow** and a **Block** key;
- switch on **Homework** mode, or a timed **Free time**;
- **pause** one child's device;
- set a **Bedtime** that turns the internet off at night and back on in the morning;
- see **What Sinko did for you**: the ads and trackers it stopped, the waiting and the data that saved, how often blocked
  apps tried to open, and how many nights bedtime was kept, today, this week and since the start
  ([how it counts](#what-sinko-did-for-you));
- **See it live**: a picture of what the box is checking and stopping, in words a parent can follow;
- let the box **learn new addresses** of the apps you block: a small AI model on the box spots an app you blocked trying a
  new address, and blocks that too (optional: it starts switched on when you agree to the terms at first set-up, and you
  can switch it off there or in **My box**, where you can also allow any of them again);
- look after the box from the same page (**My box**): update it, see its health, change the password, back up, restart.

Timers and bedtime run on the box itself, so they keep working after you close the page. Nothing needs a computer
after the first set-up. Light and dark, in Arabic and English.

## What Sinko did for you

A card on the page shows what the box did for your family: **today**, **this week**, or **since it started counting**.

| On the card | Where the number comes from |
|---|---|
| Ads and trackers stopped | The box's own records: every time its ad lists said no, on every device at home |
| Less waiting for ads | About **50 ms** for each one stopped (the estimate the Brave browser publishes) |
| Data saved | About **10 KB** for each one stopped (a deliberately low guess); in money too, if you type what 1 GB costs you |
| *App* tried to open | How often each blocked app tried, on the children's devices |
| Internet off at bedtime | Nights the internet stayed off for practically the whole of bedtime |
| Children's internet off | Every minute it was off for the children: bedtime, breaks and when you switched it off |

Every figure says "about" because it is an estimate, and **How we count** on the card explains each one. The numbers are
counts the box keeps for itself (no websites, addresses or device names); they stay on the box and are never sent to the
project. The price you type stays on your phone.

## See it work

<p align="center">
  <img src="docs/img/live-diagram.svg" alt="Animation: a phone asks the Sinko box for youtube.com and the app works; it asks for tiktok.com and the box answers no, so the app stays closed" width="820">
</p>

Every app first asks the box "where is this?". If your rules allow it, the box asks the internet and passes the answer back. If
not, the box says no and the app simply does not open. **See it live** on the page shows these answers as they happen.

<p align="center">
  <a href="https://iret33.github.io/sinko/how-it-blocks.html"><img src="docs/img/how-it-blocks.png" alt="How Sinko blocks an app, drawn as a bench in thin lines: question tokens from the children's devices slide along a track under the Sinko box, which checks each one against a row of switches, one for each app, and a mode knob; a yes rides on to the router, a no drops through a trap into a black hole" width="560"></a><br>
  <sub><b><a href="https://iret33.github.io/sinko/how-it-blocks.html">How Sinko blocks an app</a></b>: flip the switches and turn the mode knob yourself, on the project website (<a href="site/how-it-blocks.html">source</a>)<br>
  <span dir="rtl" lang="ar">كيف يحظر سينكو تطبيقًا: جرّب المفاتيح ومقبض الأوضاع بنفسك على موقع المشروع</span></sub>
</p>

## Two ways to get Sinko

**Ready-made.** An Orange Pi Zero 3 with Sinko already on its card: plug in the cable and the power, open
`http://sinko.local` on your phone, choose a password, point your router at the box. **Ready-made boxes are not on sale
yet.** Follow the project on GitHub for news; the [project website](https://iret33.github.io/sinko/) will say where to buy
one as soon as there is a shop.

**Build your own, free.** Any small Debian-based computer will do (an Orange Pi Zero 3 or a Raspberry Pi is ideal), and it
takes one command: see [Install](#install) below.

Sinko is free software (GPL-3.0-or-later). Anyone may build, share and sell help with it; flashed boxes sold under the
Sinko name are covered by [`TRADEMARK.md`](TRADEMARK.md), and [`docs/selling.md`](docs/selling.md) explains what a seller owes
the software's authors.

## Install

For people who build their own box. You need a small computer that runs Debian, Ubuntu or Raspberry Pi OS (an Orange Pi
Zero 3 is what Sinko is tested on), connected to the router by an Ethernet cable, with more than 1 GB of free disk space.
On it, over SSH or at its keyboard, run one command:

```bash
curl --proto '=https' --proto-redir '=https' -fsSL https://github.com/iret33/sinko/releases/latest/download/install.sh | sudo bash
```

It installs Pi-hole v6 if needed, Sinko, the services and the block lists, asks you for a parent password, and tells you the
address of the page and the one setting to change in your router (the DNS server: the box's address, reserved for the box).
Then open the page on your phone and add your children's devices. Running the command again updates Sinko and keeps your
password, devices and rules. Everything about it (options, the Orange Pi Zero 3 steps, keeping the box safe, removing
Sinko) is in [`docs/install.md`](docs/install.md).

## Updates

Open **My box**: it says when a newer version exists, and **Update now** installs it, checks that it works and
**puts the previous version back by itself if it does not**. An update never touches your password, devices, rules,
timers or bedtime. There is an option to update automatically at night. Details and the protections:
[`docs/updating.md`](docs/updating.md).

## Privacy, plainly

Sinko keeps your children's names and devices, your rules and your settings on the box, and never sends them to the project
or to anyone else. There is no account and no tracking. Three things you should know:

- Like every DNS filter, Pi-hole passes on the **names of sites it cannot answer itself** to an upstream DNS service
  (Cloudflare for Families, by default, on a box Sinko sets up). It sees those names and your home's internet address. The
  project never receives them. You can choose another service in Pi-hole's settings.
- To look for a new version, to update and to refresh its block lists, the box asks **GitHub**, which sees the box's
  internet address (as any website you visit does). Nothing about your family is in those requests.
- An optional **anonymous counter** (how many Sinko boxes are online) **sends nothing until you answer**. It is one of the
  two choices on the [terms of use](docs/terms.md) the page shows at first set-up, where it starts switched on; it sends a
  random number, the version and the kind of board, and nothing else. Switching it off (there, or any time in **My box**)
  makes the box ask the counter to forget it.

The whole statement, in English and Arabic, with exactly what is sent and when: [`docs/privacy.md`](docs/privacy.md).

## What it cannot do

DNS filtering is a strong everyday filter, not a lock:

- A device on **mobile data**, or using a **VPN** app, does not use the box.
- Apps that connect to fixed IP addresses (Telegram does this in part) may keep working after being blocked.
- Apps that are already open can take a few minutes to stop, until the device's own DNS cache expires.
- A child who knows the main Wi-Fi password and can change network settings can get around it.

Use it together with Screen Time (iPhone) or Family Link (Android). More in the [FAQ](docs/faq.md).

## Documentation

| | |
|---|---|
| [`docs/install.md`](docs/install.md) | Install, options, Orange Pi Zero 3, router step, commands, removing |
| [`docs/updating.md`](docs/updating.md) | Updates, rollback, pinning a version |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | An app still works? Cannot open the page? Forgot the password? |
| [`docs/faq.md`](docs/faq.md) | Questions and answers |
| [`docs/privacy.md`](docs/privacy.md) | What is sent, where, and how to turn it off (English and Arabic) |
| [`docs/terms.md`](docs/terms.md) | The terms of use a parent agrees to at first set-up, with its two choices (English and Arabic) |
| [`docs/how-it-works.md`](docs/how-it-works.md) | Pi-hole groups, the control panel, how the savings are counted, the live picture, the block lists, files on the box |
| [`docs/product-image.md`](docs/product-image.md), [`docs/selling.md`](docs/selling.md) | Making and selling ready-made boxes |
| [`docs/hardware-test-checklist.md`](docs/hardware-test-checklist.md) | What to test on a real box before a release or a sale |
| [`hardware/case/`](hardware/case/README.md) | A case to print for the Orange Pi Zero 3 (version 1.1), with the parts list (English and Arabic) |
| [`docs/maintainers/`](docs/maintainers) | Architecture and contracts; releasing |
| [`CONTRIBUTING.md`](CONTRIBUTING.md), [`SECURITY.md`](SECURITY.md), [`CHANGELOG.md`](CHANGELOG.md) | Helping, reporting a vulnerability, what changed |

## Development

```bash
python3 -m unittest discover -s tests -p "test_*.py"    # box program, updater, lists, doctor, diagnose, copy, release build; with playwright also the real page against the real scheduler
node --test tests/*.test.js                              # the page's logic (state, live picture, My box)
sudo bash tests/run_shell_tests.sh                       # installer, migration, seal, first start (stubbed system)
python3 tests/ui_smoke.py --shots /tmp/shots             # the page in a real browser, English and Arabic (needs playwright)
python3 tests/mock_pihole.py --web web --setup --live    # the page at http://127.0.0.1:8080, password "test", with demo traffic
```

`tests/mock_pihole.py` imitates the parts of the Pi-hole v6 API Sinko uses, so no device is needed. Full list and the
pull-request checklist: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Licences and names

- Sinko's code is **GPL-3.0-or-later** ([`LICENSE`](LICENSE), [`COPYING.md`](COPYING.md)); the block lists in `lists/` are
  public domain (CC0); the bundled font, IBM Plex Sans Arabic, is under the SIL Open Font License (`web/fonts/OFL.txt`);
  the case in `hardware/case/` is under CC BY-SA 4.0.
- "Sinko" and its logo are the project's marks ([`TRADEMARK.md`](TRADEMARK.md)). Third-party software and trademarks are
  listed in [`NOTICE`](NOTICE).
- Pi-hole is a registered trademark of Pi-hole LLC and is licensed under the EUPL-1.2. Sinko is independent software that
  works with it, and is not affiliated with, endorsed by or supported by Pi-hole LLC.
