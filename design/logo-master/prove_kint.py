"""Fidelity proof for kint-lockup.svg against the render, the lsa way: rasterise the SVG at the
source's exact scale and offset (4x, then box-downsample so the fractional offset survives),
composite on the render's paper colour, and compare. Also a per-layer mask IoU, a proof sheet
(source | vector) and a favicon strip of the leaf at 512 to 16 px."""
import json, subprocess, numpy as np
from PIL import Image
c = json.load(open("colours.json")); rep = json.load(open("report.json"))
paper = tuple(int(round(v)) for v in c["paper"]); ink = "#%02x%02x%02x" % tuple(int(round(v)) for v in c["ink"]); cob = "#%02x%02x%02x" % tuple(int(round(v)) for v in c["cobalt"])
box = c["box"]; s = rep["vb_scale"]; ox, oy = rep["vb_offset"]
vbw, vbh = [float(x) for x in rep["viewBox"].split()[2:]]
SRC = "/Users/alkautsar/Documents/s0nderlabs/kint/design/mocks/assets/logo-mark.png"; src = Image.open(SRC).convert("RGB")
# 1. colour the master for the proof
svg = open("kint-lockup.svg").read().replace('fill="currentColor"', f'fill="{ink}"').replace('fill="var(--kint-accent,#0A44F5)"', f'fill="{cob}"')
open("proof_colour.svg", "w").write(svg)
Wpx = vbw / s; Hpx = vbh / s                     # the master's size in source px
UP = 4
subprocess.run(["rsvg-convert", "-w", str(int(round(Wpx * UP))), "-h", str(int(round(Hpx * UP))), "proof_colour.svg", "-o", "proof_vec4x.png"], check=True)
vec = Image.open("proof_vec4x.png").convert("RGBA")
canvas = Image.new("RGBA", (1024 * UP, 1024 * UP), paper + (255,))
px = int(round((box[0] + ox) * UP)); py = int(round((box[1] + oy) * UP))
canvas.alpha_composite(vec, (px, py))
aligned = canvas.convert("RGB").resize((1024, 1024), Image.BOX); aligned.save("aligned_1024.png")
# 2. pixel compare, two tolerances (the render carries paper grain)
def ae(fuzz):
    r = subprocess.run(["magick", "compare", "-metric", "AE", "-fuzz", fuzz, "aligned_1024.png", SRC, "null:"], capture_output=True, text=True)
    return int(float(r.stderr.strip().split()[0]))
res = {"AE_fuzz2pct": ae("2%"), "AE_fuzz8pct": ae("8%"), "pixels": 1024 * 1024}
# 3. per-layer IoU on hard masks
def masks(im):
    a = np.asarray(im).astype(float); r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (r < 90) & (g < 90) & (b < 90), (b > 150) & (r < 90) & (g < 110)
si, sb = masks(src); ai, ab = masks(aligned)
res["iou_ink"] = round(float((si & ai).sum() / (si | ai).sum()), 4); res["iou_blue"] = round(float((sb & ab).sum() / (sb | ab).sum()), 4)
res["xor_ink_px"] = int((si ^ ai).sum()); res["xor_blue_px"] = int((sb ^ ab).sum()); res["src_ink_px"] = int(si.sum()); res["src_blue_px"] = int(sb.sum())
# 4. proof sheet: source crop | vector crop at 3x, and a diff
cs = src.crop(tuple(box)).resize(((box[2] - box[0]) * 3, (box[3] - box[1]) * 3), Image.LANCZOS)
cv = aligned.crop(tuple(box)).resize(cs.size, Image.LANCZOS)
diff = Image.fromarray((((si ^ ai) | (sb ^ ab))[box[1]:box[3], box[0]:box[2]] * 255).astype("uint8")).resize(cs.size, Image.NEAREST).convert("RGB")
sheet = Image.new("RGB", (cs.width * 3 + 80, cs.height + 60), paper)
for i, im in enumerate([cs, cv, diff]): sheet.paste(im, (20 + i * (cs.width + 20), 40))
sheet.save("proof-sheet.png")
# 5. favicon strip of the leaf
strip = Image.new("RGB", (1100, 560), paper); x = 20
leaf = open("kint-leaf.svg").read().replace('fill="currentColor"', f'fill="{cob}"'); open("proof_leaf.svg", "w").write(leaf)
for sz in [512, 128, 64, 48, 32, 16]:
    subprocess.run(["rsvg-convert", "-w", str(sz), "-h", str(sz), "proof_leaf.svg", "-o", f"leaf_{sz}.png"], check=True)
    im = Image.open(f"leaf_{sz}.png").convert("RGBA"); strip.paste(im, (x, 540 - sz), im); x += sz + 24
strip.save("favicon-strip.png")
json.dump(res, open("proof.json", "w"), indent=2); print(json.dumps(res, indent=1))
