# kint design bake-off: BUILD RULES (all fourteen builders)

## What you are building
ONE self-contained HTML mock for ONE variant, executing the FROZEN copy in `COPY.md` under the
variant spec assigned to you below. Fourteen mocks get judged side by side in a real browser at
1440 wide (light and dark) and at 390 wide; the winners become the real Next.js landing page and
app. Build it as a page a very good studio would ship, not a sketch. Restraint wins: fewer
elements, each to a higher bar. If a decoration carries no meaning, it goes.

The product, in one line: kint keeps a coding agent's Sibyl Memory wallet-owned, encrypted, and
kept on Base, restores it on any machine by wallet connect, verifies every recalled row against
the chain before the agent acts on it, and can show what the agent believed at an earlier block.
It is built on Sibyl Memory and sits UNDER it (their eight tools unmodified, kint adds six).

## Inputs (read all before writing a line)
- `COPY.md`: frozen copy, real numbers, banned words. Never alter copy. Never add claims.
- `assets/transcript.txt`: the real CLI output the transcript in COPY.md was cut from.
- `assets/epoch1-hex.txt`: 900 real bytes of epoch 1 ciphertext as hex, for hex or dither textures.
- `assets/grainwave.png`: a generated grainy landscape (L3b and B1 only). If the file is missing
  when you build, use the CSS fallback described in your spec; do not stop.
- `fonts/`: the licensed local faces (see Fonts). Everything else loads from Google Fonts.

## Doctrine (non-negotiable, every variant)
1. **BOTH palettes, every time, plus a visible toggle.** Three viewer states exist: an explicit
   choice stamps `data-theme="dark"` or `data-theme="light"` on `<html>`; the default stamps
   nothing and only `prefers-color-scheme` separates light from dark. The token pattern, all
   four parts: (a) bare `:root` defines the COMPLETE light palette; (b) `@media
   (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { ...tokens only... } }`;
   (c) `:root[data-theme="dark"] { ...tokens again... }`; (d) `body { background: var(--page);
   color: var(--ink) }` explicitly. NEVER give a colour its only definition inside a media or
   `[data-theme]` block; style every component through tokens. Paste this pre-paint script as the
   FIRST child of `<head>`:
   `<script>(function(){try{var t=localStorage.getItem('kint-theme');if(t==='dark'||t==='light')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>`
   and ship a toggle button (top right of the nav or top bar, `aria-label="Toggle theme"`) whose
   click reads the current state (attribute, else `matchMedia`), sets the opposite on `<html>`,
   and persists it in `localStorage` inside try/catch. A dark-first variant (L4, A3) swaps the
   roles consistently but still defines both complete palettes.
2. **One accent, three jobs**: the wordmark square, the primary action, the one coloured word
   in the H1 (and the diff words in the history view). Nowhere else. Verdict colours (verified
   green, refused red) live only on verdict pills and the refusal lines. Your spec names the accent.
3. **Warm neutrals, never pure white or pure black** unless your spec explicitly says so (L6 does).
4. **Five type sizes per page at most, nothing under 12px.** Mono is a coordinate, never prose:
   it carries hashes, seqs, block heights, addresses, commands, eyebrows. Body prose is never mono
   except in L4 and A3, where the spec makes mono the voice.
5. **Emphasis is one coloured word, never italic prose.** Uppercase only in mono eyebrows and labels.
6. **The wordmark trick**, identical in every variant: render the wordmark as
   `<span class="wm">k<span class="i">ı</span>nt</span>` using U+0131 (dotless i) and draw the
   dot yourself: `.wm .i{position:relative}.wm .i::after{content:"";position:absolute;left:50%;
   transform:translateX(-50%);top:-0.02em;width:.18em;height:.18em;background:var(--accent)}`.
   Tune `top` so the square sits where the tittle would be, slightly larger than the font's own
   dot, in the accent colour. Lowercase always.
