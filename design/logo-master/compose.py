"""Compose the master: the word from the lsa vectoriser (crisp corners, axis-snapped), the leaf and
the dot from potrace (smooth curves), both mapped into the same shared viewBox measured off the render."""
import re, json, subprocess
rep = json.load(open("report.json")); s = rep["vb_scale"]; ox, oy = rep["vb_offset"]; vb = rep["viewBox"]
lock = open("lockup_lsa.svg").read()
ink_d = re.search(r'<path fill="currentColor" fill-rule="evenodd" d="([^"]+)"', lock).group(1)
import os
INK_MODE = os.environ.get("INK_MODE", "lsa")
if INK_MODE == "potrace":
    pi = open("ink_potrace.svg").read(); pitr = re.search(r'transform="([^"]+)"', pi).group(1)
    pid = " ".join(re.findall(r'<path[^>]*d="([^"]+)"', pi)); pid = re.sub(r"\s+", " ", pid).strip()
pt = open("blue_potrace.svg").read()
ptr = re.search(r'transform="([^"]+)"', pt).group(1)
pd = " ".join(re.findall(r'<path[^>]*d="([^"]+)"', pt)); pd = re.sub(r"\s+", " ", pd).strip()
outer = f"translate({-ox*s:.4f},{-oy*s:.4f}) scale({s/4:.6f})"
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img" aria-label="kint"><title>kint</title>'
       + (f'<path fill="currentColor" fill-rule="evenodd" d="{ink_d}"/>' if INK_MODE != "potrace" else f'<g fill="currentColor" transform="{outer}"><g transform="{pitr}"><path d="{pid}"/></g></g>')
       + f'<g fill="var(--kint-accent,#0A44F5)" transform="{outer}"><g transform="{ptr}"><path d="{pd}"/></g></g></svg>\n')
open("kint-lockup.svg", "w").write(svg)
# the leaf alone: potrace's largest subpath (+ its hole) in a square viewBox; the dot is the small square at the foot
subs = re.findall(r'<path[^>]*d="([^"]+)"', pt)
subpaths = re.split(r"(?=M)", pd); subpaths = [x for x in subpaths if x.strip()]
def bbox(d):
    nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", d)]
    xs, ys = nums[0::2], nums[1::2]   # potrace --flat uses absolute coords for M and relative for others; bbox from M points only is enough to sort
    return xs[0], ys[0]
# potrace emits one <path> per outer contour with its holes inside; find the largest path by length
paths = sorted(subs, key=len, reverse=True); leaf_d = re.sub(r"\s+", " ", paths[0]).strip()
# bbox of the leaf in potrace units: rasterise via rsvg to measure is overkill; take the numbers after transform
m = re.search(r'viewBox="([^"]+)"', pt).group(1); W4, H4 = [float(v) for v in m.split()[2:]]
leaf_svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W4:.0f} {H4:.0f}" role="img" aria-label="kint"><title>kint</title>'
            f'<g fill="currentColor" transform="{ptr}"><path d="{leaf_d}"/></g></svg>\n')
open("kint-leaf-raw.svg", "w").write(leaf_svg)
print("composed: ink chars", len(ink_d), "leaf chars", len(pd), "paths", len(subs))
