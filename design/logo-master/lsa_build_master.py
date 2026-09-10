"""LSA wordmark: raster -> precise geometric master SVG.

Pipeline
--------
1. Subpixel 0.5-isocontour of the source raster (marching squares on a 4x
   bilinear upscale, so sample spacing is 0.25 source px).
2. Ramer-Douglas-Peucker segmentation at a tolerance just above the source's
   own edge noise (measured at 0.30 px max), so a straight edge never gets
   split by anti-aliasing wobble.
3. Per-arc total-least-squares line fit; an arc is straight when its max
   deviation stays under STRAIGHT_TOL.
4. Collinear merge, then sliver removal (a 1-2 px edge at a near-right-angle
   corner is anti-aliasing, but the blunt tip of a tapered wedge is real, so
   the true corner has to land close by before the sliver is dropped).
5. Curve-run detection: consecutive short arcs that turn consistently in one
   direction are one real curve, not a polygon corner. Then bow detection:
   long chains of near-collinear straights that bow by more than a pixel are
   the mark's gently curved diagonals and become curves too.
6. Curve/straight joints moved to the true tangency point, where the contour
   actually departs from the straight edge's fitted line.
7. Vertices computed as line-line intersections, never taken from a contour
   sample, so anti-aliasing at a corner cannot pull it. Each straight/curve
   joint is classified: matching directions mean a real tangency (project and
   inherit the tangent, G1), disagreeing ones mean a real corner (intersect
   the straight with the curve's own end tangent).
8. Italic-slant snapping: straight edges inside a tight band around the
   dominant stem slant rotate onto one shared angle about their own centroid.
9. Curves become cubics split on turning angle (bounded turn means bounded
   error), refined by bisection only while it still buys accuracy.
10. Emit one <path>, one subpath per closed contour, fill via currentColor,
    viewBox cropped to the ink box plus a uniform margin.

Deps: see requirements.txt (numpy, pillow, scikit-image, scipy)
Run:  python build_master.py   then   python make_deliverables.py
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import numpy as np
from PIL import Image
from skimage import measure

# ---------------------------------------------------------------- parameters
SOURCE_PNG = ("/Users/alkautsar/Documents/larisamaarnold/scripts/rebrand-ab/"
              "out/logos7/r7_ref09_nbpro_t1.png")
CROP = (777, 203, 124, 411)       # w, h, x, y: ink bbox of SOURCE_PNG plus 4 px
SRC_GRAY_4X = "gray4x.png"        # 4x bilinear upscale of the cropped source
UPSCALE = 4.0
MIN_AREA = 20.0                   # px^2; below this a contour is generator speckle

RDP_EPS = 0.62                    # px; source edge noise measures ~0.30 px max
STRAIGHT_TOL = 0.42               # px; max deviation for "this arc is a line"
COLLINEAR_DEG = 0.80              # merge adjacent straight edges under this
SLIVER_LEN = 2.6                  # px; drop straight arcs shorter than this
SLIVER_MAX_EXT = 4.5              # px; only if the true corner is this close
EDGE_TRIM = 0.18                  # fraction of each arc dropped at both ends

CURVE_SEG_MAX = 26.0              # px; arcs shorter than this can join a curve run
CURVE_TURN_MAX = 55.0             # deg; per-joint turn allowed inside a curve run
CURVE_TOTAL_MIN = 18.0            # deg; a run must bend at least this much

SLANT_BAND_DEG = 1.2              # +-band around the dominant slant to snap
SLANT_SNAP_DEG = 1.2              # only snap if the band's spread is under this
SLANT_MIN_LEN = 40.0              # px; only real stems vote on the slant
AXIS_SNAP_DEG = 0.8               # snap near-horizontal / near-vertical edges

MARGIN_FRAC = 0.04                # viewBox margin, fraction of ink width
VB_H = 100.0                      # master viewBox height (width derived)
DEC = 2                           # coordinate decimals


# ---------------------------------------------------------------- geometry
def signed_area(p):
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def fit_line(pts):
    """Total least squares line. Returns (point_on_line, unit_direction)."""
    c = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
    d = vt[0]
    return c, d / np.linalg.norm(d)


def line_dev(pts, c, d):
    n = np.array([-d[1], d[0]])
    return (pts - c) @ n


def intersect(c1, d1, c2, d2):
    a = np.array([[d1[0], -d2[0]], [d1[1], -d2[1]]])
    if abs(np.linalg.det(a)) < 1e-9:
        return None
    t = np.linalg.solve(a, c2 - c1)
    return c1 + t[0] * d1


def ang_of(d):
    """Undirected line angle in degrees, folded to [0, 180)."""
    return math.degrees(math.atan2(d[1], d[0])) % 180.0


def ang_gap(a, b):
    g = abs(a - b) % 180.0
    return min(g, 180.0 - g)


# ---------------------------------------------------------------- RDP
def rdp_indices(pts, eps):
    """Douglas-Peucker on an open chain; returns kept indices."""
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        ab = b - a
        n = np.linalg.norm(ab)
        seg = pts[i + 1:j]
        if n < 1e-12:
            dist = np.linalg.norm(seg - a, axis=1)
        else:
            u = ab / n
            nrm = np.array([-u[1], u[0]])
            dist = np.abs((seg - a) @ nrm)
        k = int(np.argmax(dist))
        if dist[k] > eps:
            k += i + 1
            keep[k] = True
            stack.append((i, k))
            stack.append((k, j))
    return np.nonzero(keep)[0].tolist()


def rdp_closed(pts, eps):
    """Douglas-Peucker on a closed contour, seeded by the farthest point pair."""
    c = pts.mean(axis=0)
    i0 = int(np.argmax(np.linalg.norm(pts - c, axis=1)))
    rolled = np.roll(pts, -i0, axis=0)
    i1 = int(np.argmax(np.linalg.norm(rolled - rolled[0], axis=1)))
    a = rdp_indices(rolled[:i1 + 1], eps)
    b = rdp_indices(rolled[i1:], eps)
    idx = sorted(set(a) | {i1 + k for k in b})
    idx = [k for k in idx if k < len(rolled)]
    return sorted({(k + i0) % len(pts) for k in idx})


# ---------------------------------------------------------------- arc model
class Arc:
    """One stretch of contour between two vertex indices on the raw contour."""

    def __init__(self, pts, i0, i1):
        n = len(pts)
        self.i0, self.i1 = i0, i1
        idx = [(i0 + k) % n for k in range((i1 - i0) % n + 1)]
        self.pts = pts[idx]
        self.straight = False
        self.forced_curve = False
        self.c = None
        self.d = None
        self.dev = 0.0
        self.p0 = None
        self.p1 = None
        self.t0 = None
        self.t1 = None
        self.forced_p0 = None
        self.forced_p1 = None
        self.forced_t0 = None
        self.forced_t1 = None

    def core(self):
        m = len(self.pts)
        t = int(round(m * EDGE_TRIM))
        if m - 2 * t < 4:
            t = max(0, (m - 4) // 2)
        return self.pts[t:m - t] if m - 2 * t >= 2 else self.pts

    def classify(self):
        core = self.core()
        if len(core) < 3:
            core = self.pts
        if len(core) < 2:
            self.straight = True
            self.c, self.d = self.pts[0], np.array([1.0, 0.0])
            return
        self.c, self.d = fit_line(core)
        self.dev = float(np.abs(line_dev(core, self.c, self.d)).max())
        self.straight = (not self.forced_curve) and self.dev <= STRAIGHT_TOL

    def chord(self):
        return float(np.linalg.norm(self.pts[-1] - self.pts[0]))

    def dir_chord(self):
        v = self.pts[-1] - self.pts[0]
        n = np.linalg.norm(v)
        return v / n if n > 1e-12 else np.array([1.0, 0.0])


def build_arcs(pts, verts):
    return [Arc(pts, verts[i], verts[(i + 1) % len(verts)])
            for i in range(len(verts))]


def merge_collinear(arcs, pts):
    changed = True
    while changed and len(arcs) > 3:
        changed = False
        for i in range(len(arcs)):
            j = (i + 1) % len(arcs)
            a, b = arcs[i], arcs[j]
            if not (a.straight and b.straight):
                continue
            if ang_gap(ang_of(a.d), ang_of(b.d)) > COLLINEAR_DEG:
                continue
            m = Arc(pts, a.i0, b.i1)
            m.classify()
            if not m.straight:
                continue
            if j == 0:
                arcs = arcs[1:-1] + [m]
            else:
                arcs = arcs[:i] + [m] + arcs[j + 1:]
            changed = True
            break
    return arcs


def drop_slivers(arcs, pts):
    while len(arcs) > 4:
        cut = None
        for i, a in enumerate(arcs):
            prv, nxt = arcs[i - 1], arcs[(i + 1) % len(arcs)]
            if not (a.straight and prv.straight and nxt.straight):
                continue
            if a.chord() >= SLIVER_LEN:
                continue
            if ang_gap(ang_of(prv.d), ang_of(nxt.d)) < 2.0:
                continue
            p = intersect(prv.c, prv.d, nxt.c, nxt.d)
            if p is None:
                continue
            mid = 0.5 * (a.pts[0] + a.pts[-1])
            if np.linalg.norm(p - mid) > SLIVER_MAX_EXT:
                continue
            cut = i
            break
        if cut is None:
            break
        a = arcs[cut]
        prv = arcs[cut - 1]
        merged = Arc(pts, prv.i0, a.i1)
        merged.classify()
        merged.straight = True
        merged.c, merged.d = prv.c, prv.d
        arcs[cut - 1] = merged
        arcs.pop(cut)
    return arcs


def detect_curve_runs(arcs, pts):
    """Fuse maximal cyclic runs of short, consistently-turning arcs into
    a single curved arc. A polygon corner turns hard at one joint; a real
    curve spreads its turn over several short arcs, which is what we catch."""
    n = len(arcs)
    if n < 4:
        return arcs

    def turn(i):
        a, b = arcs[i % n], arcs[(i + 1) % n]
        d1, d2 = a.dir_chord(), b.dir_chord()
        return math.degrees(math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1 @ d2))

    elig = [(a.chord() < CURVE_SEG_MAX) or a.forced_curve for a in arcs]
    if all(elig):
        return arcs
    start = next(i for i in range(n) if not elig[i])
    order = [(start + k) % n for k in range(n)]

    runs, cur, sign = [], [], 0
    for pos, i in enumerate(order):
        if not elig[i]:
            if len(cur) >= 2:
                runs.append(cur)
            cur, sign = [], 0
            continue
        if not cur:
            cur, sign = [i], 0
            continue
        t = turn(order[pos - 1])
        s = 1 if t > 0 else -1
        if abs(t) > CURVE_TURN_MAX or abs(t) < 0.8 or (sign and s != sign):
            if len(cur) >= 2:
                runs.append(cur)
            cur, sign = [i], 0
        else:
            cur.append(i)
            sign = s
    if len(cur) >= 2:
        runs.append(cur)

    keep = []
    for run in runs:
        total = sum(abs(turn(run[k])) for k in range(len(run) - 1))
        if total >= CURVE_TOTAL_MIN or any(arcs[k].forced_curve for k in run):
            keep.append(run)
    if not keep:
        return arcs

    replace, drop = {}, set()
    for run in keep:
        m = Arc(pts, arcs[run[0]].i0, arcs[run[-1]].i1)
        m.forced_curve = True
        m.classify()
        replace[run[0]] = m
        drop.update(run[1:])
    return [replace.get(i, a) for i, a in enumerate(arcs) if i not in drop]


TANGENT_TOL = 0.28      # px; contour is still "on the line" within this
TANGENT_RUN = 8         # samples (2 px) it must stay off the line to count


def _departure(pts, idx_seq, c, d, tol=TANGENT_TOL, run=TANGENT_RUN):
    """First position in idx_seq where the contour leaves the line for good."""
    dev = np.abs(line_dev(pts[idx_seq], c, d))
    over = dev > tol
    for p in range(len(over) - run):
        if over[p:p + run].all():
            return p
    return max(0, len(over) - 1)


def snap_curve_bounds(arcs, pts):
    """Move each curve/straight junction to the true tangency point.

    Whatever RDP picked as the boundary is a sampling artefact; the real
    boundary is where the contour departs from the straight edge's own fitted
    line. Getting this right is what lets the cubics be both few and exact.
    """
    n = len(pts)
    m = len(arcs)

    def seq(i0, i1):
        return [(i0 + k) % n for k in range((i1 - i0) % n + 1)]

    for i in range(m):
        cur = arcs[i]
        if cur.straight:
            continue
        prv, nxt = arcs[(i - 1) % m], arcs[(i + 1) % m]
        if prv.straight and not prv.forced_curve and \
                ang_gap(ang_of(prv.d), ang_of(end_line(cur.pts, True)[1])) <= CORNER_GAP:
            s = seq(prv.i0, cur.i1)
            lim = int(len(seq(prv.i0, prv.i1)) * 0.55)
            p = _departure(pts, s, prv.c, prv.d)
            p = max(p, lim)
            nb = s[p]
            if (nb - prv.i0) % n > 8 and (cur.i1 - nb) % n > 16:
                prv.__init__(pts, prv.i0, nb)
                prv.classify()
                cur.__init__(pts, nb, cur.i1)
                cur.forced_curve = True
                cur.classify()
        if nxt.straight and not nxt.forced_curve and \
                ang_gap(ang_of(nxt.d), ang_of(end_line(cur.pts, False)[1])) <= CORNER_GAP:
            # walk backwards from the far end of the next straight edge
            s = [(nxt.i1 - k) % n for k in range((nxt.i1 - cur.i0) % n + 1)]
            lim = int(len(seq(nxt.i0, nxt.i1)) * 0.55)
            p = _departure(pts, s, nxt.c, nxt.d)
            p = max(p, lim)
            nb = s[p]
            if (nxt.i1 - nb) % n > 8 and (nb - cur.i0) % n > 16:
                nxt.__init__(pts, nb, nxt.i1)
                nxt.classify()
                cur.__init__(pts, cur.i0, nb)
                cur.forced_curve = True
                cur.classify()
    return arcs


CORNER_GAP = 5.0        # deg; above this a straight/curve joint is a real corner


def end_line(pts, at_start, span_px=3.5):
    """TLS line through the first (or last) span_px of arclength, oriented
    along travel. This is the curve's own tangent line at that end."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    if at_start:
        k = int(np.searchsorted(cum, span_px)) + 1
        sub = pts[:max(4, min(k, len(pts)))]
        ref = sub[-1] - sub[0]
    else:
        k = int(np.searchsorted(cum, cum[-1] - span_px))
        sub = pts[min(k, len(pts) - 4):]
        ref = sub[-1] - sub[0]
    c, d = fit_line(sub)
    if d @ ref < 0:
        d = -d
    return c, d