7. **The house grain** is allowed and welcome in the paper variants: `body::before` fixed,
   fractalNoise baseFrequency 0.9, 4 octaves, 256px tile, opacity 0.03, z-index 9999,
   pointer-events none (the same SVG data URI used in sigil, wdk and nativ). Not in L6.
8. **Motion: at most one beat per page**, named in your spec. `--ease-out-expo:
   cubic-bezier(0.16,1,0.3,1)`. No entrance zoo, no looping pulses, no parallax.
9. **Hairlines are quiet**: 1px at 10 to 14 percent ink alpha, or inset box-shadows. No
   drop shadows except the one your spec names. Radius by role: containers 12 to 16px,
   controls 999px (pills) unless the spec says square.
10. **Real numbers only.** Every address, hash, block, row comes from COPY.md. Never invent a
    number or a claim. Links to basescan use the real hashes:
    `https://basescan.org/address/0xa22E03f7a4145Bf4909a83595C90a38E14d79600`,
    `https://basescan.org/tx/<tx hash from COPY.md>`.
11. **Banned words** (COPY.md) never appear. **No em dash (U+2014) anywhere**, comments included.
12. **390px must be clean**: no horizontal overflow, wide content scrolls inside its own
    `overflow-x:auto` box, tables collapse to stacked rows or scroll in their container.
13. Both themes must read on their own: check every colour pair you introduce for contrast in
    BOTH palettes before you finish (ink on page at least 7:1 for body, 4.5:1 for muted).

## Fonts
Local faces live in `fonts/` (relative to your file, which lives in `design/mocks/`). Declare
with `@font-face` and `font-display: swap`:
- Satoshi: `fonts/Satoshi-Variable.woff2` (`font-weight: 300 900`, ALWAYS set explicit weights,
  the fvar default is 900) and `fonts/Satoshi-VariableItalic.woff2`.
