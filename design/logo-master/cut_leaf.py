"""Cut the bottom leaf out of the chosen hero (day and night), heal the sky where it was, and trace it.

Run from design/mocks:  env -u PYTHONPATH ../logo-master/.venv/bin/python ../logo-master/cut_leaf.py

Writes, into assets/:
  hero-{day,night}-noleaf.png   the scene with the leaf healed away (stem included this time)
  leaf-{day,night}.png          RGBA cutout of the leaf, feathered 3 px, in a padded box
  leaf-cut.json                 per theme: bbox in the 1920 x 1072 image, the PCA axis (angle, centroid, extent,
                                all relative to the padded box), a potrace outline of the SAME silhouette in
                                padded-box pixel units (so an <svg viewBox="0 0 bw bh"> over the cutout matches
                                it within a pixel), two sampled fill colours (base near the stem, tip);
                                plus the logo leaf's axis under "vec".
The stem: the day stem is darker than the lamina and the night stem lighter, so the first cut (Sep 10 16:39)
dropped it and left a dash in the healed sky. Now every non-sky pixel within 16 px of the lamina that connects
to it is part of the leaf.
"""
import json, math, re, subprocess, sys, os
import numpy as np
from PIL import Image, ImageFilter
from skimage import measure, morphology
from skimage.restoration import inpaint

SCRATCH = "/private/tmp/claude-501/-Users-alkautsar-Documents-s0nderlabs-kint/5b4c89b5-7f08-4133-823b-e4a1e2c7b007/scratchpad"
rng = np.random.default_rng(11)


def axis(mask):
    ys, xs = np.where(mask)
    x = xs.astype(float); y = ys.astype(float); cx, cy = x.mean(), y.mean()
    cov = np.cov(np.vstack([x - cx, y - cy])); w, v = np.linalg.eigh(cov); d = v[:, np.argmax(w)]
    proj = (x - cx) * d[0] + (y - cy) * d[1]; lo, hi = proj.min(), proj.max(); mid = (lo + hi) / 2
    # the tip end carries more mass than the stem end: the centroid sits on the tip side of the extent's midpoint
    if 0 < mid:
        d = -d; proj = -proj; lo, hi = -hi, -lo
    ang = math.degrees(math.atan2(d[1], d[0]))  # screen coords, y down: 0 = east, negative = up
    return {"angle": round(ang, 2), "cx": float(cx), "cy": float(cy), "ext": float(hi - lo), "lo": float(lo), "hi": float(hi), "d": (float(d[0]), float(d[1]))}


def potrace_path(mask, scale=4):
    """Trace a binary mask with potrace at `scale` x and return an absolute-coordinate SVG path in mask pixel units."""
    H, W = mask.shape
    big = np.asarray(Image.fromarray((mask * 255).astype("uint8")).resize((W * scale, H * scale), Image.BILINEAR)) > 127
    pbm = os.path.join(SCRATCH, "leaf-trace.pbm"); svg = os.path.join(SCRATCH, "leaf-trace.svg")
    Image.fromarray(~big).save(pbm)  # potrace traces BLACK; PIL mode 1 writes True as white
    subprocess.run(["potrace", pbm, "-s", "-o", svg, "-t", "12", "-a", "1.15", "-O", "0.3", "-u", "10", "-r", "72", "--flat"], check=True)
    s = open(svg).read()
    tr = re.search(r'transform="translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+),([-\d.]+)\)"', s)
    tx, ty, sx, sy = map(float, tr.groups())
    d = re.search(r'<path[^>]*d="([^"]+)"', s, re.S).group(1)
    toks = re.findall(r"[MmCcLlZz]|-?\d*\.?\d+", d)
    out = []; i = 0; cur = (0.0, 0.0); start = cur

    def P(x, y):  # potrace units -> mask px: apply translate/scale, then undo the upscale
        return ((x * sx + tx) / scale, (y * sy + ty) / scale)

    def nums(n):
        nonlocal i
        v = [float(toks[i + k]) for k in range(n)]; i += n; return v

    while i < len(toks):
        t = toks[i]; i += 1
        if t == "M":
            x, y = nums(2); cur = (x, y); start = cur; out.append("M%.2f %.2f" % P(*cur))
        elif t == "m":
            x, y = nums(2); cur = (cur[0] + x, cur[1] + y); start = cur; out.append("M%.2f %.2f" % P(*cur))
        elif t in "Cc":
            while i < len(toks) and re.match(r"-?\d", toks[i]):
                x1, y1, x2, y2, x, y = nums(6)
                if t == "c":
                    x1 += cur[0]; y1 += cur[1]; x2 += cur[0]; y2 += cur[1]; x += cur[0]; y += cur[1]
                out.append("C%.2f %.2f %.2f %.2f %.2f %.2f" % (P(x1, y1) + P(x2, y2) + P(x, y))); cur = (x, y)
        elif t in "Ll":
            while i < len(toks) and re.match(r"-?\d", toks[i]):
                x, y = nums(2)
                if t == "l":
                    x += cur[0]; y += cur[1]
                out.append("L%.2f %.2f" % P(x, y)); cur = (x, y)
        elif t in "Zz":
            out.append("Z"); cur = start
    return "".join(out)