WEDGE_TIP_LEN = 4.0     # px; a shorter edge between two near-parallel flanks
WEDGE_MAX_ANGLE = 12.0  # deg; flank divergence that still counts as a wedge
WEDGE_SPAN = 40.0       # px of flank used to aim the apex


def span_line(pts, at_start, span_px, skip_px=1.5):
    """TLS line over span_px of arclength from one end, skipping the very tip
    (which is sub-pixel and noisy), oriented along travel."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    if at_start:
        lo = int(np.searchsorted(cum, skip_px))
        hi = int(np.searchsorted(cum, skip_px + span_px)) + 1
    else:
        hi = len(pts) - int(np.searchsorted(cum, skip_px))
        lo = len(pts) - int(np.searchsorted(cum, skip_px + span_px)) - 1
    lo, hi = max(0, lo), min(len(pts), hi)
    if hi - lo < 4:
        lo, hi = 0, len(pts)
    sub = pts[lo:hi]
    c, d = fit_line(sub)
    if d @ (sub[-1] - sub[0]) < 0:
        d = -d
    return c, d


def close_wedge_tips(arcs, pts):
    """Terminate acute tapered wedges in a real point.

    The speed-cut slashes end in a hairline that the raster can only render as
    a blunt sub-pixel stub. Left alone the master stops a few pixels short of
    where the artwork's own taper is heading, so the apex is reconstructed by
    intersecting the two flanks aimed over WEDGE_SPAN of their length.
    """
    m = len(arcs)
    out = []
    for i in range(m):
        t = arcs[i]
        if not t.straight or t.chord() >= WEDGE_TIP_LEN:
            continue
        prv, nxt = arcs[(i - 1) % m], arcs[(i + 1) % m]
        if prv is t or nxt is t or prv is nxt:
            continue
        cb, db = span_line(prv.pts, False, WEDGE_SPAN)
        ca, da = span_line(nxt.pts, True, WEDGE_SPAN)
        if ang_gap(ang_of(db), ang_of(da)) > WEDGE_MAX_ANGLE:
            continue
        apex = intersect(cb, db, ca, da)
        if apex is None:
            continue
        mid = 0.5 * (t.pts[0] + t.pts[-1])
        reach = float(np.linalg.norm(apex - mid))
        # the apex must sit beyond the stub, along the wedge, and not run away
        if reach > 40.0 or (apex - mid) @ db <= 0:
            continue
        out.append((i, apex, db, da))
    if not out:
        return arcs

    drop = set()
    for i, apex, db, da in out:
        m_ = len(arcs)
        prv, nxt = arcs[(i - 1) % m_], arcs[(i + 1) % m_]
        prv.forced_p1 = apex
        prv.forced_t1 = db
        nxt.forced_p0 = apex
        nxt.forced_t0 = da
        if prv.straight:
            prv.c, prv.d = apex, db
        if nxt.straight:
            nxt.c, nxt.d = apex, da
        drop.add(i)
    return [a for j, a in enumerate(arcs) if j not in drop]


BOW_MIN = 1.2           # px; a straight chain bowing more than this is a curve
BOW_GAP_MAX = 3.5       # deg; per-joint angle change allowed inside a bow


def detect_bows(arcs, pts):
    """Turn long chains of near-collinear straight arcs into one gentle curve.

    The mark's long diagonals are not dead straight, they bow by a few pixels
    over a couple of hundred. Left as a chain of L segments that reads as
    faceting once the logo is set large, so it becomes a single cubic instead.
    """
    n, m = len(pts), len(arcs)
    if m < 4:
        return arcs

    def chain_dev(run):
        idx = [(arcs[run[0]].i0 + k) % n
               for k in range((arcs[run[-1]].i1 - arcs[run[0]].i0) % n + 1)]
        p = pts[idx]
        c, d = fit_line(p)
        return float(np.abs(line_dev(p, c, d)).max())

    def grow(i):
        run = [i]
        prev_sign = 0
        while len(run) < m - 2:
            j = (run[-1] + 1) % m
            if j == i or not arcs[j].straight:
                break
            a0 = ang_of(arcs[run[-1]].d)
            a1 = ang_of(arcs[j].d)
            if ang_gap(a0, a1) > BOW_GAP_MAX:
                break
            delta = (a1 - a0 + 90.0) % 180.0 - 90.0
            sign = 1 if delta > 0 else -1
            if prev_sign and sign != prev_sign:
                break
            prev_sign = sign
            run.append(j)
        return run

    used, picks = set(), []
    for i in range(m):
        if i in used or not arcs[i].straight:
            continue
        run = grow(i)
        while len(run) >= 2 and (set(run) & used or chain_dev(run) < BOW_MIN):
            if set(run) & used:
                break
            run = run[:-1]
        if len(run) >= 2 and not (set(run) & used) and chain_dev(run) >= BOW_MIN:
            picks.append(run)
            used.update(run)
    if not picks:
        return arcs

    replace, drop = {}, set()
    for run in picks:
        c = Arc(pts, arcs[run[0]].i0, arcs[run[-1]].i1)
        c.forced_curve = True
        c.classify()
        replace[run[0]] = c
        drop.update(run[1:])
    return [replace.get(i, a) for i, a in enumerate(arcs) if i not in drop]


def resolve_vertices(arcs):
    """Place every vertex from geometry, never from a raw contour sample.

    straight/straight -> intersection of the two fitted lines.
    straight/curve    -> if the two directions agree it is a true tangency, so
                         project the joint onto the straight's line and inherit
                         its direction; if they disagree it is a real corner,
                         so intersect the straight with the curve's own end
                         tangent line and let the curve start off-axis.
    """
    m = len(arcs)
    verts = [None] * m
    tang = [(None, None)] * m       # (tangent leaving vertex i, into vertex i)
    for i in range(m):
        a, b = arcs[i - 1], arcs[i]
        if b.forced_p0 is not None or a.forced_p1 is not None:
            verts[i] = b.forced_p0 if b.forced_p0 is not None else a.forced_p1
            tang[i] = (b.forced_t0, a.forced_t1)
            continue
        if a.straight and b.straight:
            if ang_gap(ang_of(a.d), ang_of(b.d)) > 1.5:
                p = intersect(a.c, a.d, b.c, b.d)
                if p is not None and np.linalg.norm(p - b.pts[0]) < 8.0:
                    verts[i] = p
            if verts[i] is None:
                verts[i] = 0.5 * (a.pts[-1] + b.pts[0])
            continue

        joint = 0.5 * (a.pts[-1] + b.pts[0])
        if b.straight and not a.straight:            # curve -> straight
            cc, cd = end_line(a.pts, False)
            if ang_gap(ang_of(cd), ang_of(b.d)) > CORNER_GAP:
                p = intersect(cc, cd, b.c, b.d)
                verts[i] = p if (p is not None
                                 and np.linalg.norm(p - joint) < 6.0) else joint
                tang[i] = (None, cd)
            else:
                verts[i] = b.c + ((joint - b.c) @ b.d) * b.d
                d = b.d if (b.d @ (b.pts[-1] - b.pts[0])) > 0 else -b.d
                tang[i] = (None, d)
        elif a.straight and not b.straight:          # straight -> curve
            cc, cd = end_line(b.pts, True)
            if ang_gap(ang_of(cd), ang_of(a.d)) > CORNER_GAP:
                p = intersect(a.c, a.d, cc, cd)
                verts[i] = p if (p is not None
                                 and np.linalg.norm(p - joint) < 6.0) else joint
                tang[i] = (cd, None)
            else:
                verts[i] = a.c + ((joint - a.c) @ a.d) * a.d
                d = a.d if (a.d @ (a.pts[-1] - a.pts[0])) > 0 else -a.d
                tang[i] = (d, None)
        else:                                        # curve -> curve
            _, d0 = end_line(b.pts, True)
            verts[i] = joint
            tang[i] = (d0, d0)

    for i in range(m):
        arcs[i].p0 = verts[i]
        arcs[i].p1 = verts[(i + 1) % m]
        arcs[i].t0 = tang[i][0]
        arcs[i].t1 = tang[(i + 1) % m][1]


# ---------------------------------------------------------------- slant snap
def snap_axis(shapes, report):
    """Snap near-level edges to exactly level (and near-plumb to plumb).

    A wordmark's baseline, cap line and crossbars have to be dead parallel;
    the generator left them up to 0.6 deg off, which is a fraction of a pixel
    of drift to fix and a rigorous result to gain.
    """
    n = 0
    worst = 0.0
    for arcs in shapes:
        for a in arcs:
            if not a.straight:
                continue
            ang = ang_of(a.d)
            for target, d_new in ((0.0, np.array([1.0, 0.0])),
                                  (90.0, np.array([0.0, 1.0]))):
                if ang_gap(ang, target) <= AXIS_SNAP_DEG and ang_gap(ang, target) > 0:
                    worst = max(worst, ang_gap(ang, target))
                    a.c = a.core().mean(axis=0)
                    a.d = d_new
                    n += 1
                    break
    report["axis_snapped_edges"] = n
    report["axis_max_correction_deg"] = round(worst, 3)


def snap_slant(shapes, report):
    entries = []
    for si, arcs in enumerate(shapes):
        for ai, a in enumerate(arcs):
            if a.straight and a.chord() >= SLANT_MIN_LEN:
                entries.append((si, ai, ang_of(a.d), a.chord()))
    report["long_edge_angles"] = sorted(
        [[round(a, 2), round(w, 1)] for _, _, a, w in entries],
        key=lambda t: -t[1])
    if not entries:
        return None
    # ignore near-horizontal edges: the italic stems are what we are after
    cands = [(ang, w) for _, _, ang, w in entries if 12.0 < ang < 168.0]
    if not cands:
        return None
    best, best_w = None, -1.0
    for ang, _ in cands:
        w = sum(wt for a2, wt in cands if ang_gap(a2, ang) <= SLANT_BAND_DEG)
        if w > best_w:
            best_w, best = w, ang
    band = [(a, w) for a, w in cands if ang_gap(a, best) <= SLANT_BAND_DEG]
    angs = np.array([a for a, _ in band])
    wts = np.array([w for _, w in band])
    mean = float(np.sum(angs * wts) / np.sum(wts))
    spread = float(angs.max() - angs.min())
    report["slant_members"] = len(band)
    report["slant_member_angles"] = [round(float(a), 3) for a in sorted(angs)]
    report["slant_mean_deg_img"] = round(mean, 3)
    report["slant_deg_from_vertical"] = round(abs(mean - 90.0), 3)
    report["slant_spread_deg"] = round(spread, 3)
    if spread > SLANT_SNAP_DEG:
        report["slant_snapped"] = False
        return mean
    report["slant_snapped"] = True
    r = math.radians(mean)
    d_new = np.array([math.cos(r), math.sin(r)])
    for si, ai, ang, w in entries:
        if ang_gap(ang, mean) <= SLANT_BAND_DEG and 12.0 < ang < 168.0:
            a = shapes[si][ai]
            a.c = a.core().mean(axis=0)
            a.d = d_new
    return mean


# ---------------------------------------------------------------- curve fit
CURVE_TOL = 0.20        # px; max distance from contour to the fitted cubic
CURVE_MAX_DEPTH = 3


def fit_cubic_seg(pts, p0, p1, t_in, t_out):
    """One cubic p0..p1 with fixed unit tangents; least squares on magnitudes."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    if len(pts) < 3 or seg.sum() <= 0:
        return None
    t = np.concatenate([[0.0], np.cumsum(seg)])
    t /= t[-1]
    b0 = (1 - t) ** 3
    b1 = 3 * t * (1 - t) ** 2
    b2 = 3 * t ** 2 * (1 - t)
    b3 = t ** 3
    # B(t) = (b0+b1) p0 + (b2+b3) p1 + a1 b1 t_in - a2 b2 t_out
    rhs = pts - ((b0 + b1)[:, None] * p0 + (b2 + b3)[:, None] * p1)
    a = np.zeros((2 * len(t), 2))
    a[0::2, 0] = b1 * t_in[0]
    a[1::2, 0] = b1 * t_in[1]
    a[0::2, 1] = b2 * (-t_out[0])
    a[1::2, 1] = b2 * (-t_out[1])
    sol, *_ = np.linalg.lstsq(a, rhs.reshape(-1), rcond=None)
    chord = max(np.linalg.norm(p1 - p0), 1e-6)
    a1 = float(np.clip(sol[0], 0.0, 1.6 * chord))
    a2 = float(np.clip(sol[1], 0.0, 1.6 * chord))
    return p0 + a1 * t_in, p1 - a2 * t_out