- Fragment Mono: `fonts/FragmentMono-Regular.ttf` (400), `fonts/FragmentMono-Italic.ttf`.
- Geist Mono: `fonts/geist-mono-var.ttf` (`font-weight: 100 900`).
- Instrument Sans: `fonts/instrument-sans-var.ttf` (`font-weight: 400 700`).
- Open Sauce One: `fonts/OpenSauceOne-Regular.ttf` (400), `-Medium.ttf` (500), `-SemiBold.ttf` (600).
- Geist Pixel Square: `fonts/GeistPixel-Square.woff2` (display only, sparingly).
Google Fonts faces load with ONE `<link>` per file, e.g.
`<link href="https://fonts.googleapis.com/css2?family=GFS+Didot&family=Martian+Mono:wght@300..800&display=swap" rel="stylesheet">`.
Available there: GFS Didot, Martian Mono (wght 100..800), Bricolage Grotesque
(opsz 12..96, wght 200..800), Doto (wght 100..900, ROND 0..100), Schibsted Grotesk
(ital, wght 400..900), DM Mono (300, 400, 500), EB Garamond (ital, wght 400..800),
Courier Prime (400, 700, ital), Archivo (ital, wdth 62..125, wght 100..900), Cormorant Garamond
(ital, wght 300..700). Never Inter, never system-ui as a visible face, never Fraunces or IBM Plex
Mono (those are Sibyl's), never Instrument Serif, Newsreader or Ioskeley.

## Technical contract
- One file: `design/mocks/<key>.html` (keys below). Self-contained apart from the Google Fonts
  link and the relative font and asset paths. CSS in one `<style>` block. JavaScript allowed only
  for: the theme script and toggle, and the ONE variant-specific behaviour your spec names.
- Scope every selector under a root class on `<body>`: `.v-<key>` (for example `.v-l1`).
- Write in NUMBERED PART FILES of at most 200 lines each (`<key>.part1.html`, `<key>.part2.html`,
  ...) with the Write tool, then concatenate with Bash: `cat <key>.part*.html > <key>.html`.
  A single giant Write silently truncates. This is a hard rule.
- Do not open a browser, do not screenshot, do not fetch anything: the judge renders. Local
  work only. No network except the Google Fonts link inside the HTML itself.
- Self-check with Bash before returning: `grep -c $'\xe2\x80\x94' <key>.html` must print 0;
  `grep -c 'data-theme="dark"' <key>.html` at least 1; `grep -c 'prefers-color-scheme' <key>.html`
  at least 1; `grep -ciE 'sync|cross-device|multi-device|shared memory|fleet|sovereign|supercharged|single source of truth|tamper-proof|immutable' <key>.html` must print 0 (the word "sovereign" is banned even in comments); the file under 160 KB.
- Landing variants render ALL sections of COPY.md in this order: nav, hero, proof strip, the three
  actors, the beat, the box, honest limits, footer. Restyle freely, never drop a section.
- App variants render the FOUR screens of COPY.md stacked vertically in one file, each
  `min-height: 100svh`, separated by a mono label strip (`screen 1 · connect`, `screen 2 · cold
  start`, `screen 3 · the memory`, `screen 4 · history`), plus the verdict pills and the three
  error lines somewhere visible on screen 3 or 4.
- Return (StructuredOutput): `{file, lines, faces_used, accent, self_check: {emdash, banned,
  themes, size_kb}, deviations, notes}` where deviations lists ANY place you departed from the
  spec or the copy and why.

## Shared palette defaults (a variant spec overrides only what it names)
Light: `--page:#F7F6F2; --card:#FFFFFF; --ink:#1A1916; --ink-2:#4F4C46; --muted:#7A766E;
--hair:rgba(26,25,22,.12); --accent:#0000FF; --ok:#199473; --bad:#B3404A`.
Dark: `--page:#161513; --card:#1E1D1A; --ink:#ECEAE4; --ink-2:#C9C6BE; --muted:#8F8B82;
--hair:rgba(236,234,228,.14); --accent:#4D7CFF; --ok:#3AD1A6; --bad:#EE8295`.
Layout defaults: content column 880px (landing prose) and 1180px (wide bands), section padding
`clamp(72px, 9vh, 144px)`, measure 62ch for prose.

---

## VARIANT SPECS

### L1 Ledger (key `l1`)
Mood: a quiet document on ruled paper. Lineage: Ink and Switch's two-column grid, Sibyl's
section opener, iA Writer's restraint. Faces: Satoshi (display 500 and body 400) + Fragment
Mono. Palette: defaults. Grid: a 660px reading column plus a 200px margin column to its right;
chain facts (tx hash, block height, verdicts) sit in the margin beside the sentence they prove,
as small mono. Section opener, identical every time: a 24px accent hairline, a 12px mono eyebrow
at 0.12em tracking, then the headline. Hero: eyebrow, H1 at clamp(2.6rem,5.5vw,4.6rem) weight
500 with "outlives" in the accent, lede in the 660 column, one solid pill (ink fill) and one text
link, the install line as mono below. Proof strip: a full-width band of hairline-separated mono
cells. The transcript: on a slightly deeper card with a 1px hairline, 14px mono, no window
chrome. Motion beat: the proof strip numbers count up once on load.

### L2 Inscription (key `l2`)
Mood: Greek and technical, restrained. Lineage: the Vorflux posters (cream, ink, one warm accent,
engraved figure, brace labels, blueprint rules), with Sibyl the oracle as the neighbour. Faces:
GFS Didot (display only, 400) + Instrument Sans (body 400, UI 500) + Martian Mono (labels 400).
Palette: light `--page:#F3EEE3; --card:#FBF8F1; --ink:#14110D; --accent:#E07A5F`; dark
`--page:#171410; --card:#1F1B16; --ink:#EFE9DD; --accent:#F08C74`. Hero: two columns; left the
eyebrow in mono with a brace label like `{ 01 } MEMORY ANCHORED`, the H1 in Didot at
clamp(3rem,6.5vw,5.6rem), lede, CTAs; right a single engraved figure drawn as inline SVG line art
in ink at 1px stroke: a classical profile head (an oracle) inside a thin circle, overlaid with a
blueprint layer of fine rules, a golden-ratio rectangle, and mono annotations pointing at it:
`row`, `leaf f406bb09`, `rows_root 390336ff`, `block 51,081,880`. Keep the drawing simple and
deliberate (under 60 SVG elements), never a stock statue. The proof strip is a ruled ledger line
in mono with brace-numbered cells. Section openers: `{ 02 } THE THREE ACTORS` style. The box uses
a thin double rule top and bottom like an inscription plate. Motion beat: the annotation lines draw
in once (stroke-dashoffset) on load.

### L3 Poster, generative (key `l3`)
Mood: one image carries the hero. Lineage: Palak's moonlight poster and Hewar's grainwave, drawn
generatively from the real data instead of an AI image. Faces: Bricolage Grotesque (display at
opsz 96, weight 500; body at opsz 14, weight 400) + Geist Mono. Palette: light `--page:#F4F1EA;
--ink:#171512; --accent:#1F3FD6`; dark `--page:#0F1424; --ink:#ECEAE4; --accent:#7A93FF`.
Hero: full viewport. A `<canvas>` fills it: the upper 55 percent a deep cobalt field (#1F3FD6 in
light, #0B1230 in dark) with heavy grain, the lower 45 percent a sand plain (#E9DFC7 light,
#2A2618 dark) on which concentric rings of dots are drawn in the accent, one ring per epoch (draw
two thick rings plus faint guide rings), and one small dark figure (a simple 14px silhouette
drawn with two rectangles and a circle) standing at the centre. The rings are the epochs, the
figure is the row. Grain: draw noise per pixel with a seeded PRNG at ~18 percent alpha. Over the
canvas, centred: the wordmark, the H1 in bone (#F4F1EA) with "outlives" in a lighter accent tint,
one sentence of lede, one bone pill. Nothing else in the hero. Below the hero, the rest of the
page is a plain document: 880 column, section openers as mono eyebrows. Motion beat: the rings
draw outward once on load, 1.2s, ease-out-expo. Fallback if canvas is unavailable: the same
composition in CSS gradients plus the grain overlay.

### L3b Poster, grainwave image (key `l3b`)
Identical to L3 in every respect (same faces, palette, sections, copy) EXCEPT the hero: instead
of the generated canvas, use `assets/grainwave.png` as a full-bleed `background-size: cover`
image with a bottom scrim so the type reads, and the same centred type stack. If the file is
missing, use a CSS composition: a cobalt to deep-blue vertical gradient sky, a green-hill
silhouette drawn with two overlapping radial gradients, the grain overlay at 0.12, and one small
red square as the accent object. No canvas. Motion beat: none (the image is the beat).

### L4 Terminal (key `l4`)
Mood: the page reads as terminal output. Lineage: Radicle. Faces: Martian Mono only (400 body,
500 headings, 300 for muted). Dark first: define `--page:#0E1116; --card:#141920; --ink:#E6E8EC;
--ink-2:#B9BEC7; --muted:#7D8590; --accent:#7A93FF` as the default ground AND a complete light
palette (`--page:#F5F5F0; --card:#FFFFFF; --ink:#111318; --accent:#1F3FD6`) under the same
three-state pattern (light applies when the OS prefers light or data-theme="light"). No header
bar: the page opens on one mono sentence, 18px, "kint is Sibyl Memory that outlives the laptop."
with "kint" in the accent and "outlives" in braces `{outlives}` in muted; directly beneath, one
line holding two filled pills (accent "Open the app", muted "Read the README") and the nav links
as dashed-underline text. Sections are man-page labels in uppercase accent at body size:
SYNOPSIS (the lede and three actors as an indented paragraph list), PROOF (the strip as plain
lines: contract, head, digest, rows), THE BEAT (the transcript verbatim inside a 1px dashed
box), ARCHITECTURE (a `<pre>` box-drawing diagram of three stacked boxes: Sibyl Memory server,
kint wrapper, EpochAnchor on Base, with arrows), WHAT SIBYL DOES (the box), LIMITS, then a
version line like Radicle's: `kint 0.2.0 · f5d1eee · 2026-09-10`. Column 775px. Motion beat: a
blinking block cursor after the opening sentence, nothing else.

### L5 Pixel (key `l5`)
Mood: playful but exact. Lineage: Playgrnd's dither, base.org's pixel wordmark. Faces: Doto
(H1 and section headlines, weight 700, ROND 0) + Schibsted Grotesk (body 400, UI 500) + Geist
Mono (labels). Palette: light `--page:#FAFAF7; --ink:#111111; --accent:#0000FF`; dark
`--page:#101010; --ink:#F2F2EE; --accent:#5B8CFF`. Hero: a `<canvas>` band behind the H1 that
renders the real ciphertext from `assets/epoch1-hex.txt` (embed the hex string in the script) as
an ordered dither: each byte becomes a 6px cell whose fill is ink at (byte/255) alpha, thresholded
through a 4x4 Bayer matrix, so the bytes form a visible bit field; the band fades to the page
colour at its edges with a mask. Over it the H1 in Doto at clamp(2.8rem,6vw,5.2rem) with
"outlives" in the accent, then the lede and CTAs in Schibsted. Section headlines in Doto at 28px.
Everything else is plain and quiet: the dither is the ONLY playful element. Mono labels in Geist
Mono 12px. Motion beat: the dither field shifts one cell to the left every 400ms (a slow scroll),
paused when `prefers-reduced-motion`.

### L6 Base native (key `l6`)
Mood: the clean landing done in Base's own tone. Lineage: base.org, iA Writer, Pankaj's clean
pages. Faces: Open Sauce One (display 500, body 400) + DM Mono (labels). Palette: light
`--page:#FFFFFF; --card:#F7F7F7; --ink:#171717; --ink-2:#4A4A4A; --muted:#6F6F6F;
--hair:#EFEFEF; --accent:#0000FF`; dark `--page:#0A0A0A; --card:#141414; --ink:#F2F2F2;
--muted:#9A9A9A; --hair:#232323; --accent:#4D7CFF`. This is the one variant allowed pure white
and near-black. No grain. Slim nav: wordmark left, App and GitHub centred, one solid blue 48px
pill right. Hero: centred, H1 at 72px desktop (clamp(2.6rem,5vw,4.5rem)) weight 500, tracking
-0.03em, line height 1.03, two lines, "outlives" in blue; one 20px muted sentence; two 48px pills
side by side (blue solid with a small white square glyph on the left, white with a 1px hairline);
the install line as a small mono chip. Below, the product shown as a sheet: the transcript on a
white card with a very soft shadow (0 24px 60px -32px rgba(0,0,0,.25)) lying on the #F7F7F7 band.
Sections alternate white and #F7F7F7 full-bleed bands, no rules, 1200px container, big empty
margins. Section labels are 12px uppercase DM Mono in muted above each headline. Motion beat: none.

### L7 Archive (key `l7`)
Mood: a card catalogue; the record. Lineage: anima's desk, a ledger. Faces: EB Garamond (display
500 at large sizes, body 400 at 18px, small caps via `font-variant-caps: small-caps` for the
eyebrows) + Courier Prime (all chain facts, the transcript, the install line). Palette: light
`--page:#F5F0E6; --card:#FBF8F2; --ink:#1F1A14; --ink-2:#4E463C; --muted:#7C7266;
--hair:rgba(31,26,20,.14); --accent:#9E2B25`; dark `--page:#16130F; --card:#1E1A15;
--ink:#EBE4D6; --muted:#9A9083; --accent:#E06A62`. Ruled ledger lines: every section sits on
faint horizontal rules 32px apart (a repeating-linear-gradient background on the section) with a
single vertical margin rule at the left of the column, like a ledger page. Hero: eyebrow in small
caps, the H1 in Garamond at clamp(3rem,6.5vw,5.8rem) weight 500 with "outlives" in the accent,
lede at 20px, one square-cornered ink button and one text link, install line in Courier. Proof
strip as a stamped index card (a card with a 1px ink rule and the accent as a small rubber-stamp
style label "ANCHORED · BLOCK 51,081,880" rotated -3 degrees, opacity .85). The transcript in
Courier Prime on the card. Motion beat: none.

### L8 Split (key `l8`)
Mood: a rule grid and a headline in two voices. Lineage: Anytype. Faces: Archivo (display at
wdth 125 weight 600 for the first H1 line; body at wdth 100 weight 400) + Cormorant Garamond
italic 500 for the second H1 line ONLY + Fragment Mono for labels. Palette: light `--page:#FFFFFF;
--ink:#0B0B0B; --hair:#5B5B5B; --accent:#0000FF`; dark `--page:#0C0C0C; --ink:#F3F3F1;
--hair:#8A8A8A; --accent:#5B8CFF`. The whole page is a 1px hairline grid: a 1680px container with
a ruled box for the hero and four ruled cells beneath it. The H1 splits across two faces on two
lines: "Sibyl Memory that" in Archivo Expanded, then "outlives the laptop." in Cormorant italic in
the accent, sized so both lines are the same width. Right of the headline in the hero box: a
monoline 1-bit line drawing in SVG (ink, 1.5px strokes, no fill) of a laptop with a small padlock
and a chain link floating above it, minimal, under 40 elements. The four cells under the hero
carry the proof strip facts. The three actors are numbered 1 / 2 / 3 in small 1px-bordered
square boxes, each actor its own full-width ruled band. The box and limits are ruled cells too.
No cards, no shadows, no radii anywhere. Motion beat: none.

### A1 Table (key `a1`)
The app as a bounded table. Lineage: Datasette's honesty, Mercury's calm rows, Basescan's fact
rail without the noise. Faces: Satoshi + Fragment Mono. Palette: defaults. Top bar: 48px, wordmark,
then mono facts (owner, tenant, head seq, block) as hairline-separated cells, lock state as a pill
at the right, then the theme toggle. Screen 1: a centred 440px card with the two fields and the
two unlock paths as two equal buttons; the mono line under. Screen 2: a 660 column, the progress
line in mono, the two epoch rows landing as list items with a small accent square bullet, the
finish line. Screen 3: the tier tabs as a text row with counts in mono; the table with 36px rows,
6px cell padding, a single hairline per row, header labels in 12px mono muted uppercase, no
zebra, body column truncated at one line with the full text on hover title; the "no later than
block" column right-aligned in mono; the deleted row in a "gone" group under the table, struck
through; the Datasette-style facet line above the table ("Suggested facets: category, block,
verdict"); the footer line in mono. Screen 4: a right-hand drawer (420px, drawn open in the mock)
with the fact rail: label column 120px muted mono ending in a colon, value column; the two
versions as stacked entries with the changed words in the accent. Verdict pills: 22px, one glyph
plus one word. Motion beat: screen 2 rows fade in staggered once.

### A2 Timeline (key `a2`)
The app as a rail. Lineage: GitHub's file history, Family's status pills. Faces: Instrument Sans
(UI) + Martian Mono (facts). Palette: L2's cream and terracotta. Screen 1: the connect card in
cream with the two paths stacked, the wallet path first with the warning sentence in a quiet box.
Screen 2: a vertical 2px rail at the left of a 760 column; epochs hang on the rail as nodes with
the block height as the node label; rows land inside a bordered card per epoch, hairline-divided,
each row two lines (body 15px 500, provenance 12px mono muted). Screen 3: the memory as the same
rail grouped by block: "block 51,081,867 · epoch 1 · 14 rows" then its card, "block 51,081,880 ·
epoch 2 · +2 rows, 1 deleted" then its card, the deleted row inside epoch 2's card with a "gone"
pill. Each row's right side: a 7-char hash chip in mono on a 10 percent accent tint, a copy icon,
an "open at this block" icon, all 28px and muted. Screen 4: the history of release-gate as the
same rail with two nodes and the diff words in the accent; the rail ends with a terminator line
"End of history for this row". Verdict pills as Family does them: 22px, glyph plus one word, green
for verified, red for refused, muted for closed. Motion beat: the rail draws down once on screen 2.

### A3 Console (key `a3`)
The app as a console. Lineage: Radicle, the CLI itself. Faces: Martian Mono only (Doto allowed
for the top bar wordmark only, 700). Palette: L4's dark-first with the light palette complete.
Screen 1: a prompt line `kint connect --owner 0xC635…87Ec --tenant kint-demo` typed out, then
two selectable lines `[1] sign with the wallet` and `[2] type the passphrase`, a passphrase field
styled as a prompt. Screen 2: the cold start streams line by line (the film moment): the progress
line, then `epoch 1 · block 51081867 · 14 rows · opened`, `epoch 2 · block 51081880 · +2 rows,
1 deleted · opened`, then the finish line, each appearing 350ms apart. Screen 3: `ls` style
listing grouped by tier with aligned columns (key, category, status, block) and body text
indented under each key, the deleted row prefixed with `-` in the refused colour, the facet line
as `filter: category=rules` hint text. Screen 4: `history entity release-gate` output with the two
versions and the diff words in the accent, and the refusal transcript from COPY.md rendered as
what the console shows when a row drifted. A blinking block cursor at the end. Verdict words are
plain text in the verdict colours, no pills. Motion beat: the streaming lines on screen 2.

### A4 Sheet (key `a4`)
The app as sheets on a desk. Lineage: iA Writer's document, imaji's desk (one sheet in focus,
earlier ones tidied into a stack behind). Faces: Bricolage Grotesque (opsz 14 for UI, opsz 96 for
the one headline) + Geist Mono. Palette: L3's bone and cobalt. Screen 1: a single white sheet
(680px, 12px radius, one soft shadow 0 18px 48px -28px rgba(0,0,0,.35)) on the bone desk with the
headline "Unlock the memory", the two paths, and under the passphrase field the hex texture from
`assets/epoch1-hex.txt` printed faintly in mono as the sheet's body (the ciphertext as it sits on
Base). Screen 2: the same sheet, the hex resolving into rows: show it mid-transition, the top
half already readable rows, the bottom half still hex, with the progress line as a mono strip on
the sheet's edge. Screen 3: rows as short sheets in a two-column masonry (each row a small sheet
with key, category, body, and the block height in mono at the foot), tier tabs as a mono row above,
the deleted row as a greyed sheet with "gone at block 51,081,880". Screen 4: release-gate's two
versions as two sheets, the current one in front, the older one offset behind it (rotate -1.5deg,
translate), the diff words in the accent. Verdict pills on the sheet corners. Motion beat: the
hex-to-rows resolve on screen 2 (a CSS clip-path reveal, once).

### B1 Brand sheet (key `b1`)
Not a page: a presentation sheet for the mark. Lineage: Scotty's logo backdrop. Faces: ALL of
these, one row each: Satoshi 700, GFS Didot 400, Bricolage Grotesque 600 (opsz 96), Martian Mono
500, Doto 700, Open Sauce One 600, EB Garamond 500, Archivo 600 (wdth 125), Schibsted Grotesk 700.
Layout: a full-bleed backdrop, `assets/grainwave.png` blurred (`filter: blur(28px) saturate(.9)`)
with a scrim (light theme: bone at .35; dark: ink at .55) and the grain overlay at .06; if the
file is missing, a CSS gradient of deep green to sage with the grain. On it, a centred column of
nine rows: each row shows the wordmark trick (`kınt` with the accent square) in that face at 96px,
with the face name and weight as a 12px mono label to its left, and to its right the same
wordmark at 24px and the favicon (a 20px accent square with a "k" knocked out in the page colour,
drawn as inline SVG). A second block below: the accent square alone at 16, 32, 64px and the
wordmark reversed (bone on ink) in the two strongest faces. Toggle present. Motion beat: none.
Return `faces_used` as the full list so the judge can check that each row rendered its own face.
