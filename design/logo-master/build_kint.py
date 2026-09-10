"""kint lockup: the GPT Image 2.5 render -> one geometric master SVG, 1:1.

Reuses larisamaarnold's vectoriser (lsa_build_master.py, copied verbatim) as a library:
the same subpixel isocontour, RDP, TLS line fits, curve runs, tangency snapping, vertices as
line intersections, axis snapping and cubic emission. Two layers are traced from two soft
colour masks of the same render (ink = the word, cobalt = the leaf and the square dot; the
midrib is the hole in the leaf, cut by fill-rule evenodd), and both are emitted into ONE
shared viewBox so the lockup's proportions are the render's, not re-set.

Outputs: kint-lockup.svg (two paths: currentColor word, var(--kint-accent) leaf+dot),
kint-leaf.svg (the leaf alone, square viewBox, for favicon and app icon), report.json.
Run: .venv/bin/python build_kint.py   then   .venv/bin/python prove_kint.py
"""
import json, numpy as np
from PIL import Image
from skimage import measure
import lsa_build_master as B

B.SLANT_BAND_DEG = 0.0            # the mark is upright: no italic-slant snapping
LAYERS = [("ink", "gray4x_ink.png"), ("blue", "gray4x_blue.png")]
UP = 4.0

import os
BLUE_TUNE = {"RDP_EPS": float(os.environ.get("K_RDP", B.RDP_EPS)), "CURVE_TOTAL_MIN": float(os.environ.get("K_CTM", B.CURVE_TOTAL_MIN)), "CURVE_SEG_MAX": float(os.environ.get("K_CSM", B.CURVE_SEG_MAX)), "STRAIGHT_TOL": float(os.environ.get("K_STOL", B.STRAIGHT_TOL))}
INK_TUNE = {"RDP_EPS": B.RDP_EPS, "CURVE_TOTAL_MIN": B.CURVE_TOTAL_MIN, "CURVE_SEG_MAX": B.CURVE_SEG_MAX, "STRAIGHT_TOL": B.STRAIGHT_TOL}
def trace(gray4x, tune=None):
    for k, v in (tune or {}).items(): setattr(B, k, v)
    a = np.asarray(Image.open(gray4x).convert("L")).astype(float) / 255.0
    a = np.pad(a, 2, mode="constant", constant_values=0.0)
    contours = []
    for c in measure.find_contours(a, 0.5):
        pts = np.column_stack([(c[:, 1] - 2) / UP, (c[:, 0] - 2) / UP])
        if len(pts) > 1 and np.allclose(pts[0], pts[-1]): pts = pts[:-1]
        if abs(B.signed_area(pts)) < B.MIN_AREA: continue
        contours.append(pts)
    contours.sort(key=lambda p: -abs(B.signed_area(p)))
    shapes = []
    for pts in contours:
        verts = B.rdp_closed(pts, B.RDP_EPS)
        arcs = B.build_arcs(pts, verts)
        for x in arcs: x.classify()
        arcs = B.merge_collinear(arcs, pts); arcs = B.drop_slivers(arcs, pts)
        arcs = B.detect_curve_runs(arcs, pts); arcs = B.merge_collinear(arcs, pts)
        arcs = B.detect_bows(arcs, pts); arcs = B.close_wedge_tips(arcs, pts)
        arcs = B.snap_curve_bounds(arcs, pts)
        shapes.append(arcs)
    rep = {}
    B.snap_axis(shapes, rep)
    for arcs in shapes: B.resolve_vertices(arcs)
    return shapes, rep

def main():
    traced = {name: trace(f, BLUE_TUNE if name == "blue" else INK_TUNE) for name, f in LAYERS}
    for name, (shapes, _) in traced.items(): print(name, "contours", len(shapes), "arcs", [len(x) for x in shapes])
    allp = np.array([a_.p0 for shapes, _ in traced.values() for arcs in shapes for a_ in arcs])
    x0, y0 = allp[:, 0].min(), allp[:, 1].min(); x1, y1 = allp[:, 0].max(), allp[:, 1].max()
    iw, ih = x1 - x0, y1 - y0
    m = B.MARGIN_FRAC * iw
    s = B.VB_H / (ih + 2 * m)
    vb_w = (iw + 2 * m) * s
    def xf(p): return np.array([(p[0] - x0 + m) * s, (p[1] - y0 + m) * s])
    stats = {"cubics": 0}
    d = {name: "".join(B.emit_subpath(arcs, xf, stats) for arcs in shapes) for name, (shapes, _) in traced.items()}
    vb = f"0 0 {B.fmt(vb_w)} {B.fmt(B.VB_H)}"
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img" aria-label="kint">'
           f'<title>kint</title>'
           f'<path fill="currentColor" fill-rule="evenodd" d="{d["ink"]}"/>'
           f'<path fill="var(--kint-accent,#0A44F5)" fill-rule="evenodd" d="{d["blue"]}"/></svg>\n')
    open("kint-lockup.svg", "w").write(svg)
    # the leaf alone: the largest blue contour, its own square viewBox
    shapes_b, _ = traced["blue"]
    leaf_shapes = [sh for sh in shapes_b if abs(B.signed_area(np.array([a_.p0 for a_ in sh]))) > 400 or True]
    lp = np.array([a_.p0 for arcs in shapes_b for a_ in arcs])
    # the dot is the small square well below the leaf: keep contours whose top is above the leaf's bottom
    leaf_only = []
    ys = [np.array([a_.p0 for a_ in arcs])[:, 1] for arcs in shapes_b]
    leaf_bottom = max(y.max() for y in ys if (y.max() - y.min()) > 100)
    for arcs, y in zip(shapes_b, ys):
        if y.min() < leaf_bottom - 5: leaf_only.append(arcs)
    lp = np.array([a_.p0 for arcs in leaf_only for a_ in arcs])
    lx0, ly0, lx1, ly1 = lp[:, 0].min(), lp[:, 1].min(), lp[:, 0].max(), lp[:, 1].max()
    lw, lh = lx1 - lx0, ly1 - ly0; side = max(lw, lh) * 1.08; ls = 100.0 / side
    ox = (side - lw) / 2; oy = (side - lh) / 2
    def lxf(p): return np.array([(p[0] - lx0 + ox) * ls, (p[1] - ly0 + oy) * ls])
    dl = "".join(B.emit_subpath(arcs, lxf, {"cubics": 0}) for arcs in leaf_only)
    open("kint-leaf.svg", "w").write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="kint"><title>kint</title><path fill="currentColor" fill-rule="evenodd" d="{dl}"/></svg>\n')
    report = {"viewBox": vb, "ink_src_px": [round(float(iw), 2), round(float(ih), 2)], "vb_scale": round(float(s), 6),
              "vb_offset": [round(float(x0 - m), 3), round(float(y0 - m), 3)],
              "layers": {name: {"subpaths": d[name].count("M"), "L": d[name].count("L"), "C": d[name].count("C"), "chars": len(d[name]),
                                "edges_per_shape": [len(x) for x in shapes], "max_line_dev_px": round(max([y.dev for x in shapes for y in x] or [0]), 4),
                                "axis_snapped": rep.get("axis_snapped_edges"), "axis_max_correction_deg": rep.get("axis_max_correction_deg")}
                         for name, (shapes, rep) in traced.items()},
              "leaf_svg": {"contours": len(leaf_only), "chars": len(dl)}}
    json.dump(report, open("report.json", "w"), indent=2)
    print(json.dumps(report, indent=1))
main()