def bez_pts(p0, c1, c2, p1, n=240):
    t = np.linspace(0, 1, n)[:, None]
    return ((1 - t) ** 3 * p0 + 3 * t * (1 - t) ** 2 * c1
            + 3 * t ** 2 * (1 - t) * c2 + t ** 3 * p1)


def cubic_error(pts, p0, c1, c2, p1):
    """Max contour-to-cubic distance, ignoring a sliver at each end.

    The endpoints are placed by construction (projected onto the neighbouring
    ideal line), so residual right at a joint is not a fit failure and must not
    drive subdivision."""
    b = bez_pts(p0, c1, c2, p1)
    d = np.linalg.norm(pts[:, None, :] - b[None, :, :], axis=2).min(axis=1)
    t = max(2, int(len(d) * 0.04))
    core = d[t:-t] if len(d) > 2 * t + 2 else d
    return float(core.max()), int(np.argmax(core)) + (t if len(d) > 2 * t + 2 else 0)


SPLIT_TURN = 45.0       # deg of turning covered by one cubic before splitting


def local_dirs(pts, k=8):
    """Smoothed tangent direction at every sample, via a +-k chord."""
    n = len(pts)
    i = np.arange(n)
    lo = np.clip(i - k, 0, n - 1)
    hi = np.clip(i + k, 0, n - 1)
    return pts[hi] - pts[lo]


