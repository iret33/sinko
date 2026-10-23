"""
Sinko box: a two-piece, fan-cooled enclosure for the Orange Pi Zero 3 (CadQuery). Version 1.1.

Rebuild the print files:  pip install cadquery shapely svgelements && python3 sinko_case.py
The files land in ./build next to this script, already turned the right way up for printing.
The Sinko mark and wordmark are read from the repository's docs/img (see brand.py).

Coordinate frame = the board's own STEP frame:
  PCB top surface at z = 0, PCB bottom at z = -1.3, board X ±25, Y ±27.5.
  All I/O sits on the +X edge (RJ45, vertical USB-A, vertical USB-C, micro-HDMI).

Open:   USB-C (power) and RJ45 (Ethernet).
Closed: micro-HDMI, USB-A, TF slot, all headers (top fully closed).
Top:    30 x 30 x 7 mm fan pocket (snap-in) above a 14 x 14 x <=6 mm SoC heatsink.

Parts
  LID  — upper shell (top + 4 walls), printed upside-down.
  BASE — thin plinth plate with tongue + standoffs, printed flat.
Fastening: 4x M2.5 x 12 screws (8 to 16 mm fit) from underneath: base standoff -> PCB hole -> lid post.
The posts clamp the board; the lid hovers 0.3 mm over the base as a shadow line.
"""
import math
import cadquery as cq

# ----------------------------------------------------------------- parameters
PCB_TOP, PCB_BOT = 0.0, -1.3
HOLES = [(-22.57, 24.99), (22.49, 24.99), (-22.57, -24.95), (22.49, -24.95)]

WALL = 2.0
TOP_T = 2.0
R_OUT = 6.0                          # vertical corner radius of the lid

# lid outer footprint (square 60.6 x 60.6, board pushed to the +X port wall)
X0, X1 = -32.5, 28.1
Y0, Y1 = -30.3, 30.3

Z_LID_BOT = -4.5                     # bottom edge of lid wall
Z_CEIL = 17.0                        # inside of the top
Z_TOP = Z_CEIL + TOP_T               # 19.0

Z_BASE_BOT = -6.8
Z_BASE_TOP = -4.8                    # floor top / seam
SEAM_GAP = Z_LID_BOT - Z_BASE_TOP    # 0.3 mm designed shadow gap
PLINTH_INSET = 0.8
TONGUE_T, TONGUE_CLR, Z_TONGUE_TOP = 1.2, 0.2, -2.0

# fasteners
POST_R = 2.75
POST_BORE_D = 2.4                    # M2.5 goes in without force and still cuts its thread (2.2 in v1)
POST_BORE_TOP = 13.5                 # deep enough for a 16 mm screw
POST_LEAD_IN = 0.5                   # height of the cone at the mouth of the bore
STANDOFF_R_TOP, STANDOFF_R_LOW, Z_STANDOFF_STEP = 3.0, 3.5, -3.1
SCREW_CLEAR_D = 2.9
CB_D, CB_DEPTH = 5.0, 2.7            # counterbore for M2.5 socket/button head
FOOT_D, FOOT_DEPTH = 10.5, 0.6       # locating recess for 10 mm rubber bumpers

# fan (30 x 30 x 7) — centre on case centre-line, pushed to the back, clear of RJ45
FAN = 30.0
FAN_T = 7.0
FAN_CLR = 0.3
FAN_CX, FAN_CY = -12.0, 0.0
FAN_PAD = 0.8                        # air gap between fan and grille (quieter)
Z_FAN_TOP = Z_CEIL - FAN_PAD         # 16.2
Z_FAN_BOT = Z_FAN_TOP - FAN_T - 0.1  # 9.1 (0.1 slack)