def cut(src, out_scene, out_leaf, target, night=False):
    im = Image.open(src).convert("RGB"); a = np.asarray(im).astype(float); H, W = a.shape[:2]
    r, g, b = a[..., 0], a[..., 1], a[..., 2]; lum = (r + g + b) / 3
    if not night:
        sky = (r > 200) & (g > 190) & (b > 170); blob = (~sky) & (lum >= 110) & (r > 120) & (r - b > 25)
    else:
        sky = lum < 95; blob = (lum > 140) & (np.abs(r - b) < 60)
    lab = measure.label(morphology.opening(blob, morphology.disk(1)))
    props = [p for p in measure.regionprops(lab) if 300 < p.area < 9000]
    tx, ty = target
    best = min(props, key=lambda p: (abs((p.bbox[1] + p.bbox[3]) / 2 - tx) + abs((p.bbox[0] + p.bbox[2]) / 2 - ty)))
    core = lab == best.label
    core = morphology.closing(core, morphology.disk(2)); core = morphology.remove_small_holes(core, max_size=400)
    # the stem and any torn lobe: non-sky pixels near the lamina that connect to it
    near = morphology.dilation(core, morphology.disk(int(os.environ.get("KINT_STEM", "16"))))
    cand = (~sky) & near
    cand = morphology.closing(cand, morphology.disk(1))
    cl = measure.label(cand | core)
    keep = np.zeros_like(core)
    for p in measure.regionprops(cl):
        m = cl == p.label
        if (m & core).any():
            keep |= m
    leafmask = morphology.remove_small_holes(morphology.closing(keep, morphology.disk(1)), max_size=200)
    # the cutout: feathered alpha
    a1 = morphology.dilation(leafmask, morphology.disk(3)).astype(float)
    alpha = np.asarray(Image.fromarray((a1 * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(1.6))).astype(float) / 255
    alpha = np.where(leafmask, 1.0, alpha)
    ys, xs = np.where(leafmask); y0, x0, y1, x1 = ys.min(), xs.min(), ys.max() + 1, xs.max() + 1
    pad = 8; X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
    Image.fromarray(np.dstack([a[Y0:Y1, X0:X1], alpha[Y0:Y1, X0:X1] * 255]).astype("uint8"), "RGBA").save(out_leaf)
    # the heal: a smooth biharmonic fill on a crop, plus the sky's own high-frequency texture from the ring
    hole = morphology.dilation(leafmask, morphology.disk(5))
    hy, hx = np.where(hole); m = 48
    cy0, cx0, cy1, cx1 = max(0, hy.min() - m), max(0, hx.min() - m), min(H, hy.max() + m), min(W, hx.max() + m)
    crop = a[cy0:cy1, cx0:cx1] / 255.0; hcrop = hole[cy0:cy1, cx0:cx1]
    smooth = inpaint.inpaint_biharmonic(crop, hcrop, channel_axis=-1) * 255.0
    # the paper's own grain, taken as one coherent patch of sky next door (per-pixel noise reads as speckle)
    blur = np.asarray(im.filter(ImageFilter.GaussianBlur(3.0))).astype(float)
    resid_full = a - blur
    hy_, hx_ = np.where(hole); off = None
    for dx, dy in ((-120, 0), (0, -120), (120, 0), (0, 120), (-90, -90), (90, -90), (-90, 90), (90, 90)):
        yy, xx = hy_ + dy, hx_ + dx
        if yy.min() >= 0 and xx.min() >= 0 and yy.max() < H and xx.max() < W and sky[yy, xx].all():
            off = (dx, dy); break
    if off is None:
        raise SystemExit("no clean sky patch next to the hole")
    resid = resid_full[hy_ + off[1], hx_ + off[0]]
    healed = a.copy()
    sm_full = np.zeros_like(a); sm_full[cy0:cy1, cx0:cx1] = smooth
    healed[hy_, hx_] = np.clip(sm_full[hy_, hx_] + resid, 0, 255)
    print('heal patch offset', off)
    # soften the seam only
    hb = np.asarray(Image.fromarray(healed.astype("uint8")).filter(ImageFilter.GaussianBlur(0.9))).astype(float)
    seam = morphology.dilation(hole, morphology.disk(2)) & ~morphology.erosion(hole, morphology.disk(2)); healed[seam] = hb[seam]
    Image.fromarray(healed.astype("uint8")).save(out_scene)
    # geometry, in the padded box
    box = leafmask[Y0:Y1, X0:X1]; bw, bh = X1 - X0, Y1 - Y0
    ax = axis(box)
    # two fill colours for the vector: median lamina colour at the stem third and at the tip third along the axis
    yy, xx = np.where(box); proj = (xx - ax["cx"]) * ax["d"][0] + (yy - ax["cy"]) * ax["d"][1]
    px = a[Y0:Y1, X0:X1][box]
    lam = px[:, 0] >= 110 if not night else px.mean(axis=1) > 120  # lamina only, not the dark (day) rib
    lo, hi = ax["lo"], ax["hi"]
    base = np.median(px[lam & (proj < lo + (hi - lo) * 0.35)], axis=0)
    tip = np.median(px[lam & (proj > lo + (hi - lo) * 0.65)], axis=0)
    hexc = lambda c: "#%02X%02X%02X" % tuple(int(round(v)) for v in c)
    return {
        "bbox": [int(X0), int(Y0), int(X1), int(Y1)], "image": [W, H],
        "angle": ax["angle"], "cx": round(ax["cx"] / bw, 4), "cy": round(ax["cy"] / bh, 4), "ext": round(ax["ext"] / bw, 4),
        "path": potrace_path(box), "base": hexc(base), "tip": hexc(tip),
    }, box


if __name__ == "__main__":
    A = "assets"; T = (907, 553)
    day, dbox = cut(f"{A}/poster-hero-soft.png", f"{A}/hero-day-noleaf.png", f"{A}/leaf-day.png", T)
    night, nbox = cut(f"{A}/poster-hero-soft-night.png", f"{A}/hero-night-noleaf.png", f"{A}/leaf-night.png", T, night=True)
    info = {"day": day, "night": night}
    # the logo leaf's axis, from a 1000 px raster of kint-leaf.svg
    vp = os.path.join(SCRATCH, "vecleaf.png")
    subprocess.run(["rsvg-convert", "-w", "1000", "-h", "1000", f"{A}/kint-leaf.svg", "-o", vp], check=True)
    vm = np.asarray(Image.open(vp).convert("RGBA"))[..., 3] > 127
    vx = axis(vm); info["vec"] = {"angle": vx["angle"], "cx": round(vx["cx"] / 1000, 4), "cy": round(vx["cy"] / 1000, 4), "ext": round(vx["ext"] / 1000, 4)}
    json.dump(info, open(f"{A}/leaf-cut.json", "w"), indent=1)
    # proof: rasterise each traced path at 8x over the mask and report IoU
    for k, box in (("day", dbox), ("night", nbox)):
        bh, bw = box.shape; S = 8
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {bw} {bh}" width="{bw*S}" height="{bh*S}"><path d="{info[k]["path"]}" fill="#000"/></svg>'
        sp = os.path.join(SCRATCH, f"trace-{k}.svg"); pp = os.path.join(SCRATCH, f"trace-{k}.png")
        open(sp, "w").write(svg); subprocess.run(["rsvg-convert", sp, "-o", pp], check=True)
        tr = np.asarray(Image.open(pp).convert("RGBA"))[..., 3] > 127
        ref = np.asarray(Image.fromarray(box).resize((bw * S, bh * S), Image.NEAREST)) > 0
        iou = (tr & ref).sum() / (tr | ref).sum()
        print(k, "box", bw, "x", bh, "mask px", int(box.sum()), "trace IoU %.3f" % iou, "base", info[k]["base"], "tip", info[k]["tip"], "angle", info[k]["angle"], "path chars", len(info[k]["path"]))
    print("vec", info["vec"])
