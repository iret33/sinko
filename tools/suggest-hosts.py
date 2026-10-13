#!/usr/bin/env python3
"""Suggest hosts that the block lists miss, with a small AI model trained from the lists themselves.

    tools/suggest-hosts.py                         # download Cisco Umbrella's top 1 million names, write host-suggestions.md
    tools/suggest-hosts.py --names FILE            # read the names from FILE instead ("rank,name" or one name a line; .zip too)
    tools/suggest-hosts.py --backtest REF          # train on the lists as they were at git REF and tell which of the hosts
                                                   # added since then the model would have suggested
    tools/suggest-hosts.py --save-model FILE       # also train on everything and write the model (JSON)

Every name a list blocks is an example of its app; every other popular name is an example of "no app". The model
(logistic regression on pieces of the name) learns which pieces mark an app, reads every popular name that no list
blocks, and writes the ones it believes belong to an app into a review file, grouped by app. Nothing it finds goes into
a list by itself: a person checks each suggestion on a real device first (CONTRIBUTING.md). How it works, how well it
does and what it gets wrong: docs/maintainers/host-model.md.

Standard library only; runs on Python 3.9 and newer. The same input gives the same output (no randomness that is not
seeded, nothing that depends on the order of a set).
"""
import argparse
import collections
import datetime
import importlib.machinery
import importlib.util
import io
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UMBRELLA_URL = "https://s3-us-west-1.amazonaws.com/umbrella-static/top-1m.csv.zip"
MAX_DOWNLOAD = 64 * 1024 * 1024         # the zip is about 10 MB; anything much bigger is not the list
MAX_NAMES = 2_000_000

NEGATIVES = 300_000       # ordinary names the model learns from in each half (a sample, to keep a run to minutes)
PER_SITE = 40             # at most this many examples of one app's site, so googlevideo.com does not drown the rest
POSITIVE_SHARE = 0.02     # all the app examples together weigh this much of the ordinary names: a name is rarely an app's
EPOCHS = 6                # passes of the "is it an app's?" stage ...
RATE = 0.5                # ... its AdaGrad step ...
L2 = 1e-4                 # ... and how hard a weight is pulled back to zero
EPOCHS_WHICH = 8          # passes and step of the "which app?" stage
RATE_WHICH = 0.3
PRUNE = 0.05              # weights smaller than this are left out of a saved model
SHOW = 40                 # groups shown per app and section; the rest are counted

REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/~^-]{0,100}\Z")      # never starts with "-": it reaches git's command line


