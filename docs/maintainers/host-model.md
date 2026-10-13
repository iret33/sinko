# Host suggestions: the small AI model

The block lists go stale. Apps move to new names, and a list that was right last month lets an app work today: Sinko 3.0.4
added 24 hosts by hand after each service was tested on a real device. `tools/suggest-hosts.py` helps with that work. It
trains a small AI model on the lists, reads a million popular host names, and writes the ones it believes belong to an
app into a review list. A person checks each line on a device before it goes into a list.

That review list is **step 1**: it decides nothing on a box. **Step 2**, the model on the box itself, is
[at the end of this page](#step-2-the-model-on-the-box): its engine and the `sinko learn` command are in, off until
switched on; the parent page's part comes next.

## What it is, and what to call it

A machine-learning model in the ordinary sense: logistic regression over pieces of a host name, trained from examples.
It is about 480 KB as JSON (140 KB compressed), uses Python's standard library only and needs no network to score a name.
It is not a chatbot: it reads names, never pages, pictures or messages, and it decides nothing on its own.

So it is honest to say Sinko uses AI, as long as the sentence says what the AI does. A box runs the model only where
learning was switched on, and until the parent page has the switch, only an owner who can log in to the box can do that.

| | Say | Do not say |
|---|---|---|
| With step 1 | "Block lists kept up to date with the help of a small AI model." «قوائم الحظر تُحدَّث بمساعدة نموذج صغير من الذكاء الاصطناعي.» | "AI-powered box", "the box uses AI" |
| With step 2 | "A small AI model in the family box spots new addresses of apps you blocked. It runs on the box itself, and what it learns is not sent anywhere." «نموذج صغير من الذكاء الاصطناعي داخل صندوق العائلة يتعرّف على عناوين جديدة للتطبيقات التي حظرتها. يعمل على الصندوق نفسه، وما يتعلّمه لا يُرسَل إلى أي مكان.» | "AI-powered parental controls", "AI keeps your children safe", "AI blocks harmful content", "sends nothing out" |

The blocking itself is always the lists (and, with step 2, rules the box adds). The AI finds names; it does not understand
content, and it does not change what DNS filtering cannot do (README, *What it cannot do*). Never let a sentence about the
model sound like one about the box: the box still passes the names it cannot answer to its upstream DNS service
(`docs/privacy.md`), so "sends nothing" is only true of what the model learns. Have a native speaker read the Arabic
before it is printed anywhere.

## Running it

```bash
python3 tools/suggest-hosts.py                          # about 4 minutes; writes host-suggestions.md
python3 tools/suggest-hosts.py --names top-1m.csv.zip   # a names file you already have ("rank,name" or one name a line)
python3 tools/suggest-hosts.py --backtest 1ffee15       # would it have found what was added since that commit?
python3 tools/suggest-hosts.py --save-model model/host-model.json  # also write the model the release ships
```

Without `--names` it downloads [Cisco Umbrella's popularity list](https://s3-us-west-1.amazonaws.com/umbrella-static/index.html)
(the million names most looked up through Cisco's DNS service, about 10 MB) into a temporary folder. The list is not kept
and is never committed. The same input always gives the same file. The workflow `.github/workflows/host-suggestions.yml`
runs it on the first of every month (and by hand from the Actions tab). It shows the review list on the run's page
and keeps the file and the model as the run's artifact. It has read-only access and changes nothing in the repository.

## Reading the review list

Each app has up to three parts. Every line is a box to tick once it has been checked:

1. **New sites that carry the app's own word** (`||tiktok-minis.us^`): a whole site whose name has a word from one of the
   app's listed sites. These are the strongest suggestions.
2. **On somebody else's site** (`||tiktokcdn.com.wsdvs.com^`, under a content network): block only what the line
   shows, never the site it is on. A line between slashes is one regular expression for many hosts of one shape, such as
   `/(^|\.)instagram\.[a-z0-9_-]+\.fna\.fbcdn\.net$/` for 3,805 Instagram media servers on Facebook's network. A list
   file cannot hold a pattern (it is Adblock style, one `||domain^` a line), so such a line needs a rule. That is part
   of step 2.
3. **The model alone**: the name has none of the app's words, and the model thinks it is the app's anyway. These are the
   weakest suggestions. A line that starts with `*.` means that the start of the names looked like the app's, but the site
   itself does not. Example: `rr1---sn-….gvt1.com` looks like a YouTube video server, but gvt1.com is Google's download network
   for Chrome and Android. Never block such a site whole.

Then follow [CONTRIBUTING.md](../../CONTRIBUTING.md): block a test device's app, look it up, and see that the app stops
and nothing else does. A list blocks an **app**, not sites *about* the app: fan wikis, downloaders and namesakes stay out
even when the model is sure.

## How it works

1. **Examples.** Every domain on a list is an example of its app, and so is every popular name a list blocks (a name under
   a listed domain, or a content network's alias of one: `x.tiktokcdn-us.com.edgesuite.net`). The other popular names are
   ordinary, except those that carry an app's own word without being listed (`instagram.fxyz.fna.fbcdn.net`). Those are left
   out: teaching them as ordinary would teach the model to miss what it is for. An app's words come from the main label of
   each whole site on its list (`tiktokcdn` from `tiktokcdn.com`) and of each host on a platform (`steamcdn-a` from
   `steamcdn-a.akamaihd.net`). A host on somebody else's site gives none: `teams.microsoft.com` must not make "microsoft"
   a word of Teams. The guard list is not an app and is left out.
2. **Reading a name.** Shared platforms (Akamai, Fastly, Cloudflare, `l.google.com`, `fbcdn.net`, …: `SHARED` in the
   tool) are cut off the end, because "akamaized" says nothing about whose a name is. Then the public suffix is cut. What is
   left is read as its main label, every label, pairs of neighbouring labels, and every 3- to 5-letter piece of each label,
   with digits folded together.
3. **Two stages.** "Is this an app's name?" is logistic regression. "Which app?" is a softmax over the apps, trained on the
   app examples only. A suggestion needs at least 0.98 on the first stage.
4. **Fair scores.** The sites are split in two halves. Each half is scored by a model trained on the other half's ordinary
   names, so every site is new to the model that judges it, as it would be in real life.
5. **Lines, not names.** Names are grouped by the shortest end that still carries the app's word, and ends of one shape
   become one pattern. A line never offers a whole platform or anything the list tests refuse (`NEVER` in the tool, checked
   against `tests/test_core.py` by `tests/test_suggest_hosts.py`).

## How well it does

Measured on 13 October 2026 with Umbrella's list of that day.

**Backtest.** Trained on the lists as they were before #25 (`--backtest 1ffee15`), it suggests **15 of the 24 hosts** that
#25 then added by hand, each with the right app. Examples are `tiktokv.eu`, `tiktok-row.net`, `discord.media`,
`ytimg.l.google.com` and the X hosts on Fastly and Cloudflare. It misses the hosts whose names say nothing about the app
(`fbsbx.com` for Facebook, `cdn1.unrealengine.com` for Fortnite, `napubgm.broker.amsoveasea.com` for PUBG,
`bytefcdn-oversea.com`). It also misses a few it scored just under the bar (`dynamic.x.com.cdn.cloudflare.net` 0.96,
`pubgm.yzfchat.com` 0.97).

**Today's lists.** It suggests 9,829 names in 579 lines. Some of the lines, **not yet checked on a device**:

- Instagram: the pattern above, 3,805 media servers on Facebook's network. These are the "known limit" of 3.0.4.
- TikTok: new ByteDance sites such as `tiktok-minis.us`, `byteoversea.net`, `toutiaoapi.com`, `tiktokw.eu`,
  `tiktokeu-cdn.com`, `tiktoklb.us`, and hundreds of TikTok and Douyin names on other companies' content networks.
- ChatGPT: `oaistatsig.com` (OpenAI's usage measuring); Fortnite: `epicgamescdn.com`.

**What it gets wrong** (and why a person reads every line):

- Namesakes: `telegraph.co.uk`, `telegraaf.nl` and `telegram.hr` (newspapers) for Telegram, because `telegra.ph` is on its
  list; `infoblox.com` for Roblox, because "blox" is Roblox's.
- Sites *about* an app: `minecraft.wiki`, `planetminecraft.com`, `fortnite.gg`, `youtube.fandom.com`.
- One odd entry can mislead it. In an earlier test, which never showed it `office.com`, it took `office.com` for Discord
  because Discord's list has `watchanimeattheoffice.com`.

## Limits

- It reads names only. It cannot know who owns a site, and a name that says nothing (`fbsbx.com`) stays invisible to it.
- `SHARED` and `NEVER` are written by hand. A platform missing from `SHARED` can be taken for an app's site; the `*.`
  lines and the "never" notes show where to look.
- Umbrella's list is what Cisco's users look up. An app popular in one region only may be missing from it.
- The list changes every day, so two months' review lists differ even when the block lists do not.

## Step 2: the model on the box

**Goal.** When a blocked app reaches a new name that no list has yet, the box blocks that name for that app within
minutes, without waiting for a release. It must never block something that is not the app's.

**Why the box can do better than step 1.** It sees what the children's devices really look up, and when. An app that is
being stopped tries its other names straight away (TikTok looked up `api-h2.tiktokv.com.ttdns2.com`, which #25 added
after seeing the app use it). The behaviour is evidence the name alone does not have.

**What is in.** The engine and a command; the exact contract is in [`architecture.md`](architecture.md), *Learning new
addresses*.

1. **One copy of the code.** Reading a name and scoring it (`app_labels`, `features`, `Cover`, `zone`, `Model.score`) live
   in `bin/sinko`, and `tools/suggest-hosts.py` imports them from there, so training and the box can never read a name
   differently (the move changed no byte of the model). The release ships the model as `model/host-model.json`, 481 KB;
   [`model/README.md`](../../model/README.md) says how it was made.
2. **What it reads.** Once a minute, the scheduler's `Maintenance` asks `/api/queries` (the endpoint the live picture
   reads) for the lookups since its last look, at most 1,000. It looks a minute at a time, not every 10 minutes as first
   planned, because a refusal and a new name must be at most two minutes apart. It scores only names that were answered and
   that no list covers. On a development machine the model loads in 0.14 s, holds 3.6 MB and scores a name in about 50 µs;
   the Zero 3's own numbers are for the hardware checklist. With Pi-hole's privacy level hiding names or devices, it learns
   nothing.
3. **When it blocks.** All of these must hold:
   - The model gives the name at least 0.98 for an app, and that app is blocked right now.
   - The name carries the app's own word, and what gets blocked is the shortest end of the name that still does
     (`tiktokcdn.com.wsdvs.com`, never `wsdvs.com`).
   - The same device was refused a name of that app's list within 2 minutes, before or after: the app is open and being
     stopped.
   - That end is not one of `NEVER`, no allow rule of the owner's covers the name, and it was not taken back before.
   - Fewer than 20 names were learned for that app today, and the box holds fewer than 200 learned names in all.

   This is stricter than step 1 on purpose: no person reads the line first.
4. **How it blocks.** A Pi-hole deny rule, the regular expression `(^|\.)zone$`, in the app's own group `pb-svc-<id>`, with
   the comment `pb-learned:<id> <day>`. It follows the app's block and allow by itself, needs no gravity run and takes
   effect at once; after a look that learned something the box's DNS cache is cleared once. `Controller` still makes
   every rule of the parent's: the learner adds only its own. `setup` and the self-heal leave learned rules alone, `sinko
   remove` deletes them, and a backup and restore carry them like any other rule.
5. **Switching it on and taking a name back.** `sudo sinko learn on|off|status|list|forget NAME`. The switch is the new
   shared-state key `"learn": {"on": false}` (both parsers and `tests/fixtures/state-cases.json` know it, so the page keeps
   it when it saves). `forget` keeps the rule, switched off, with the comment `pb-learned-no:<id>`, so the name is not
   learned again.
6. **Privacy.** The learner sends nothing anywhere, and what the box sends (`docs/privacy.md`) does not change. It reads
   the history Pi-hole already keeps on the box and stores only its rules, in Pi-hole. `docs/privacy.md` says so in both
   languages. The site's text and the counter's page stay true as they are; the site changes with the parent page's part.
7. **Proof.** `tests/test_learn.py`: every condition of point 3 (each one alone keeps a name from being learned), the
   limits, the rules and their removal, the scheduler's switch and its minute, the command, and the shipped model (it
   knows every app of the catalogue, and what it says about a few real names).

**Still to do.**

- **The parent page.** Under a blocked app: "Sinko's AI also stopped 3 new addresses of this app", with the list and
  **Allow this one again** (what `forget` does). In *My box*, the switch "Learn new addresses of blocked apps". Every
  string in English and Arabic with no technical words (`tests/test_copy.py`), page tests, and the site's text.
- **The board.** `docs/hardware-test-checklist.md`: memory and time on a Zero 3, and a pass with a real TikTok on a test
  phone.
- **Rollout.** One release where the switch exists and is off, described as *Try it*, then on by default in a later
  release if no false block was reported. Only then do the README and the site use the step 2 sentence above.

**Known risk.** A namesake looked up on the same device within two minutes of the app being stopped can be learned: the
model gives `telegraph.co.uk` 0.995 for Telegram, because `telegra.ph` is on Telegram's list. The two-minute rule makes it
rare and the daily limit caps it; `forget` (and later **Allow this one again**) undoes it for good.

**Decided** (13 October 2026).

- **The model file** is trained on Cisco's list, as in step 1. It lives in `model/`, under the GPL like the code, and
  `NOTICE` credits Cisco.
- **Which apps learn.** Every app, Teams included, under the same conditions.

**Open questions.**

- **Updates.** Should the model be refreshed with the nightly lists (it would need a checksum, as releases have) or only
  with a release?
- **Expiry.** Should a learned rule that has not been hit for 90 days expire?