def turn_splits(pts, max_turn):
    """Indices that cut the arc into pieces of at most max_turn degrees.

    Splitting on turning (not on max error) is what makes this converge: a
    cubic tracks a circular arc to well under a hundredth of a pixel up to
    about 45 degrees, so bounded turn means bounded error from the start.
    """
    if len(pts) < 24:
        return []
    d = local_dirs(pts)
    ang = np.unwrap(np.arctan2(d[:, 1], d[:, 0]))
    total = ang[-1] - ang[0]
    nseg = max(1, int(math.ceil(abs(math.degrees(total)) / max_turn)))
    if nseg < 2:
        return []
    out = []
    for j in range(1, nseg):
        t = ang[0] + total * (j / nseg)
        k = int(np.argmax(ang >= t)) if total >= 0 else int(np.argmax(ang <= t))
        out.append(int(np.clip(k, 6, len(pts) - 7)))
    return sorted(set(out))


def _leaf_chain(pts, p0, p1, t_in, t_out, depth=0):
    fit = fit_cubic_seg(pts, p0, p1, t_in, t_out)
    if fit is None:
        return [(p0 + (p1 - p0) / 3, p0 + 2 * (p1 - p0) / 3, p1)]
    c1, c2 = fit
    err, _ = cubic_error(pts, p0, c1, c2, p1)
    if err <= CURVE_TOL or depth >= CURVE_MAX_DEPTH or len(pts) < 16:
        return [(c1, c2, p1)]
    k = len(pts) // 2
    pm = pts[k]
    d = local_dirs(pts)[k]
    tm = d / max(np.linalg.norm(d), 1e-9)
    return (_leaf_chain(pts[:k + 1], p0, pm, t_in, tm, depth + 1)
            + _leaf_chain(pts[k:], pm, p1, tm, t_out, depth + 1))