# ports (measured from the STEP at the board edge)
RJ45 = dict(y0=5.67, y1=21.67, z0=0.51, z1=13.81)
USBC = dict(yc=-7.72, zc=5.11)
# RJ45 window: 15.2 x 12.5 mm, 0.8 mm smaller than the jack face each way, so its edge always lands on the metal
RJ45_WIN = dict(y0=6.07, y1=21.27, z0=0.81, z1=13.31)
USBC_W, USBC_H = 4.2, 10.0           # stadium that hugs the socket
# the hole sits in a shallow rounded dish in the outside of the wall, so a cable's plug body goes in far enough to seat
USBC_DISH_W, USBC_DISH_H, USBC_DISH_R, USBC_DISH_DEPTH = 7.0, 12.8, 1.6, 1.2

# Sinko lockup engraved in the top. Reads from the front (-X, the perforated face);
# cables leave from the back (+X). Centred on Y between the grille and the top edge.
ENGRAVE = 0.6
LOGO_CAP = 6.5                         # cap height of the "S" in mm
LOGO_XC = (2.0 + (X1 - 0.9)) / 2       # midway between grille edge and the top chamfer

# grille
GRILLE_RINGS = [4.0, 7.0, 10.0, 13.0]
GRILLE_HOLE = 2.0
GRILLE_PITCH = 3.1


def rrect(x0, x1, y0, y1, r):
    """rounded rectangle sketch on XY (workplane at z=0)"""
    return (cq.Workplane("XY").center((x0 + x1) / 2, (y0 + y1) / 2)
            .rect(x1 - x0, y1 - y0).extrude(1).edges("|Z").fillet(r)
            .faces("<Z").wires().toPending())


def rr_solid(x0, x1, y0, y1, r, z0, z1):
    return (cq.Workplane("XY").workplane(offset=z0)
            .center((x0 + x1) / 2, (y0 + y1) / 2)
            .rect(x1 - x0, y1 - y0).extrude(z1 - z0)
            .edges("|Z").fillet(r))


def cyl(x, y, r, z0, z1):
    return cq.Workplane("XY").workplane(offset=z0).center(x, y).circle(r).extrude(z1 - z0)


def box(x0, x1, y0, y1, z0, z1):
    return (cq.Workplane("XY").workplane(offset=z0)
            .center((x0 + x1) / 2, (y0 + y1) / 2).rect(x1 - x0, y1 - y0).extrude(z1 - z0))


