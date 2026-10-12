"""
Sinko brand lockup -> shapely polygons in millimetres.

Follows the repo's own lockup rule (tools/make-brand.py, social preview):
  * the mark is the glyph without its teal tile (house + door + two signal arcs),
  * the wordmark's baseline sits on the house's floor (y = 427 in the 512 grid),
  * letters (outline extent without pad) : glyph height = 150 : 192.
Strokes are applied the way the SVGs draw them (round joins / caps).

Local lockup frame: u = reading direction (mm), v = up (mm), baseline at v = 0.
"""
import re
import numpy as np
from svgelements import Path, Line, Move, Close
from shapely.geometry import Polygon, LineString, MultiPolygon
from shapely.ops import unary_union
from shapely import affinity

import os
# the committed marks: docs/img/logo.svg and docs/img/wordmark-en.svg at the top of the repository
BRAND = os.environ.get("SINKO_BRAND_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "docs", "img"))

HOUSE_FLOOR = 427.0          # mark grid
WORD_BASELINE = 808.0        # wordmark grid (n, k, i stems end at 808; round letters overshoot to 820)
WORD_STROKE = 28.0
MARK_STROKE_HOUSE = 30.0
MARK_STROKE_ARCS = 26.0


def subpath_rings(d, samples=24):
    """Flatten an SVG path string into a list of point lists, one per subpath."""
    rings, cur = [], []
    for seg in Path(d):
        if isinstance(seg, Move):
            if len(cur) > 1:
                rings.append(cur)
            cur = [(seg.end.x, seg.end.y)]
        elif isinstance(seg, (Line, Close)):
            if seg.end is not None:
                cur.append((seg.end.x, seg.end.y))
        else:
            for t in np.linspace(0, 1, samples)[1:]:
                p = seg.point(t)
                cur.append((p.x, p.y))
    if len(cur) > 1:
        rings.append(cur)
    return rings


def filled(d):
    """Even-odd fill of a compound path (fonts: identical to nonzero)."""
    geom = None
    for r in subpath_rings(d):
        if len(r) < 3:
            continue
        p = Polygon(r).buffer(0)
        geom = p if geom is None else geom.symmetric_difference(p)
    return geom


def paths_of(svg_text):
    return re.findall(r'<path ([^>]*)/>', svg_text)


def attr(a, name):
    m = re.search(r'\b%s="([^"]*)"' % name, a)
    return m.group(1) if m else None


def mark_polygon():
    """House (filled + 30 stroke, round join) minus door, plus two arcs (26 stroke, round caps)."""
    svg = open(f"{BRAND}/logo.svg").read()
    ps = paths_of(svg)
    house = filled(attr(ps[0], "d")).buffer(MARK_STROKE_HOUSE / 2, join_style=1, quad_segs=16)
    door = filled(attr(ps[1], "d"))
    arcs = [LineString(r).buffer(MARK_STROKE_ARCS / 2, cap_style=1, quad_segs=16)
            for r in subpath_rings(attr(ps[2], "d"), samples=48)]
    return unary_union([house.difference(door)] + arcs)


def wordmark_polygon():
    svg = open(f"{BRAND}/wordmark-en.svg").read()
    d = attr(paths_of(svg)[0], "d")
    return filled(d).buffer(WORD_STROKE / 2, join_style=1, quad_segs=12)


def lockup(cap_mm=6.5, gap_ratio=0.40):
    """Return (MultiPolygon in mm, width, v_min, v_max). Baseline at v=0, u starts at 0."""
    word = wordmark_polygon()
    mark = mark_polygon()
    # letters block (outline extent without the pad) = 834-48 = 786 units; glyph extent 79..427 = 348 units
    wb = word.bounds; mb = mark.bounds
    s_w = cap_mm / (820 + WORD_STROKE / 2 - (98 - WORD_STROKE / 2))      # cap height of the S, stroked
    letters_mm = (wb[3] - wb[1]) * s_w
    glyph_mm = letters_mm * 192.0 / 150.0
    s_m = glyph_mm / (mb[3] - mb[1])
    # to (u, v): flip y, scale, put baselines at v = 0
    m = affinity.affine_transform(mark, [s_m, 0, 0, -s_m, -mb[0] * s_m, HOUSE_FLOOR * s_m])
    gap = gap_ratio * letters_mm
    u0 = (mb[2] - mb[0]) * s_m + gap
    w = affinity.affine_transform(word, [s_w, 0, 0, -s_w, u0 - wb[0] * s_w, WORD_BASELINE * s_w])
    g = unary_union([m, w])
    if isinstance(g, Polygon):
        g = MultiPolygon([g])
    b = g.bounds
    info = dict(scale_mark=s_m, scale_word=s_w, glyph_mm=glyph_mm, letters_mm=letters_mm,
                arc_stroke_mm=MARK_STROKE_ARCS * s_m, door_mm=52 * s_m,
                rib_between_arcs_mm=(116 - 62 - MARK_STROKE_ARCS) * s_m)
    return g, b, info


if __name__ == "__main__":
    g, b, info = lockup()
    print("bounds u %.2f..%.2f  v %.2f..%.2f  (%.1f x %.1f mm)" % (b[0], b[2], b[1], b[3], b[2] - b[0], b[3] - b[1]))
    for k, v in info.items():
        print(f"  {k}: {v:.3f}")
    print("polygons:", len(g.geoms), "area mm2: %.1f" % g.area)
    # thinnest engraved feature / thinnest standing rib, via negative buffers
    for t in (0.25, 0.3, 0.35):
        lost = g.area - g.buffer(-t).buffer(t).area
        print(f"  engraved area thinner than {2*t:.1f} mm: {lost:.3f} mm2")
    # preview
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 2.6))
    for p in g.geoms:
        ax.fill(*p.exterior.xy, color="#0F766E")
        for i in p.interiors:
            ax.fill(*i.xy, color="white")
    ax.axhline(0, color="#c9521c", lw=0.6)
    ax.set_aspect("equal"); ax.set_title("Sinko lockup as engraved (mm), baseline in orange")
    fig.savefig(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lockup.png"), dpi=160, bbox_inches="tight")