def curve_chain(pts, p0, p1, t_in, t_out):
    """List of (c1, c2, end) cubics approximating pts within CURVE_TOL."""
    cuts = turn_splits(pts, SPLIT_TURN)
    if not cuts:
        return _leaf_chain(pts, p0, p1, t_in, t_out)
    d = local_dirs(pts)
    bounds = [0] + cuts + [len(pts) - 1]
    out = []
    prev_p, prev_t = p0, t_in
    for a, b in zip(bounds[:-1], bounds[1:]):
        last = b == len(pts) - 1
        end_p = p1 if last else pts[b]
        if last:
            end_t = t_out
        else:
            v = d[b]
            end_t = v / max(np.linalg.norm(v), 1e-9)
        out += _leaf_chain(pts[a:b + 1], prev_p, end_p, prev_t, end_t)
        prev_p, prev_t = end_p, end_t
    return out


def tangents_for(arcs, i):
    """Unit tangents entering / leaving curved arc i, as decided at the joints."""
    a = arcs[i]
    t_in, t_out = a.t0, a.t1
    if t_in is None:
        t_in = end_line(a.pts, True)[1]
    if t_out is None:
        t_out = end_line(a.pts, False)[1]
    t_in = np.asarray(t_in, float)
    t_out = np.asarray(t_out, float)
    t_in = t_in / max(np.linalg.norm(t_in), 1e-9)
    t_out = t_out / max(np.linalg.norm(t_out), 1e-9)
    return t_in, t_out


