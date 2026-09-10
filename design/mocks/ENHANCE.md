# kint bake-off, ROUND TWO: enhance L3, L3b, L5, L6, L8 and build the navbar sheet

Round one built fourteen mocks; they were audited in a real browser at 1920 light, 1920 dark and
390 emulated. The five landing variants in this round were chosen by elpabl0 to be pushed further.
His words: "the best hero section layout out there is 3 and 4" (L3 and L3b, the poster heroes).
This round applies Josh Puckett's Interface Craft to each file. Read this whole document, then
`BRIEF.md` (doctrine and technical contract, still in force), then `COPY.md` (frozen copy, now with
the FULL epoch transaction hashes so every epoch can link to its basescan tx page), then LOOK at the
render of your page (paths below) before touching the file. You are refining a render, not writing
from scratch. Keep everything that already works.

## The stance (name the feeling first; every decision must serve it)
kint's four facets, stack-ranked:
1. **Exact.** Every number on the page is real and verifiable; the design must feel measured, not decorated. Machine facts in mono, tabular figures, hairlines that land on a grid.
2. **Trustworthy.** A judge reads this in ninety seconds and decides whether the claim (verified against the chain) is credible. Restraint, consistency, one accent, real artifacts (the transcript, the ciphertext, the block heights) instead of illustration.
3. **Calm.** Warm paper, one temperature, generous whitespace, one motion beat, nothing pulsing.
4. **Inventive.** One idea per page that a judge has not seen this week: the real bytes as texture, the rings that are epochs, the annotation grammar, the split headline. Never more than one.

Score your page on these four (1 to 5) from the render BEFORE you change anything, write the scores
in your return, then fix the biggest gap first. Do not declare done until every facet is 4 or above
on your honest read of the code you wrote AND the page still passes the technical contract.