def make_logo(z0, z1):
    """Sinko mark + wordmark as a solid between z0 and z1 (world frame)."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from brand import lockup
    g, b, _ = lockup(cap_mm=LOGO_CAP)
    u_mid, v_mid = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2

    def to_world(ring):   # reading direction -> -Y, up -> +X (a pure rotation, no mirror)
        return [cq.Vector(LOGO_XC + (v - v_mid), -(u - u_mid), z0) for (u, v) in list(ring.coords)[:-1]]

    solids = []
    g = g.simplify(0.01, preserve_topology=True)   # 10 µm: invisible, keeps STEP files small
    for poly in getattr(g, "geoms", [g]):
        outer = cq.Wire.makePolygon(to_world(poly.exterior), close=True)
        inner = [cq.Wire.makePolygon(to_world(i), close=True) for i in poly.interiors]
        face = cq.Face.makeFromWires(outer, inner)
        solids.append(cq.Solid.extrudeLinear(face, cq.Vector(0, 0, z1 - z0)))
    return cq.Workplane("XY").add(cq.Compound.makeCompound(solids))


# ============================================================================ LID
def make_lid(logo=True):
    outer = rr_solid(X0, X1, Y0, Y1, R_OUT, Z_LID_BOT, Z_TOP)
    outer = outer.faces(">Z").edges().chamfer(0.9)         # crisp 45° top edge (prints clean upside-down)
    outer = outer.faces("<Z").edges().chamfer(0.35)        # crisp bottom break
    inner = rr_solid(X0 + WALL, X1 - WALL, Y0 + WALL, Y1 - WALL, R_OUT - WALL,
                     Z_LID_BOT - 1, Z_CEIL)
    lid = outer.cut(inner)

    # --- clamping posts (ceiling -> PCB top) + webs to the side walls
    for (hx, hy) in HOLES:
        post = cyl(hx, hy, POST_R, PCB_TOP, Z_CEIL + 0.5)
        wy = Y1 - WALL + 0.3 if hy > 0 else Y0 + WALL - 0.3
        web = box(hx - 1.2, hx + 1.2, min(hy, wy), max(hy, wy), 1.0, Z_CEIL + 0.5)
        lid = lid.union(post).union(web)
    for (hx, hy) in HOLES:
        lid = lid.cut(cyl(hx, hy, POST_BORE_D / 2, PCB_TOP - 0.1, POST_BORE_TOP))
        # small lead-in chamfer so the screw finds the bore
        lid = lid.cut(cq.Workplane("XY").workplane(offset=PCB_TOP - 0.01).center(hx, hy)
                      .circle(POST_BORE_D / 2 + 0.4).workplane(offset=POST_LEAD_IN)
                      .circle(POST_BORE_D / 2).loft())

    # --- fan pocket: corner pads, 4 snap clips (±Y), 2 locating ribs (±X)
    h = FAN / 2 + FAN_CLR
    fx0, fx1, fy0, fy1 = FAN_CX - h, FAN_CX + h, FAN_CY - h, FAN_CY + h
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = FAN_CX + sx * (FAN / 2 - 2.5), FAN_CY + sy * (FAN / 2 - 2.5)
            lid = lid.union(box(cx - 2.2, cx + 2.2, cy - 2.2, cy + 2.2, Z_FAN_TOP, Z_CEIL + 0.3))

    CLIP_W, CLIP_T, HOOK, Z_CLIP_BOT = 6.0, 1.0, 0.8, Z_FAN_BOT - 1.1
    for cx in (FAN_CX - 6.0, FAN_CX + 7.0):
        for side in (-1, 1):
            yi = fy1 if side > 0 else fy0                       # inner face of tab
            yo = yi + side * CLIP_T
            tab = box(cx - CLIP_W / 2, cx + CLIP_W / 2, min(yi, yo), max(yi, yo),
                      Z_CLIP_BOT, Z_CEIL + 0.3)
            # hook profile in the (Y,Z) plane: catch face at Z_FAN_BOT, lead-in below
            pts = [(yi, Z_CLIP_BOT), (yi - side * HOOK, Z_FAN_BOT - 0.25),
                   (yi - side * HOOK, Z_FAN_BOT), (yi, Z_FAN_BOT)]
            hook = (cq.Workplane("YZ").workplane(offset=cx - CLIP_W / 2)
                    .polyline(pts).close().extrude(CLIP_W))
            lid = lid.union(tab).union(hook)
    for side in (-1, 1):
        xi = fx1 if side > 0 else fx0
        rib = box(min(xi, xi + side * 1.2), max(xi, xi + side * 1.2), FAN_CY - 4, FAN_CY + 4,
                  12.0, Z_CEIL + 0.3)
        lid = lid.union(rib)

    # --- concentric round-hole grille over the fan
    pts = []
    for i, r in enumerate(GRILLE_RINGS):
        n = max(6, round(2 * math.pi * r / GRILLE_PITCH))
        off = (math.pi / n) * (i % 2)
        pts += [(FAN_CX + r * math.cos(off + 2 * math.pi * k / n),
                 FAN_CY + r * math.sin(off + 2 * math.pi * k / n)) for k in range(n)]
    grille = (cq.Workplane("XY").workplane(offset=Z_FAN_TOP - 0.5)
              .pushPoints(pts).circle(GRILLE_HOLE / 2).extrude(Z_TOP - Z_FAN_TOP + 1.5))
    lid = lid.cut(grille)

    # --- Sinko mark + wordmark, engraved
    if logo:
        lid = lid.cut(make_logo(Z_TOP - ENGRAVE, Z_TOP + 1.0))

    # --- exhaust perforation on the back wall (-X), same hole language
    vpts = []
    for row, z in enumerate((3.4, 6.1, 8.8)):
        ncol = 9 if row % 2 == 0 else 8
        for c in range(ncol):
            vpts.append((-(ncol - 1) * 1.55 + c * 3.1, z))
    vents = (cq.Workplane("YZ").workplane(offset=X0 - 1)
             .pushPoints(vpts).circle(GRILLE_HOLE / 2).extrude(WALL + 2))
    lid = lid.cut(vents)

    # --- RJ45 window (just inside the jack face)
    w = RJ45_WIN
    rj = (cq.Workplane("YZ").workplane(offset=X1 - WALL - 1)
          .center((w["y0"] + w["y1"]) / 2, (w["z0"] + w["z1"]) / 2)
          .rect(w["y1"] - w["y0"], w["z1"] - w["z0"])
          .extrude(WALL + 2).edges("|X").fillet(0.6))
    lid = lid.cut(rj)

    # --- USB-C: vertical stadium around the socket, in a rounded dish on the outside
    usbc = (cq.Workplane("YZ").workplane(offset=X1 - WALL - 1)
            .center(USBC["yc"], USBC["zc"]).slot2D(USBC_H, USBC_W, angle=90)
            .extrude(WALL + 2))
    dish = (cq.Workplane("YZ").workplane(offset=X1 - USBC_DISH_DEPTH)
            .center(USBC["yc"], USBC["zc"]).rect(USBC_DISH_W, USBC_DISH_H)
            .extrude(USBC_DISH_DEPTH + 1).edges("|X").fillet(USBC_DISH_R))
    lid = lid.cut(usbc).cut(dish)

    # --- 0.4 mm relief pockets behind the sealed ports (HDMI, USB-A) so a slightly
    #     over-extruded wall can never press on the connector faces
    xi = X1 - WALL
    for (y0, y1, z0, z1) in ((-22.9, -14.0, -0.5, 3.6), (-1.85, 4.85, 0.1, 14.3)):
        lid = lid.cut(box(xi - 0.5, xi + 0.4, y0, y1, z0, z1))
    return lid


# =========================================================================== BASE
def make_base():
    i = PLINTH_INSET
    base = rr_solid(X0 + i, X1 - i, Y0 + i, Y1 - i, R_OUT - i, Z_BASE_BOT, Z_BASE_TOP)
    base = base.faces("<Z").edges().chamfer(0.5)

    # tongue that slips inside the lid walls (alignment + light/dust seal)
    to = WALL + TONGUE_CLR
    ti = to + TONGUE_T
    t_out = rr_solid(X0 + to, X1 - to, Y0 + to, Y1 - to, R_OUT - to, Z_BASE_TOP - 0.2, Z_TONGUE_TOP)
    t_in = rr_solid(X0 + ti, X1 - ti, Y0 + ti, Y1 - ti, R_OUT - ti, Z_BASE_TOP - 1, Z_TONGUE_TOP + 1)
    tongue = t_out.cut(t_in)
    tongue = tongue.faces(">Z").edges().chamfer(0.3)
    base = base.union(tongue)

    keep_in = rr_solid(X0 + to, X1 - to, Y0 + to, Y1 - to, R_OUT - to, Z_BASE_TOP - 1, PCB_BOT + 1)
    for (hx, hy) in HOLES:
        so = (cyl(hx, hy, STANDOFF_R_LOW, Z_BASE_TOP - 0.2, Z_STANDOFF_STEP)
              .union(cyl(hx, hy, STANDOFF_R_TOP, Z_STANDOFF_STEP - 0.1, PCB_BOT)))
        base = base.union(so.intersect(keep_in))      # never pokes past the tongue line
    for (hx, hy) in HOLES:
        base = base.cut(cyl(hx, hy, SCREW_CLEAR_D / 2, Z_BASE_BOT - 1, PCB_BOT + 1))
        base = base.cut(cyl(hx, hy, FOOT_D / 2, Z_BASE_BOT - 1, Z_BASE_BOT + FOOT_DEPTH))
        base = base.cut(cyl(hx, hy, CB_D / 2, Z_BASE_BOT - 1, Z_BASE_BOT + FOOT_DEPTH + CB_DEPTH))
    return base


# ================================================== reference parts (for checks)
def make_fan():
    f = box(FAN_CX - FAN / 2, FAN_CX + FAN / 2, FAN_CY - FAN / 2, FAN_CY + FAN / 2,
            Z_FAN_BOT + 0.1, Z_FAN_TOP)
    f = f.edges("|Z").fillet(1.5)
    f = f.cut(cyl(FAN_CX, FAN_CY, 14.4, Z_FAN_BOT, Z_FAN_TOP + 1))
    f = f.union(cyl(FAN_CX, FAN_CY, 6.5, Z_FAN_BOT + 0.1, Z_FAN_TOP))
    for k in range(7):                             # blades (visual only)
        a = 360 / 7 * k
        bl = (box(FAN_CX + 6.0, FAN_CX + 14.2, FAN_CY - 0.5, FAN_CY + 3.5,
                  Z_FAN_BOT + 1.5, Z_FAN_TOP - 1.5)
              .rotate((FAN_CX, FAN_CY, 0), (FAN_CX, FAN_CY, 1), a))
        f = f.union(bl)
    return f


HS = dict(x=-6.44, y=-0.27, size=14.0, h=6.0, pad=0.3, soc_top=1.2)


def make_heatsink():
    z0 = HS["soc_top"] + HS["pad"]
    s = HS["size"]
    hsk = box(HS["x"] - s / 2, HS["x"] + s / 2, HS["y"] - s / 2, HS["y"] + s / 2, z0, z0 + 1.5)
    n = 6
    for k in range(n):
        fx = HS["x"] - s / 2 + 0.5 + k * (s - 1.0) / (n - 1)
        hsk = hsk.union(box(fx - 0.5, fx + 0.5, HS["y"] - s / 2, HS["y"] + s / 2, z0, z0 + HS["h"]))
    return hsk


if __name__ == "__main__":
    import os
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build")
    os.makedirs(out, exist_ok=True)
    lid, lid_plain, base = make_lid(), make_lid(logo=False), make_base()
    inlay = make_logo(Z_TOP - ENGRAVE, Z_TOP)          # optional flush colour fill for the engraving

    # print orientation: the lid (and its inlay) top face down, the base flat; all lid files share one transform
    ref = lid.val().rotate((0, 0, 0), (1, 0, 0), 180).BoundingBox()

    def lid_xf(w):
        return w.val().rotate((0, 0, 0), (1, 0, 0), 180).translate((-ref.center.x, -ref.center.y, -ref.zmin))

    bb = base.val().BoundingBox()
    parts = {
        "Sinko-case_LID": lid_xf(lid),
        "Sinko-case_LID_no-logo": lid_xf(lid_plain),
        "Sinko-case_LID_logo-inlay_OPTIONAL": lid_xf(inlay),
        "Sinko-case_BASE": base.val().translate((-bb.center.x, -bb.center.y, -bb.zmin)),
    }
    for name, shape in parts.items():
        w = cq.Workplane().add(shape)
        cq.exporters.export(w, os.path.join(out, name + ".stl"), tolerance=0.005, angularTolerance=0.08)
        cq.exporters.export(w, os.path.join(out, name + ".step"))
        b = shape.BoundingBox()
        print(f"{name:36s} {b.xlen:6.2f} x {b.ylen:6.2f} x {b.zlen:6.2f} mm  {shape.Volume() / 1000:6.2f} cm3  valid={shape.isValid()}")