# ---------------------------------------------------------------- emit
def fmt(v):
    s = f"{round(float(v), DEC):.{DEC}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    if s.startswith("0.") and len(s) > 2:
        s = s[1:]
    elif s.startswith("-0.") and len(s) > 3:
        s = "-" + s[2:]
    return s


def emit_subpath(arcs, xf, stats):
    p = xf(arcs[0].p0)
    out = [f"M{fmt(p[0])} {fmt(p[1])}"]
    for i, a in enumerate(arcs):
        if a.straight:
            q = xf(a.p1)
            out.append(f"L{fmt(q[0])} {fmt(q[1])}")
            continue
        t_in, t_out = tangents_for(arcs, i)
        chain = curve_chain(a.pts, a.p0, a.p1, t_in, t_out)
        stats["cubics"] += len(chain)
        for c1, c2, end in chain:
            c1, c2, end = xf(c1), xf(c2), xf(end)
            out.append(f"C{fmt(c1[0])} {fmt(c1[1])} {fmt(c2[0])} {fmt(c2[1])}"
                       f" {fmt(end[0])} {fmt(end[1])}")
    out.append("Z")
    return "".join(out)


# ---------------------------------------------------------------- debug view
def debug_overlay(shapes, path="debug_overlay.png", scale=4):
    from PIL import ImageDraw
    base = Image.open(SRC_GRAY_4X).convert("RGB")
    im = base.point(lambda v: int(v * 0.45))
    dr = ImageDraw.Draw(im)
    for arcs in shapes:
        for i, a in enumerate(arcs):
            if a.straight:
                dr.line([tuple(a.p0 * scale), tuple(a.p1 * scale)],
                        fill=(60, 235, 90), width=2)
            else:
                t_in, t_out = tangents_for(arcs, i)
                prev = a.p0
                for c1, c2, end in curve_chain(a.pts, a.p0, a.p1, t_in, t_out):
                    b = bez_pts(prev, c1, c2, end, 60) * scale
                    dr.line([tuple(q) for q in b], fill=(255, 60, 220), width=2)
                    prev = end
            x, y = a.p0 * scale
            dr.ellipse([x - 5, y - 5, x + 5, y + 5],
                       outline=(255, 210, 40), width=2)
    im.save(path)