## Craft rules that bind this round (distilled from Interface Craft; violations are BELOW floor)
- **Default, then exceed.** Start from what a clean base.org or Linear page would do, then beat it on every axis. Never below the floor.
- **One dominant focal element per screen.** The hero owns the first screen. Every later section has one thing that wins (the transcript sheet, the box, the strip). Establish dominance BEFORE subtracting; subtraction that flattens the hero is a regression.
- **Two type voices, not one.** A display voice for presence at HERO scale, a clean text voice for everything else, mono only for coordinates (hashes, seqs, blocks, commands, eyebrows). The display face must carry the largest thing on the page; if it only shows up small it is decoration. Section headlines go to the text voice, smaller (the display voice used everywhere dilutes it).
- **Type scale: five sizes max, gentler ratio below the base.** Display leading 1.0 to 1.1, body 1.4 to 1.6, measure 45 to 75ch (`max-width: 66ch` on prose). `text-wrap: balance` on headings, `pretty` on body. Tabular figures on every number that sits in a column or animates. Tracking tightens as size grows; open up small caps eyebrows.
- **One temperature, held everywhere.** Every neutral warm (or every neutral cool for L6). Tint via opacity of the ink, never a new grey. Audit: desaturate the palette in your head; any neutral that is a different temperature is the defector.
- **The accent does ONE job at FULL strength and reaches real mass:** the filled primary CTA and the one hero element (the coloured word, the rings, the dither's live cells), plus the wordmark square. Not on chrome, not on labels, not on row fills. Timid accent (a hairline plus a grey CTA) is as wrong as a sprayed one. Verdict green and red only on verdict tokens, desaturated so they never outshout the accent.
- **Hairlines are inset box-shadows or ink at 8 to 14 percent alpha, never `border: 1px solid` in a solid colour.** One radius language keyed to role: pills for controls, 12 to 16px for containers, 0 where the variant's grammar is square (L8, L7).
- **Depth: pick one system.** Light paper pages use luminance depth (the whitest surface is the focus, no shadows) OR one named soft shadow on the one sheet that earns it. Dark palettes stage on `#0e0e0e` at the darkest, cards lifted to `#16` to `#1a`, two-tier shadow (contact + ambient) on anything that floats, a 1px inner top highlight on the focused surface. Never pure black.
- **Material weight matches role.** Footer, captions, meta rows, the nav: quiet, base layer, no cards, no borders. Only content that earns emphasis floats.
- **Alignment: two dominant vertical rules per screen, no more.** Count the invisible edges; collapse. Trim container top padding so titles sit optically balanced. Icons in buttons optically centred, not mathematically.
- **Motion: gate zero first (should it animate at all?), then one beat per page**, ease-out only (`cubic-bezier(0.23,1,0.32,1)` or `cubic-bezier(0.16,1,0.3,1)`), functional UI under 300ms, the signature beat 600 to 900ms once, press feedback `scale(0.97)` on every pressable, hover gated behind `@media (hover:hover) and (pointer:fine)`, `prefers-reduced-motion` gentler not zero, `transform` and `opacity` only.
- **Copy is interface.** No invented claims. Real numbers. Eyebrows in sentence case unless mono uppercase. Curly quotes and a real ellipsis where prose needs them (never an em dash).
- **Uncommon care lives in the overlooked places:** the focus ring (soft, in the accent, matching the hairline weight), the hover on a mono fact (a copy affordance), the empty margin that is deliberately empty, the caption that tells the reader the texture is real, the 390 layout that is designed rather than collapsed.
- **Mobile is designed, not collapsed.** At 390 the hero still has one dominant element, the CTA is a full-width primary with the secondary as a text link beneath (hierarchy by fill contrast, not size), the proof strip becomes a stacked fact list, tables scroll in their own container, the nav is the variant's own mobile grammar (see the navbar sheet).

## Renders to look at first (Read these PNGs; they are the current state of your page)
Directory: `/private/tmp/claude-501/-Users-alkautsar-Documents-s0nderlabs-kint/5b4c89b5-7f08-4133-823b-e4a1e2c7b007/scratchpad/judge/`
Per key: `<key>-light-top.png`, `<key>-light-mid.png`, `<key>-light-low.png`, `<key>-dark-top.png`, `<key>-m390.png`, `<key>-m390-mid.png`, and `sheet-<key>.png` (all four side by side).

## Per-variant critique and enhancement (observation, impact, alternative)

### L3 Poster, generative (`l3.html`)
Render: the cobalt field with the rings of dots on the sand, the type stack centred over the field, bone pill. The rings were redrawn since the first audit (dense dots, larger figure).
- **The rings are decoration until they are labelled.** Observation: two accent rings and faint guides, nothing says they are epochs. Impact: a judge reads a pattern, not the chain. Alternative: add two small mono labels as HTML positioned over the canvas at each accent ring's right edge (`epoch 1 · block 51,081,867 · 14 rows` and `epoch 2 · block 51,081,880 · +2 rows, 1 gone`), bone text at 12px with a 1px leader line to the ring; the figure gets one label beneath it: `rules / release-gate`. Compute positions from the same ring geometry the canvas uses (expose cx, cy, rx, ry per ring on `window.__rings` and place the labels after draw and on resize). Now the hero IS the head walk. This is the page's one inventive idea; nothing else on the page may compete with it.
- **The nav pill "Theme" is a control in a different language from the text links.** Impact: the Style Details rule (one control treatment) is broken in the first 40px. Alternative: the toggle becomes an icon button the same height and weight as the links, and the wordmark sits top-left in bone (the mark belongs in the nav; the hero stack can keep a larger one only if the two are not within 300px of each other, otherwise drop the hero one).
- **The document below the hero is at the floor.** Impact: after a strong first screen the page goes generic. Alternative: (a) a proof strip directly under the hero as a full-bleed ruled band in mono, cells hairline-separated, contract and both epochs linked; (b) the three actors as three columns on one hairline with numerals in the accent; (c) the transcript on one white sheet with a single soft shadow (the only shadow on the page); (d) the box as a full-bleed cobalt band, bone text, so the accent reaches mass a second time and rhymes with the hero; (e) honest limits as a two-column ruled list.
- **Dark theme.** The cobalt sky should deepen (`#0B1230`), the sand darken to `#2A2618`, the rings lift to `#7A93FF`, the figure becomes bone; verify every token pair in both palettes.
- Motion: keep the rings drawing outward once (1.2s, ease-out); labels fade in after the rings land. Nothing else moves.

### L3b Poster, image (`l3b.html`)
Render: the grainwave image full bleed, the type stack bottom-weighted over the sand, a bone pill, then a plain document.
- **New image.** `assets/poster-kint.png` is being generated for this round (a lone figure at the centre of dotted rings on a sand plain, a closed laptop half sunk in the foreground sand, cobalt sky, one red house). If it exists when you build, use it; if not, keep `assets/grainwave.png` and note it. Position the type stack so it never covers the figure or the laptop: read the image (Read the PNG) and place the stack in the emptiest region, most likely centred over the lower sand or lower-left, with a smoothstep-eased scrim (fifteen stops, `t*t*(3-2*t)`, see below) rather than a linear gradient so there is no visible horizon line where the scrim stops.
- **The wordmark is missing from the nav.** Alternative: wordmark top-left in bone, App and GitHub and the icon toggle top-right, all one control language, quiet.
- **Everything under the hero: same programme as L3 (a) to (e)**, so L3 and L3b differ only in the hero and you can compare generative against image directly.
- The scrim recipe (drop it in as the hero's bottom layer):
  `background: linear-gradient(to top, rgb(15 20 36 / 1) 0%, rgb(15 20 36 / .985) 7.1%, rgb(15 20 36 / .945) 14.3%, rgb(15 20 36 / .882) 21.4%, rgb(15 20 36 / .802) 28.6%, rgb(15 20 36 / .708) 35.7%, rgb(15 20 36 / .606) 42.9%, rgb(15 20 36 / .5) 50%, rgb(15 20 36 / .394) 57.1%, rgb(15 20 36 / .292) 64.3%, rgb(15 20 36 / .198) 71.4%, rgb(15 20 36 / .118) 78.6%, rgb(15 20 36 / .055) 85.7%, rgb(15 20 36 / .015) 92.9%, rgb(15 20 36 / 0) 100%)`, height 55 percent of the hero.
- Motion: none in the hero. The image is the beat.

### L5 Pixel (`l5.html`)
Render: the Doto H1 over the dithered ciphertext band, blue pill, the proof strip now with the address on its own row, section headlines in Doto.
- **The display voice is diluted.** Observation: Doto carries the H1 (right) and every section headline at 28px (wrong). Impact: the pixel voice stops being an event. Alternative: section headlines in Schibsted Grotesk 500 at 22px; Doto stays on the H1 only, plus the two-digit section numerals (`01`) in the accent at 12px, which keeps the pixel voice present as a coordinate.
- **The texture is real but nobody is told.** Alternative: a one-line mono caption under the hero, quiet: `the field above is epoch 1 as it sits on Base: 900 bytes of ciphertext, one cell per byte`. This is the breadcrumb.
- **The strip's first row is heavier than the second** (address alone, then six cells). Alternative: make the address cell carry a 12px mono label `EpochAnchor` above the value like the others, same padding, so the two rows read as one system; both epochs get their own cells linking to their tx pages.
- **The toggle glyph (a half square) is the only icon on the page.** Fine if it matches the dither's 6px cell logic: make it a 12px dithered square (three cells on, one off) so the only icon speaks the page's language.
- Consistency sweep: one radius (pills for controls, 12px for the sheet), one hairline alpha, verdict colours desaturated so they never outshout the blue.
- Motion: keep the one-cell shift every 400ms; it must pause under `prefers-reduced-motion` and while the tab is hidden.

### L6 Base native (`l6.html`)
Render: white page, 72px headline, two pills, the transcript on a sheet on a grey band, the box on a near-black band.
- **At the floor by design; the job is ABOVE.** Observation: it reads as a clean base.org cousin, nothing a judge has not seen. Alternative, three moves: (a) the transcript sheet becomes the page's product artifact the iA way: a white sheet, 12px radius, a two-tier shadow (`0 1px 2px rgba(0,0,0,.06), 0 24px 60px -32px rgba(0,0,0,.28)`), a 1px inner top highlight, sitting on the `#F7F7F7` band with the proof facts as a mono caption row beneath it; (b) the H1 gets `text-wrap: balance`, tracking -0.03em, and the coloured word is the only blue on the first screen besides the one pill; (c) the box band is not black: use `#111` lifted to `#171717` with the hairline between bands removed, so the dark band reads as one calm plane.
- **Section labels without headlines leave sections feeling unowned.** Alternative: keep the mono label, add a one-line text-voice headline in Open Sauce One 500 at 22px using COPY's own bold lines where they exist (the three actors' first sentences are headlines already), no invented words.
- **Buttons: verify the glyph is optically centred** (12/9 not 12/12) and both pills share one height and one radius; hover lifts 1px with no shadow.
- Motion: none. L6 wins by stillness.

### L8 Split (`l8.html`)
Render: the ruled grid, Archivo Expanded over Cormorant italic in blue, the laptop and padlock line drawing, four ruled cells for the facts.
- **The drawing is generic.** Observation: a laptop with a padlock could be any security product. Alternative: redraw as a 1-bit diagram of THIS product, under 40 elements, 1.5px strokes, no fills: a laptop whose screen holds six short horizontal lines (rows); from the screen a vertical chain of three small squares rises, each linked by a short line, the top square drawn slightly larger and labelled in Fragment Mono `51,081,880` beneath it; the padlock sits on the second square. Now the picture is the mechanism: rows to leaf to root to block.
- **The cells' labels and values: CONTRACT / HEAD / DIGEST / STORE.** Keep. Add each epoch as a linked mono line inside HEAD (`epoch 2 · tx 0x369907fb…` linking to the tx page).
- **Buttons are square and the nav is square; the toggle is a bordered square: consistent, good.** Check the CTA pair: primary solid blue with white text, secondary a 1px hairline in ink alpha, both the same height; hover inverts the secondary.
- **Section bands.** Each actor band should carry its numeral in a 32px 1px-bordered square at the left cell, the text in the right cell, one hairline between bands and no double lines where cells meet (only one edge per cell carries the line; overlapping transparent borders sum and read darker).
- Motion: none.

## The navbar sheet (`nav.html`, a new file, one builder)
One self-contained page under `.v-nav` showing EIGHT navbar concepts, each rendered TWICE side by side: a desktop frame (1180px wide, 96px tall, showing the nav over the top of a greyed hero stub) and a mobile frame (390px wide, 640px tall, showing the nav in its mobile grammar over the same stub, including any bottom bar). Each concept gets a mono label, a one-line rationale, and a one-line note on the scroll behaviour. Shared tokens from BRIEF.md (paper, ink, Base blue), Satoshi + Fragment Mono, both themes and a toggle. Use real copy: wordmark `kınt` with the square, links App and GitHub, the CTA "Open the app", the live fact `head seq 2 · block 51,081,880`.
1. **Hairline bar.** Wordmark left, App and GitHub right, icon toggle, one hairline below. Mobile: same, the links stay (two words fit), no burger.
2. **Centred trio.** Wordmark left, links centred, one filled pill right (base.org). Mobile: wordmark left, pill right, links move into the hero.
3. **Floating island.** A pill-shaped bar 16px from the top, `backdrop-filter: blur(16px) saturate(1.4)`, ink at 6 percent fill, 999px radius, wordmark, links, toggle inside; shrinks from 56 to 44px after 80px of scroll (transform only). Mobile: the island holds wordmark + one pill.
4. **Proof bar.** The nav carries the live chain fact centred in mono (`head seq 2 · block 51,081,880 · in step`) with a 6px accent square that pulses ONCE on load; links right. Mobile: the fact becomes a 32px strip under the bar.
5. **Left rail (app chrome).** A 56px fixed rail: mark at the top, three icon glyphs (memory, history, verify) drawn as 1.5px monoline SVG, the theme toggle and the owner avatar (a 24px square with the checksummed address on hover) pinned to the FOOT. The content region scrolls independently (`h-screen` grid, `min-height:0; overflow:auto` on main), the rail never moves. Mobile: the rail becomes a bottom tab bar with ONLY the three peers (memory, history, verify); connect and theme live in a 48px header. That is the peerness rule from the course.
6. **Sticky shrink.** A masthead with the wordmark at 48px and the eyebrow, collapsing to a 48px bar as you scroll (font-size mapped from scrollY 0 to 128 onto 48 to 16 with `mapRange`, clamped), the iOS large-title move. Mobile: same, in a scroll container so the judge can scroll it in the frame.
7. **Inline sentence nav.** No bar: the first line of the page is one sentence with the wordmark in the accent, and the links and the CTA sit on the very next line as pills and dashed-underline text (Radicle). Mobile: the same two lines, wrapping.
8. **Hairline with the toggle as the only control.** Wordmark left, a single icon toggle right, nothing else; links live in the footer. The most Calm option. Mobile: identical.
Each frame is an `<iframe srcdoc>` or a scoped div; use scoped divs with `overflow:hidden` and their own `--vw` so they render side by side without real iframes. At 390 real viewport the sheet stacks one concept per screen with the mobile frame first.

## Technical contract (unchanged from BRIEF.md, plus)
- Edit the existing file in place for L3, L3b, L5, L6, L8 (write part files, cat, replace). Keep the key, the `.v-<key>` scope, the three-state theme pattern, the pre-paint script, the toggle, the wordmark trick with its tuned `top` value (already measured per face; do not change the number).
- LOCAL FILE WORK ONLY. No network, no rendering, no viewing the result in any program: the judge renders. The Google Fonts link stays the only URL besides basescan.
- Self-checks (BRIEF.md) before returning, plus: `grep -c 'border:1px solid' <key>.html` must be 0 where the variant does not use square grid rules (L8 may keep its grid lines as `box-shadow` insets or `outline`, never solid borders that double at cell seams).
- Return the structured object: key, file, facets_before {exact, trustworthy, calm, inventive}, facets_after, the list of moves you made (one line each), deviations, notes.