def _box_program():
    """bin/sinko, loaded as a module: how a name is read and scored lives there, so that the box and this training can
    never read a name differently."""
    loader = importlib.machinery.SourceFileLoader("sinko_program", os.path.join(ROOT, "bin", "sinko"))
    spec = importlib.util.spec_from_loader("sinko_program", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


box = _box_program()
SHARED, NEVER, HOST_RE, THRESHOLD = box.SHARED, box.NEVER, box.HOST_RE, box.MODEL_THRESHOLD
site, unwrap, app_labels, features, sigmoid = box.site, box.unwrap, box.app_labels, box.features, box.sigmoid
Cover, Model, app_words, matcher, carries, zone = box.Cover, box.Model, box.app_words, box.matcher, box.carries, box.zone


def say(text):
    print(text, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Lists and names
# --------------------------------------------------------------------------- #
def lists_at(ref, root=ROOT):
    """The lists as they were at git `ref`."""
    if not REF_RE.match(ref):
        raise ValueError("not a git reference: %r" % ref)
    files = subprocess.run(["git", "-C", root, "ls-tree", "--name-only", ref, "lists/"], check=True,
                           capture_output=True, text=True).stdout.split()
    lists = {}
    for path in sorted(files):
        name = os.path.basename(path)
        if name.endswith(".txt") and name != "guard.txt":
            text = subprocess.run(["git", "-C", root, "show", "%s:%s" % (ref, path)], check=True,
                                  capture_output=True, text=True).stdout
            lists[name[:-4]] = box.parse_block_list(text)
    return lists


def parse_names(lines):
    """Host names from "rank,name" or bare lines, lowercased, without duplicates, in their order; junk is skipped."""
    seen = {}
    for line in lines:
        name = line.strip().rsplit(",", 1)[-1].strip().lower().rstrip(".")
        if len(name) <= 253 and HOST_RE.match(name) and name not in seen:
            seen[name] = None
            if len(seen) >= MAX_NAMES:
                break
    return list(seen)


def read_names(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            if len(members) != 1:
                raise ValueError("%s should hold one file, it holds %d" % (path, len(members)))
            with zf.open(members[0]) as fh:
                return parse_names(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"))
    with open(path, encoding="utf-8", errors="replace") as fh:
        return parse_names(fh)


def download(url, dest):
    with urllib.request.urlopen(url, timeout=60) as resp, open(dest, "wb") as out:
        total = 0
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD:
                raise ValueError("%s is bigger than %d MB" % (url, MAX_DOWNLOAD >> 20))
            out.write(chunk)


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #
def train(lists, names, cover=None, words=None, skip=lambda s: False, seed=7):
    """Learns from `lists` (the examples of each app) and `names`: a name some list blocks is one more example of its
    app; a name that carries an app's word but is not listed is left out (it is probably the app's, and teaching it as
    "no app" would teach the model to miss exactly what it is for); the rest, except those whose site `skip` says to
    keep away, are ordinary names. Returns a pruned Model."""
    rnd = random.Random(seed)
    apps = sorted(lists)
    index = {sid: i for i, sid in enumerate(apps)}
    cover = cover or Cover(lists)
    every_word = matcher(set().union(*(words or app_words(lists)).values()))
    by_site = collections.OrderedDict()
    for sid in apps:
        for d in lists[sid]:
            by_site.setdefault(site(d), {})[d] = sid
    ordinary = []
    for name in names:
        sid = cover(name)
        if sid:
            by_site.setdefault(site(name), {})[name] = sid
        elif not skip(site(name)) and not carries(name, every_word):
            ordinary.append(name)
    if len(ordinary) > NEGATIVES:
        ordinary = rnd.sample(ordinary, NEGATIVES)

    vocab = {}
    positives = []                                   # (feature ids, app index, weight)
    for rows in by_site.values():
        rows = list(rows.items())
        if len(rows) > PER_SITE:
            rows = rnd.sample(rows, PER_SITE)
        for name, sid in rows:
            ids = tuple(vocab.setdefault(f, len(vocab)) for f in features(name))
            if ids:
                positives.append((ids, index[sid], 1.0 / math.sqrt(len(rows))))
    if not positives:
        raise ValueError("the lists give nothing to learn from")
    boost = POSITIVE_SHARE * max(len(ordinary), 1) / sum(w for _, _, w in positives)
    examples = [(ids, 1, w * boost) for ids, _, w in positives]
    examples += [(tuple(vocab[f] for f in features(n) if f in vocab), 0, 1.0) for n in ordinary]

    # Stage 1, "is it an app's?": logistic regression, AdaGrad, L2 applied to the weights a name touches.
    w, h = [0.0] * len(vocab), [1e-8] * len(vocab)
    b, hb = 0.0, 1e-8
    for _ in range(EPOCHS):
        rnd.shuffle(examples)
        for ids, y, weight in examples:
            g = (sigmoid(b + sum(w[i] for i in ids)) - y) * weight
            hb += g * g
            b -= RATE * g / math.sqrt(hb)
            for i in ids:
                gi = g + L2 * w[i]
                h[i] += gi * gi
                w[i] -= RATE * gi / math.sqrt(h[i])

    # Stage 2, "which app?": softmax over the apps, on the app examples only.
    k = len(apps)
    w2 = [None] * len(vocab)
    b2 = [0.0] * k
    for epoch in range(EPOCHS_WHICH):
        rnd.shuffle(positives)
        rate = RATE_WHICH / (1 + epoch)
        for ids, y, weight in positives:
            z = list(b2)
            for i in ids:
                if w2[i]:
                    for c, v in w2[i].items():
                        z[c] += v
            top = max(z)
            e = [math.exp(v - top) for v in z]
            total = sum(e)
            for c in range(k):
                g = (e[c] / total - (1.0 if c == y else 0.0)) * weight
                if abs(g) < 1e-4:
                    continue
                b2[c] -= rate * g
                for i in ids:
                    if w2[i] is None:
                        w2[i] = {}
                    w2[i][c] = w2[i].get(c, 0.0) - rate * g

    names_of = sorted(vocab, key=vocab.get)
    w1 = {f: round(w[i], 3) for i, f in enumerate(names_of) if abs(w[i]) >= PRUNE}
    rows = {}
    for i, f in enumerate(names_of):
        row = sorted((c, round(v, 3)) for c, v in (w2[i] or {}).items() if abs(v) >= PRUNE)
        if row:
            rows[f] = row
    return Model(apps, round(b, 3), w1, [round(v, 3) for v in b2], rows)


def fold(s):
    return zlib.crc32(s.encode()) & 1


def cross_scored(lists, names, progress=say):
    """Scores every name that no list blocks with a model that never saw its site as an ordinary name (two models,
    each trained on one half of the sites and used on the other), so that a site counts as new to the model, as it
    would be in real life. Returns ([(score, app, name)], the two models)."""
    cover = Cover(lists)
    words = app_words(lists)
    models = []
    for half in (0, 1):
        progress("training the model on half %d of the sites ..." % (half + 1))
        models.append(train(lists, names, cover, words, skip=lambda s, half=half: fold(s) != half))
    progress("reading %d names ..." % len(names))
    scored = []
    for name in names:
        if cover(name):
            continue
        p, sid = models[1 - fold(site(name))].score(name)
        if p >= THRESHOLD:
            scored.append((p, sid, name))
    return scored, models


# --------------------------------------------------------------------------- #
# From scored names to a review file
# --------------------------------------------------------------------------- #
def shape(z, rx):
    """A zone with the labels that are neither the app's word nor part of its site written as "*": the 801
    instagram.<city>.fna.fbcdn.net hosts are one shape, so they are reviewed as one line."""
    labels = z.split(".")
    keep = len(site(z).split("."))
    return tuple(label if (i >= len(labels) - keep or rx.search(label)) else "*"
                 for i, label in enumerate(labels))


def pattern(zones):
    """A Pi-hole regex that matches every zone of one shape (and the names under them). Labels hold only letters,
    digits, "_" and "-", none of them special outside brackets, so they are written as they are."""
    parts = []
    for column in zip(*(z.split(".") for z in zones)):
        parts.append(column[0] if len(set(column)) == 1 else "[a-z0-9_-]+")
    return r"(^|\.)" + r"\.".join(parts) + "$"


Group = collections.namedtuple("Group", "app kind line zones names score examples note")
KINDS = (("site", "New sites that carry the app's own word"),
         ("alias", "On somebody else's site: block only what the line shows"),
         ("model", "The model alone (weaker: check twice)"))


def group(scored, lists, judge=None):
    """Turns (score, app, name) rows into review lines: one per zone, or one per shape when several zones share it.
    `judge(name)` -> (score, app) is asked about the site of a line the model alone suggests: when the site's own name
    does not look like the app's, the model read the first part of the names (rr1---sn-x.gvt1.com looks like a YouTube
    video server, but gvt1.com is Google's download network), and the site is not offered as a whole."""
    rx = {sid: matcher(w) for sid, w in app_words(lists).items()}
    branded = collections.defaultdict(lambda: collections.defaultdict(list))    # (app, shape) -> zone -> rows
    alone = collections.defaultdict(list)                                       # (app, zone) -> rows
    for p, sid, name in scored:
        z = zone(name, rx[sid])
        if z is not None:
            branded[(sid, shape(z, rx[sid]))][z].append((p, name))
        else:
            s = site(name)
            alone[(sid, name if s in NEVER else s)].append((p, name))
    groups = []
    for (sid, _), zones in branded.items():
        rows = sorted((r for rs in zones.values() for r in rs), key=lambda r: (-r[0], r[1]))
        if len(zones) == 1:
            z = next(iter(zones))
            if z in NEVER:
                continue
            line = "||%s^" % z
            s = site(z)
            if z == s or carries(s, rx[sid]):
                kind, note = "site", ""
            else:
                kind, note = "alias", "under %s, which is not this app's: block only this, never %s" % (s, s)
        else:
            line = "/%s/" % pattern(sorted(zones))
            kind, note = "alias", "%d hosts of one shape: a list cannot hold a pattern, this needs a rule" % len(zones)
        groups.append(Group(sid, kind, line, len(zones), len(rows), rows[0][0], [n for _, n in rows[:3]], note))
    for (sid, z), rows in alone.items():
        if z in NEVER:
            continue
        rows.sort(key=lambda r: (-r[0], r[1]))
        s = site(z)
        if s in NEVER:
            line, note = z, "this exact name only: it is on %s, which is never blocked as a whole" % s
        elif judge is not None and z == s and judge(s)[0] < THRESHOLD:
            line, note = "*.%s" % s, "the model read the first part of these names: %s itself does not look like " \
                                     "this app's, never block it whole" % s
        else:
            line, note = "||%s^" % z, ""
        groups.append(Group(sid, "model", line, 1, len(rows), rows[0][0], [n for _, n in rows[:3]], note))
    rank = {kind: i for i, (kind, _) in enumerate(KINDS)}
    groups.sort(key=lambda g: (g.app, rank[g.kind], -g.names, -g.score, g.line))
    return groups


def render(groups, lists, source, count, when=None, model_bytes=None):
    when = when or datetime.date.today().isoformat()
    by_app = collections.defaultdict(list)
    for g in groups:
        by_app[g.app].append(g)
    entries = sum(len(v) for v in lists.values())
    out = ["# Host suggestions, %s" % when, "",
           "A small AI model learned from the block lists (%d apps, %d entries) which pieces of a name mark an app, then "
           "read %s names from %s. These are the names that no list blocks and that it is at least %d%% sure belong to "
           "an app." % (len(lists), entries, format(count, ","), source, round(THRESHOLD * 100)), "",
           "**Every line is a guess.** Check each one on a real device before it goes into a list (CONTRIBUTING.md); "
           "how to read this file: docs/maintainers/host-model.md.", ""]
    if model_bytes:
        out += ["Model size: %d KB." % (model_bytes // 1024), ""]
    order = sorted(by_app, key=lambda a: (-sum(g.names for g in by_app[a]), a))
    out += ["| App | Names | Lines |", "|---|---:|---:|"]
    out += ["| %s | %d | %d |" % (a, sum(g.names for g in by_app[a]), len(by_app[a])) for a in order]
    for a in order:
        out += ["", "## %s" % a]
        for kind, title in KINDS:
            rows = [g for g in by_app[a] if g.kind == kind]
            if not rows:
                continue
            out += ["", "### " + title, ""]
            for g in rows[:SHOW]:
                more = " (+%d more)" % (g.names - len(g.examples)) if g.names > len(g.examples) else ""
                note = " _%s_" % g.note if g.note else ""
                out.append("- [ ] `%s` %.3f, %d name%s: %s%s%s" % (
                    g.line, g.score, g.names, "" if g.names == 1 else "s", ", ".join("`%s`" % e for e in g.examples),
                    more, note))
            if len(rows) > SHOW:
                out.append("- and %d more lines" % (len(rows) - SHOW))
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Backtest: would the model have found what was later added by hand?
# --------------------------------------------------------------------------- #
def backtest(old, new, names, progress=say):
    """Trains on `old` lists (with `names`) and scores each host that `new` has and `old` did not. Returns rows of
    (app, host, score, guessed app, verdict) and the number found."""
    added = [(sid, d) for sid in sorted(new) for d in new[sid] if d not in set(old.get(sid, ()))]
    _, models = cross_scored(old, names, progress)
    rx = {sid: matcher(w) for sid, w in app_words(old).items()}
    rows, found = [], 0
    for sid, d in added:
        if sid not in old:
            rows.append((sid, d, 0.0, None, "the app was not in the lists then"))
            continue
        p, guess = models[1 - fold(site(d))].score(d)
        if p >= THRESHOLD and guess == sid:
            found += 1
            verdict = "found" if zone(d, rx[sid]) else "found (the model alone)"
        elif p >= THRESHOLD:
            verdict = "flagged as %s" % guess
        else:
            verdict = "missed"
        rows.append((sid, d, p, guess, verdict))
    return rows, found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--names", help="names to read: a file with \"rank,name\" or one name a line, or a zip of one "
                                    "(default: download Cisco Umbrella's top 1 million)")
    ap.add_argument("--lists", default=os.path.join(ROOT, "lists"), help="the lists folder (default: lists/)")
    ap.add_argument("--out", default="host-suggestions.md", help="the review file to write (default: %(default)s)")
    ap.add_argument("--backtest", metavar="REF", help="train on the lists at git REF and report on the hosts added since")
    ap.add_argument("--save-model", metavar="FILE", help="also train one model on everything and write it as JSON")
    args = ap.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        if args.names:
            source, names = os.path.basename(args.names), read_names(args.names)
        else:
            say("downloading %s ..." % UMBRELLA_URL)
            path = os.path.join(tmp, "top-1m.csv.zip")
            download(UMBRELLA_URL, path)
            source, names = "Cisco Umbrella's top 1 million", read_names(path)
    if not names:
        say("no names to read")
        return 1
    lists = box.load_app_lists(args.lists)

    if args.backtest:
        rows, found = backtest(lists_at(args.backtest), lists, names)
        width = max([len(d) for _, d, *_ in rows] + [4])
        for sid, d, p, guess, verdict in rows:
            print("%-16s %-*s %.3f  %s" % (sid, width, d, p, verdict))
        print("found %d of the %d hosts added since %s" % (found, len(rows), args.backtest))
        return 0

    scored, models = cross_scored(lists, names)
    model_bytes = None
    if args.save_model:
        say("training one model on everything ...")
        blob = json.dumps(train(lists, names).to_json(), separators=(",", ":"), sort_keys=True)
        with open(args.save_model, "w", encoding="utf-8") as fh:
            fh.write(blob)
        model_bytes = len(blob)
    groups = group(scored, lists, judge=lambda name: models[1 - fold(site(name))].score(name))
    text = render(groups, lists, source, len(names), model_bytes=model_bytes)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    say("%d names suggested; wrote %s" % (len(scored), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