def prepare():
    """Crop to the ink box and upscale 4x with a plain bilinear filter.

    Bilinear, not Lanczos: on a hard edge the negative lobes of a windowed-sinc
    ring, and after thresholding that ringing becomes a wavy contour. Bilinear
    just interpolates the anti-aliasing ramp, which is exactly the surface
    marching squares is about to walk anyway, so the upscale adds sample
    density without inventing geometry.
    """
    if os.path.exists(SRC_GRAY_4X):
        return
    w, h, x, y = CROP
    subprocess.run(["magick", SOURCE_PNG, "-colorspace", "gray",
                    "-crop", f"{w}x{h}+{x}+{y}", "+repage", "crop_gray.png"],
                   check=True)
    subprocess.run(["magick", "crop_gray.png", "-filter", "Triangle",
                    "-resize", "400%", SRC_GRAY_4X], check=True)


def main():
    prepare()
    report = {}
    a = np.asarray(Image.open(SRC_GRAY_4X).convert("L")).astype(float) / 255.0
    a = np.pad(a, 2, mode="constant", constant_values=0.0)
    contours = []
    for c in measure.find_contours(a, 0.5):
        pts = np.column_stack([(c[:, 1] - 2) / UPSCALE, (c[:, 0] - 2) / UPSCALE])
        if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
            pts = pts[:-1]
        if abs(signed_area(pts)) < MIN_AREA:
            continue
        contours.append(pts)
    contours.sort(key=lambda p: -abs(signed_area(p)))
    print(f"kept contours: {len(contours)}")

    shapes = []
    for ci, pts in enumerate(contours):
        verts = rdp_closed(pts, RDP_EPS)
        arcs = build_arcs(pts, verts)
        for x in arcs:
            x.classify()
        n_rdp = len(arcs)
        arcs = merge_collinear(arcs, pts)
        arcs = drop_slivers(arcs, pts)
        arcs = detect_curve_runs(arcs, pts)
        arcs = merge_collinear(arcs, pts)
        arcs = detect_bows(arcs, pts)
        arcs = close_wedge_tips(arcs, pts)
        arcs = snap_curve_bounds(arcs, pts)
        nc = sum(1 for x in arcs if not x.straight)
        print(f"  contour {ci}: rdp={n_rdp} -> edges={len(arcs)} "
              f"(line={len(arcs)-nc}, curve={nc}) area={signed_area(pts):.1f}")
        shapes.append(arcs)

    snap_axis(shapes, report)
    snap_slant(shapes, report)
    for arcs in shapes:
        resolve_vertices(arcs)

    print("\n--- arc inventory (source px) ---")
    for si, arcs in enumerate(shapes):
        for i, x in enumerate(arcs):
            kind = "line " if x.straight else "CURVE"
            print(f"  s{si} #{i:02d} {kind} len={x.chord():7.2f} "
                  f"ang={ang_of(x.d):7.2f} dev={x.dev:5.2f} "
                  f"p0=({x.p0[0]:7.2f},{x.p0[1]:7.2f})")

    allp = np.array([a_.p0 for arcs in shapes for a_ in arcs])
    x0, y0 = allp[:, 0].min(), allp[:, 1].min()
    x1, y1 = allp[:, 0].max(), allp[:, 1].max()
    iw, ih = x1 - x0, y1 - y0
    m = MARGIN_FRAC * iw
    s = VB_H / (ih + 2 * m)
    vb_w = (iw + 2 * m) * s

    def xf(p):
        return np.array([(p[0] - x0 + m) * s, (p[1] - y0 + m) * s])

    debug_overlay(shapes)
    stats = {"cubics": 0}
    d = "".join(emit_subpath(arcs, xf, stats) for arcs in shapes)
    vb = f"0 0 {fmt(vb_w)} {fmt(VB_H)}"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" '
        f'fill="currentColor" role="img" aria-label="LSA">'
        f'<title>LSA</title><path fill-rule="evenodd" d="{d}"/></svg>\n'
    )
    with open("master_raw.svg", "w") as f:
        f.write(svg)

    report.update({
        "viewBox": f"0 0 {vb_w:.2f} {VB_H:.2f}",
        "ink_src_px": [round(float(iw), 2), round(float(ih), 2)],
        "vb_scale": round(float(s), 6),
        "vb_offset": [round(float(x0 - m), 3), round(float(y0 - m), 3)],
        "edges_per_shape": [len(x) for x in shapes],
        "curves_per_shape": [sum(1 for y in x if not y.straight) for x in shapes],
        "max_line_dev_px": round(max(y.dev for x in shapes for y in x), 4),
        "cmd_L": d.count("L"),
        "cmd_C": d.count("C"),
        "subpaths": d.count("M"),
        "d_chars": len(d),
    })
    with open("report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("\n--- report ---")
    for k, v in report.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
