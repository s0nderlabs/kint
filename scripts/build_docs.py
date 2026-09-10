#!/usr/bin/env python3
"""Build kint's docs site from docs/site/*.md. Standard library only.

    python scripts/build_docs.py --out web
    python scripts/build_docs.py --out /tmp/preview --landing design/mocks/index.html

Writes <out>/docs/index.html (overview), <out>/docs/<slug>/index.html (one per chapter),
<out>/docs/<slug>.md (raw markdown for agents), <out>/docs/_/{docs.css,docs.js,search.json},
<out>/llms.txt and <out>/llms-full.txt.

The landing page owns the design tokens and the marks. When --landing points at it, its :root token
blocks and its SVG symbols are read at build time and win over the fallbacks kept in
scripts/docs_assets/, so the docs follow the landing without copying it.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = Path(__file__).resolve().parent / "docs_assets"
REPO = "https://github.com/s0nderlabs/kint"
BLOB = f"{REPO}/blob/main/"
GROUPS = ["Get started", "Concepts", "Reference", "Operate", "Background"]
# The one place the site origin lives (decided by elpabl0 on Sep 10 2026, 22:2x WIB); change it here.
SITE = "https://kint.s0nderlabs.xyz"
NEXT_TEMPLATES = Path(__file__).resolve().parent / "docs_next"


# ---------------------------------------------------------------- markdown (the subset the chapters use)

def slugify(text: str) -> str:
    t = re.sub(r"<[^>]+>", "", text)
    t = html.unescape(t).replace("`", "").lower()
    t = re.sub(r"[^\w\s-]", "", t).strip()
    return re.sub(r"\s+", "-", t)


class Ctx:
    def __init__(self, base: str, slash: bool = True):
        self.base = base
        self.slash = slash
        self.ids: dict[str, int] = {}
        self.heads: list[tuple[int, str, str]] = []  # level, text, id

    def uid(self, s: str) -> str:
        n = self.ids.get(s, 0)
        self.ids[s] = n + 1
        return s if n == 0 else f"{s}-{n}"


LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
LIST_RE = re.compile(r"^( *)([-*+]|\d+[.)])[ \t]+")
FENCE_RE = re.compile(r"^( *)(```+|~~~+)\s*([\w+-]*)\s*$")
HEAD_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def href(url: str, ctx: Ctx) -> tuple[str, bool]:
    if url.startswith("/docs/"):
        rest = url[len("/docs/"):]
        slug, _, anchor = rest.partition("#")
        slug = slug.strip("/")
        if slug.endswith(".md"):
            return (f"{ctx.base}docs/{slug}" if ctx.slash else f"{ctx.base}docs/md/{slug}"), False
        end = "/" if ctx.slash else ""
        path = f"{ctx.base}docs/{slug}{end}" if slug else f"{ctx.base}docs{end}"
        return path + (f"#{anchor}" if anchor else ""), False
    ext = bool(re.match(r"^(https?:)?//", url)) or url.startswith("mailto:")
    return url, ext


def inline(s: str, ctx: Ctx) -> str:
    codes: list[str] = []

    def keep_code(m: re.Match) -> str:
        body = m.group(2).strip() or m.group(2)
        # short tokens never split; long unbroken ones (hashes, addresses) may; phrases wrap at their spaces
        cls = "" if " " in body else (' class="long"' if len(body) > 28 else ' class="nw"')
        codes.append(f"<code{cls}>{html.escape(body, quote=False)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    s = re.sub(r"(`+)(.+?)\1", keep_code, s)
    s = html.escape(s, quote=False)

    def link(m: re.Match) -> str:
        url, ext = href(html.unescape(m.group(2)), ctx)
        cls = ' class="ext"' if ext else ""
        rel = ' rel="noreferrer"' if ext else ""
        return f'<a href="{html.escape(url)}"{cls}{rel}>{m.group(1)}</a>'

    s = LINK_RE.sub(link, s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)
    return s


TREE_GLYPHS = re.compile(r"([├└│─]+)")


def highlight(code: str, lang: str) -> tuple[str, str | None]:
    """Return (html, copy_text). copy_text strips prompts and output from shell transcripts."""
    lines = code.split("\n")
    out: list[str] = []
    is_tree = any(("├──" in l or "└──" in l) for l in lines)
    shell = lang in ("sh", "bash", "shell", "zsh", "console")
    text = lang in ("text", "console", "") and not is_tree
    prompted = shell and any(l.startswith("$ ") for l in lines)
    for raw in lines:
        e = html.escape(raw, quote=False)
        if is_tree:
            e = TREE_GLYPHS.sub(r'<span class="g">\1</span>', e)
        elif shell or lang == "toml" or lang in ("python", "py"):
            prompt = ""
            if shell and raw.startswith("$ "):
                prompt, e = '<span class="p">$</span> ', html.escape(raw[2:], quote=False)
            elif lang == "toml" and re.match(r"^\s*\[.*\]\s*$", raw):
                e = f'<span class="s">{e}</span>'
            e = prompt + comment(e)
        elif lang in ("ts", "js", "javascript", "typescript", "solidity", "sol", "json", "jsonc"):
            e = re.sub(r"(^|\s)(//.*)$", r'\1<span class="c">\2</span>', e)
        if text:
            e = re.sub(r"\b(verified|PROCEED|proceed)\b", r'<span class="ok">\1</span>', e)
            e = re.sub(r"\b(REFUSED|REFUSE|refused|refuse|drifted)\b", r'<span class="no">\1</span>', e)
        out.append(e)
    copy = None
    if prompted:
        copy = "\n".join(l[2:] for l in lines if l.startswith("$ "))
    return "\n".join(out), copy


def comment(e: str) -> str:
    """Grey a trailing # comment that sits outside quotes."""
    q = None
    for i, ch in enumerate(e):
        if ch in "'\"" and (q is None or q == ch):
            q = None if q else ch
        elif ch == "#" and q is None and (i == 0 or e[i - 1] in " \t"):
            if i > 0 and e[:i].strip() == "" and False:
                pass
            return e[:i] + f'<span class="c">{e[i:]}</span>'
    return e


COPY_SVG = ('<svg class="cp" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">'
            '<rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 3.5v-.5a1.5 1.5 0 0 0-1.5-1.5H4A1.5 1.5 0 0 0 2.5 3v5A1.5 1.5 0 0 0 4 9.5h.5"/></svg>'
            '<svg class="ck" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8.5l3.2 3L13 4.5"/></svg>')


def render_blocks(lines: list[str], ctx: Ctx) -> str:
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fm = FENCE_RE.match(line)
        if fm:
            ind, fence, lang = len(fm.group(1)), fm.group(2), fm.group(3).lower()
            buf = []
            i += 1
            while i < n and not re.match(rf"^ *{re.escape(fence[0])}{{{len(fence)},}}\s*$", lines[i]):
                l = lines[i]
                buf.append(l[ind:] if l[:ind].strip() == "" else l)
                i += 1
            i += 1
            body, copy = highlight("\n".join(buf), lang)
            dc = f' data-copy="{html.escape(copy)}"' if copy is not None else ""
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f'<div class="code"><pre{dc}><code{cls}>{body}</code></pre>'
                       f'<button class="copy" type="button" aria-label="Copy">{COPY_SVG}</button></div>')
            continue
        hm = HEAD_RE.match(line)
        if hm:
            level, text = len(hm.group(1)), hm.group(2)
            body = inline(text, ctx)
            if level == 1:
                out.append(f"<h1>{body}</h1>")
            else:
                hid = ctx.uid(slugify(text))
                if level in (2, 3):
                    ctx.heads.append((level, re.sub(r"<[^>]+>", "", body), hid))
                tag = f"h{min(level, 4)}"
                out.append(f'<{tag} id="{hid}">{body}<a class="anc" href="#{hid}" aria-label="Link to this section">#</a></{tag}>')
            i += 1
            continue
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line):
            out.append("<hr>")
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(render_table(rows, ctx))
            continue
        if line.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(re.sub(r"^> ?", "", lines[i]))
                i += 1
            inner = render_blocks(buf, ctx)
            warn = ' class="warn"' if re.match(r"^\s*\*\*Warning", "\n".join(buf)) else ""
            out.append(f"<blockquote{warn}>{inner}</blockquote>")
            continue
        lm = LIST_RE.match(line)
        if lm:
            html_list, i = render_list(lines, i, ctx)
            out.append(html_list)
            continue
        buf = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not (FENCE_RE.match(lines[i]) or HEAD_RE.match(lines[i]) or LIST_RE.match(lines[i])
                                                  or lines[i].startswith(">") or lines[i].lstrip().startswith("|")):
            buf.append(lines[i].strip())
            i += 1
        text = " ".join(buf)
        cls = ' class="src"' if text.startswith("Source:") else ""
        if re.match(r"^Read \[[^\]]+\]\(/docs/[^)]+\) next\.$", text):
            out.append(f'<p class="nextline" hidden>{inline(text, ctx)}</p>')
        else:
            out.append(f"<p{cls}>{inline(text, ctx)}</p>")
    return "\n".join(out)


def render_list(lines: list[str], i: int, ctx: Ctx) -> tuple[str, int]:
    first = LIST_RE.match(lines[i])
    base_ind = len(first.group(1))
    ordered = first.group(2)[0].isdigit()
    start = int(re.match(r"\d+", first.group(2)).group(0)) if ordered else 1
    items: list[str] = []
    n = len(lines)
    while i < n:
        m = LIST_RE.match(lines[i])
        if not m or len(m.group(1)) != base_ind or m.group(2)[0].isdigit() != ordered:
            break
        col = len(m.group(0))
        body = [lines[i][col:]]
        i += 1
        loose = False
        while i < n:
            l = lines[i]
            if not l.strip():
                j = i + 1
                while j < n and not lines[j].strip():
                    j += 1
                if j >= n:
                    i = j
                    break
                nxt = lines[j]
                ind = len(nxt) - len(nxt.lstrip(" "))
                if ind > base_ind:
                    body.extend([""] * (j - i))
                    loose = loose or not LIST_RE.match(nxt)
                    i = j
                    continue
                break
            ind = len(l) - len(l.lstrip(" "))
            if ind > base_ind:
                body.append(l[min(ind, col):])
                i += 1
                continue
            if LIST_RE.match(l) or FENCE_RE.match(l) or HEAD_RE.match(l) or l.startswith(">") or l.lstrip().startswith("|"):
                break
            body.append(l.strip())  # lazy continuation of the item's paragraph
            i += 1
        inner = render_blocks(body, ctx)
        if not loose and inner.startswith("<p>") and inner.count("<p>") == 1:
            inner = inner[3:].replace("</p>", "", 1)
        items.append(f"<li>{inner}</li>")
        # a blank line then another item at the same indent continues the list
        if i < n and not lines[i].strip():
            j = i
            while j < n and not lines[j].strip():
                j += 1
            m2 = LIST_RE.match(lines[j]) if j < n else None
            if m2 and len(m2.group(1)) == base_ind and m2.group(2)[0].isdigit() == ordered:
                i = j
    tag = "ol" if ordered else "ul"
    st = f' start="{start}"' if ordered and start != 1 else ""
    return f"<{tag}{st}>" + "".join(items) + f"</{tag}>", i


def split_row(row: str) -> list[str]:
    r = row.strip()
    if r.startswith("|"):
        r = r[1:]
    if r.endswith("|") and not r.endswith("\\|"):
        r = r[:-1]
    cells, cur, in_code = [], "", False
    k = 0
    while k < len(r):
        ch = r[k]
        if ch == "`":
            in_code = not in_code
        if ch == "\\" and k + 1 < len(r) and r[k + 1] == "|":
            cur += "|"
            k += 2
            continue
        if ch == "|" and not in_code:
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
        k += 1
    cells.append(cur.strip())
    return cells


def render_table(rows: list[str], ctx: Ctx) -> str:
    head = split_row(rows[0])
    body = [split_row(r) for r in rows[2:]]
    th = "".join(f"<th>{inline(c, ctx)}</th>" for c in head)
    trs = "".join("<tr>" + "".join(f"<td>{inline(c, ctx)}</td>" for c in r) + "</tr>" for r in body)
    return f'<div class="tbl"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


# ---------------------------------------------------------------- the chapters

@dataclass
class Doc:
    file: Path
    slug: str
    title: str
    description: str
    group: str
    order: int
    source: str
    body: str
    html: str = ""
    heads: list = field(default_factory=list)


def parse_frontmatter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---\n", 4)
    if end < 0:
        return {}, raw
    data: dict = {}
    for line in raw[4:end].split("\n"):
        if ":" not in line or line.strip().startswith("#"):
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        data[k.strip()] = int(v) if re.fullmatch(r"-?\d+", v) else v
    return data, raw[end + 5:].lstrip("\n")


def load_docs(src: Path) -> list[Doc]:
    docs = []
    for f in sorted(src.glob("[0-9][0-9]-*.md")):
        data, body = parse_frontmatter(f.read_text())
        slug = data.get("slug") or re.sub(r"^\d+-", "", f.stem)
        docs.append(Doc(f, slug, data.get("title", slug), data.get("description", ""), data.get("group", "Background"),
                        int(data.get("order", 999)), data.get("source", ""), body))
    docs.sort(key=lambda d: d.order)
    return docs


def plain(h: str) -> str:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S)
    t = re.sub(r'<a class="anc"[^>]*>#</a>', "", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def search_entries(d: Doc) -> list[dict]:
    parts = re.split(r'(<h[23] id="[^"]+">.*?</h[23]>)', d.html, flags=re.S)
    entries = [{"s": d.slug, "t": d.title, "h": d.title, "a": "", "x": (d.description + " " + plain(parts[0]))[:600]}]
    for k in range(1, len(parts), 2):
        m = re.match(r'<h[23] id="([^"]+)">(.*?)</h[23]>', parts[k], flags=re.S)
        text = plain(parts[k + 1] if k + 1 < len(parts) else "")
        entries.append({"s": d.slug, "t": d.title, "h": plain(m.group(2)), "a": m.group(1), "x": text[:600]})
    return entries


# ---------------------------------------------------------------- the landing's tokens and marks

TOKEN_SELECTORS = (':root', ':root:not([data-theme="light"])', ':root[data-theme="dark"]')


def landing_tokens(landing: Path | None) -> str:
    """The landing's custom-property blocks, verbatim, in the order they appear (later wins)."""
    if not landing or not landing.exists():
        return ""
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", landing.read_text(), flags=re.S))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for m in re.finditer(r"(@media\s*\(prefers-color-scheme:\s*dark\)\s*\{)?\s*(:root(?::not\(\[data-theme=\"light\"\]\)|\[data-theme=\"dark\"\])?)\s*\{([^{}]*)\}", css):
        decls = [d.strip() for d in m.group(3).split(";") if d.strip().startswith("--")]
        decls = [d for d in decls if not d.startswith(("--grain-tile", "--leaf-mask", "--edge", "--haze", "--halo"))]
        if not decls:
            continue
        block = f"{m.group(2)}{{{';'.join(decls)}}}"
        if m.group(1):
            block = f"@media (prefers-color-scheme:dark){{{block}}}"
        out.append(block)
    return "\n/* tokens read from the landing at build time */\n" + "\n".join(out) + "\n" if out else ""


def landing_marks(landing: Path | None) -> str:
    if landing and landing.exists():
        m = re.search(r'<svg width="0" height="0"[^>]*>.*?</svg>\s*(?=\n|<)', landing.read_text(), flags=re.S)
        if m and 'id="lockh"' in m.group(0) and 'id="leafm"' in m.group(0):
            return m.group(0).strip()
    return (ASSETS / "marks.svg").read_text().strip()


def favicon(marks: str) -> str:
    m = re.search(r'<symbol id="leafm" viewBox="([^"]+)"><path[^>]*\sd="([^"]+)"', marks)
    if not m:
        return ""
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{m.group(1)}"><path fill="#1F3FD6" fill-rule="evenodd" d="{m.group(2)}"/></svg>'
    return "data:image/svg+xml," + urllib.parse.quote(svg)


# ---------------------------------------------------------------- pages

TOGGLE = ('<button class="toggle" id="themeToggle" type="button" aria-label="Toggle theme"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" focusable="false">'
          '<rect x="0.5" y="0.5" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1"></rect><path d="M7 0.5 H13.5 V13.5 H7 Z" fill="currentColor"></path></svg></button>')
LENS = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.75"/><path d="M10.5 10.5 14 14"/></svg>'
CHEV = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg>'


def head(title: str, desc: str, cfg: dict, alt_md: str | None) -> str:
    alt = f'\n<link rel="alternate" type="text/markdown" href="{alt_md}">' if alt_md else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<script>(function(){{try{{var t=localStorage.getItem('kint-theme');if(t==='dark'||t==='light')document.documentElement.setAttribute('data-theme',t);}}catch(e){{}}}})();</script>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta name="theme-color" content="#F4F1EA" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#12110F" media="(prefers-color-scheme: dark)">
<link rel="icon" href="{cfg['favicon']}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,200..800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{cfg['base']}docs/_/docs.css?v={cfg['v']}">{alt}
</head>"""


def topbar(cfg: dict) -> str:
    b = cfg["base"]
    return f"""<a class="skip" href="#main">Skip to the page</a>
{cfg['marks']}
<header class="top"><div class="in">
  <a class="wm" href="{b}" aria-label="kint, home"><svg viewBox="0 -1 80 29" aria-hidden="true" focusable="false"><use href="#lockh"/></svg></a>
  <a class="crumb" href="{b}docs/">Docs</a>
  <button class="sbtn" id="sbtn" type="button" aria-label="Search the docs">{LENS}<span class="sl">Search the docs</span><kbd>/</kbd></button>
  <a class="link" href="{REPO}">GitHub</a>
  {TOGGLE}
</div></header>"""


def sidebar(docs: list[Doc], active: str | None, cfg: dict) -> str:
    b = cfg["base"]
    cur = ' aria-current="page"' if active is None else ""
    parts = [f'<nav class="side" id="side" aria-label="Chapters"><a href="{b}docs/"{cur}>Overview</a>']
    for g in GROUPS:
        items = [d for d in docs if d.group == g]
        if not items:
            continue
        parts.append(f'<div class="grp"><p class="gh">{g}</p>')
        for d in items:
            cur = ' aria-current="page"' if d.slug == active else ""
            parts.append(f'<a href="{b}docs/{d.slug}/"{cur}>{html.escape(d.title)}</a>')
        parts.append("</div>")
    parts.append("</nav>")
    return "".join(parts)


def footer(cfg: dict) -> str:
    b = cfg["base"]
    return (f'<footer class="foot"><div class="row"><svg class="fwm" viewBox="0 -1 80 29" role="img" aria-label="kint"><use href="#lockh"/></svg>'
            f'<span>MIT &middot; Built for the Sibyl Labs Hackathon, September 2026 &middot; s0nderlabs &middot; on <span class="base" aria-hidden="true"></span>Base</span>'
            f'<span class="links"><a href="{b}">Home</a><a href="{REPO}">GitHub</a><a href="{REPO}#readme">README</a></span></div></footer>')


def search_dialog() -> str:
    return (f'<div class="sd" id="sd" aria-hidden="true"><div class="box" role="dialog" aria-modal="true" aria-label="Search the docs">'
            f'<div class="fld">{LENS}<input id="sin" type="search" placeholder="Search commands, tools, flags, ideas" autocomplete="off" spellcheck="false" aria-controls="sul">'
            f'<button class="esc" id="sesc" type="button" aria-label="Close search">esc</button></div>'
            f'<ul id="sul" role="listbox"></ul></div></div>')


def page(title: str, desc: str, main: str, docs: list[Doc], active: str | None, cfg: dict,
         toc: str = "", alt_md: str | None = None, mtitle: str = "Chapters") -> str:
    shell = "shell" + (" ov" if not toc else "")
    return f"""{head(title, desc, cfg, alt_md)}
<body data-base="{cfg['base']}">
{topbar(cfg)}
<div class="{shell}">
  <button class="mnav" id="mnav" type="button" aria-expanded="false" aria-controls="side"><span>{html.escape(mtitle)}</span>{CHEV}</button>
  {sidebar(docs, active, cfg)}
  <main class="doc" id="main">{main}</main>
  {toc}
</div>
{footer(cfg)}
{search_dialog()}
<script src="{cfg['base']}docs/_/docs.js?v={cfg['v']}" defer></script>
</body>
</html>
"""


def chapter_page(d: Doc, docs: list[Doc], cfg: dict) -> str:
    b = cfg["base"]
    i = docs.index(d)
    prev = docs[i - 1] if i > 0 else None
    nxt = docs[i + 1] if i + 1 < len(docs) else None
    pager = ['<nav class="pager" aria-label="Previous and next">']
    if prev:
        pager.append(f'<a class="prev" href="{b}docs/{prev.slug}/"><span class="t"><span class="ar">&larr;</span> {html.escape(prev.title)}</span>'
                     f'<span class="d">{html.escape(prev.description)}</span></a>')
    if nxt:
        pager.append(f'<a class="next" href="{b}docs/{nxt.slug}/"><span class="t">{html.escape(nxt.title)} <span class="ar">&rarr;</span></span>'
                     f'<span class="d">{html.escape(nxt.description)}</span></a>')
    pager.append("</nav>")
    toc_links = "".join(f'<a class="h{lv}" href="#{hid}">{html.escape(text)}</a>' for lv, text, hid in d.heads)
    edit = f"{REPO}/edit/main/docs/site/{d.file.name}"
    toc = (f'<aside class="toc" aria-label="On this page"><nav>{toc_links}</nav>'
           f'<div class="meta"><a href="{b}docs/{d.slug}.md">Markdown</a><a href="{edit}">Edit on GitHub</a></div></aside>')
    main = f'<article>{d.html}</article>{"".join(pager)}'
    return page(f"{d.title} · kint docs", d.description, main, docs, d.slug, cfg, toc=toc, alt_md=f"{b}docs/{d.slug}.md", mtitle=d.title)


OV_LAYOUT = [  # (groups in the cell, span, tint, columns)
    (["Get started"], "c5", "t1", 1),
    (["Concepts"], "c7", "t2", 2),
    (["Reference"], "c7", "t3", 2),
    (["Operate", "Background"], "c5", "t1", 1),
]


def overview_page(docs: list[Doc], cfg: dict) -> str:
    b = cfg["base"]
    install = ("uv tool install git+https://github.com/s0nderlabs/kint@v0.3.0\n"
               "kint session-key create\n"
               "kint setup all")
    code, _ = highlight("\n".join("$ " + l for l in install.split("\n")), "sh")
    cells = []
    for groups, span, tint, cols in OV_LAYOUT:
        inner = []
        for k, g in enumerate(groups):
            items = [d for d in docs if d.group == g]
            if not items:
                continue
            lis = "".join(f'<li><a href="{b}docs/{d.slug}/"><span class="t">{html.escape(d.title)}<i aria-hidden="true">&rarr;</i></span>'
                          f'<span class="d">{html.escape(d.description)}</span></a></li>' for d in items)
            sep = ' class="gsep"' if k else ""
            inner.append(f'<h2{sep}>{g}</h2><ul style="--cols:{cols}">{lis}</ul>')
        if inner:
            cells.append(f'<li class="bx {tint} {span}">{"".join(inner)}</li>')
    main = f"""<div class="intro">
  <div><h1>How kint works, from install to refusal.</h1>
  <p class="lede-ov">Install it once per machine, connect the wallet, and every harness you run reads Sibyl Memory through kint-server. These pages cover each step, each mechanism, and every command, tool and setting, read from the code at v0.3.0.</p></div>
  <div><div class="code"><pre data-copy="{html.escape(install)}"><code class="language-sh">{code}</code></pre><button class="copy" type="button" aria-label="Copy">{COPY_SVG}</button></div>
  <a class="go" href="{b}docs/quickstart/">Read the quickstart &rarr;</a></div>
</div>
<ul class="bento">{''.join(cells)}</ul>
<div class="more"><p>The README is the GitHub side of these pages, and every page names the source files it explains. Agents can read any page as markdown, or all of it at once.</p>
<div class="links"><a href="{REPO}#readme">README</a><a href="{REPO}/blob/main/CHANGELOG.md">Changelog</a><a href="{REPO}/blob/main/docs/judge.md">Claims table</a><a href="{b}llms.txt">llms.txt</a><a href="{b}llms-full.txt">llms-full.txt</a></div></div>"""
    return page("kint docs", "How kint works, from install to refusal: every step, mechanism, command, tool and setting.",
                main, docs, None, cfg)


# ---------------------------------------------------------------- agents' files

def raw_md(d: Doc) -> str:
    src = f"> Source: {BLOB}{d.source}\n\n" if d.source else ""
    return f"# {d.title}\n\n{src}{d.body.strip()}\n"


def llms_index(docs: list[Doc], site: str, md: str = "docs") -> str:
    bullets = "\n".join(f"- [{d.title}]({site}/{md}/{d.slug}.md): {d.description}" for d in docs)
    return f"""# kint

> Sibyl Memory that outlives the laptop. kint wraps Sibyl Memory's MCP server untouched (their eight tools as shipped, six added), encrypts the memory to the owner's wallet, keeps it on Base as calldata under a small contract, restores it on any machine by wallet connect, and verifies every recalled row against the chain before the agent acts on it.

## Install

kint is not on PyPI yet. Install from the tagged release (Python 3.10+):

```
uv tool install git+https://github.com/s0nderlabs/kint@v0.3.0
```

If the shell sets PYTHONPATH, run the binaries with it unset (`env -u PYTHONPATH kint ...`); `kint setup` bakes `/usr/bin/env -u PYTHONPATH` into every harness registration.

## For AI agents

Never ask the human for the derive signature, the vault passphrase or the recovery code in a chat: the signature only travels on stdin (`kint connect --signature -`), and the other two are typed in a terminal (`--passphrase-stdin`, `--recovery-code-stdin`). Call `memory_verify` before acting on anything recalled; on `refuse`, do not act and tell the human which block anchored the last good value. Full guide: {site}/{md}/agents.md

- Every page as markdown: {site}/{md}/<slug>.md
- Everything in one file: {site}/llms-full.txt

## Docs

{bullets}

## Reference

- Repository: {REPO} (MIT, v0.3.0)
- EpochAnchor on Base mainnet (chain id 8453): 0xa22E03f7a4145Bf4909a83595C90a38E14d79600 (verified on Basescan)
- Sibyl Memory: https://github.com/Sibyl-Labs/Sibyl-Memory
"""


def llms_full(docs: list[Doc], readme: str) -> str:
    head_ = ("# kint, the full documentation in one file\n\n"
             "> Sibyl Memory that outlives the laptop. This file inlines the repository README and every documentation page, "
             "separated by horizontal rules. Each page names its source files.\n\n"
             "Install: `uv tool install git+https://github.com/s0nderlabs/kint@v0.3.0` (not on PyPI yet; Python 3.10+).")
    sections = [head_, f"## README\n\n> Source: {BLOB}README.md\n\n{readme.strip()}"]
    for d in docs:
        src = f"> Source: {BLOB}{d.source}\n\n" if d.source else ""
        body = re.sub(r"^# .*\n+", "", d.body.strip(), count=1)
        sections.append(f"## {d.title}\n\n{src}{body}")
    return "\n\n---\n\n".join(sections) + "\n"


# ---------------------------------------------------------------- Next.js route (web/app/docs)

DROP = {':root', ':root:not([data-theme="light"])', ':root[data-theme="dark"]', '*', '*::before', '*::after', 'html', 'body',
        'body::before', '::selection', 'a', '.skip', '.skip:focus'}
DROP_PREFIX = ('.top', '.wm', '.crumb', '.toggle', '.foot', '.fwm')


def _blocks(css: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while True:
        j = css.find("{", i)
        if j < 0:
            return out
        depth, k = 1, j + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        out.append((css[i:j].strip(), css[j + 1:k - 1]))
        i = k


def _split_sel(sel: str) -> list[str]:
    parts, cur, depth = [], "", 0
    for ch in sel:
        depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p]


def _scope_rules(css: str) -> str:
    out = []
    for sel, body in _blocks(css):
        if sel.startswith("@font-face"):
            continue
        if sel.startswith("@"):
            inner = _scope_rules(body)
            if inner.strip():
                out.append(f"{sel}{{{inner}}}")
            continue
        keep = []
        for s_ in _split_sel(sel):
            if s_ in DROP or s_.startswith(DROP_PREFIX):
                continue
            if s_.startswith("body.menu"):
                keep.append(".kdocs.menu" + s_[len("body.menu"):])
            else:
                keep.append(".kdocs " + s_)
        if keep:
            out.append(f"{','.join(keep)}{{{body.strip()}}}")
    return "\n".join(out)


NEXT_EXTRA = """
/* docs-only tokens and the sticky site bar (web/app/docs only) */
.kdocs{--top:64px;--veil:rgba(23,21,18,.18);--glass:rgba(244,241,234,.94)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .kdocs{--veil:rgba(0,0,0,.5);--glass:rgba(18,17,15,.94)}}
:root[data-theme="dark"] .kdocs{--veil:rgba(0,0,0,.5);--glass:rgba(18,17,15,.94)}
.kdocs [id]{scroll-margin-top:calc(var(--top) + 24px)}
.kdocs .dbar{position:sticky;top:0;z-index:50;background:var(--glass);-webkit-backdrop-filter:saturate(1.4) blur(12px);backdrop-filter:saturate(1.4) blur(12px);box-shadow:inset 0 -1px 0 var(--hair)}
.kdocs .dbar .snav{width:min(var(--wide),100% - 48px);margin-inline:auto;height:var(--top);padding:0}
.kdocs .side .sbtn{width:100%;min-width:0;margin:0 0 16px}
@media (max-width:900px){.kdocs .dbar .snav{width:calc(100% - 40px)}}
"""


def scoped_css() -> str:
    raw = re.sub(r"/\*.*?\*/", "", (ASSETS / "docs.css").read_text(), flags=re.S)
    head = "/* GENERATED by scripts/build_docs.py --next from scripts/docs_assets/docs.css; edit that file, not this one. */\n"
    return head + _scope_rules(raw) + "\n" + NEXT_EXTRA


def build_next(src: Path, web: Path, site: str) -> list[str]:
    docs = load_docs(src)
    if not docs:
        sys.exit(f"no chapters in {src}")
    warnings = []
    slugs = {d.slug for d in docs}
    for d in docs:
        ctx = Ctx("/", slash=False)
        d.html = render_blocks(d.body.split("\n"), ctx)
        d.heads = ctx.heads
        if "—" in d.body:
            warnings.append(f"{d.file.name}: contains an em dash")
    anchors = {d.slug: set(re.findall(r'id="([^"]+)"', d.html)) for d in docs}
    for d in docs:
        for m in re.finditer(r"\]\(/docs/([^)#]*)(?:#([^)]+))?\)", d.body):
            s_, a_ = m.group(1).strip("/").removesuffix(".md"), m.group(2)
            if s_ and s_ not in slugs:
                warnings.append(f"{d.file.name}: link to unknown page /docs/{s_}")
            elif s_ and a_ and a_ not in anchors.get(s_, set()):
                warnings.append(f"{d.file.name}: link to missing anchor /docs/{s_}#{a_}")
    install = ("uv tool install git+https://github.com/s0nderlabs/kint@v0.3.0\n"
               "kint session-key create\n"
               "kint setup all")
    code, _ = highlight("\n".join("$ " + l for l in install.split("\n")), "sh")
    install_html = (f'<div class="code"><pre data-copy="{html.escape(install)}"><code class="language-sh">{code}</code></pre>'
                    f'<button class="copy" type="button" aria-label="Copy">{COPY_SVG}</button></div>')
    content = {
        "site": site, "repo": REPO, "groups": GROUPS, "install": install, "installHtml": install_html,
        "overview": [{"groups": g, "span": sp, "tint": t, "cols": c} for g, sp, t, c in OV_LAYOUT],
        "docs": [{"slug": d.slug, "title": d.title, "description": d.description, "group": d.group, "order": d.order,
                  "file": d.file.name, "source": d.source, "html": d.html,
                  "heads": [{"level": lv, "text": tx, "id": hid} for lv, tx, hid in d.heads]} for d in docs],
    }
    app = web / "app" / "docs"
    (app / "[slug]").mkdir(parents=True, exist_ok=True)
    for f in NEXT_TEMPLATES.rglob("*"):
        if f.is_file():
            dest = app / f.relative_to(NEXT_TEMPLATES)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dest)
    (app / "content.json").write_text(json.dumps(content, ensure_ascii=False))
    (app / "docs.css").write_text(scoped_css())
    gen = app / "_gen"
    gen.mkdir(parents=True, exist_ok=True)
    index = []
    for d in docs:
        index.extend(search_entries(d))
    (gen / "raw.json").write_text(json.dumps({d.slug: raw_md(d) for d in docs}, ensure_ascii=False))
    (gen / "search.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    pub = web / "public"
    pub.mkdir(parents=True, exist_ok=True)
    readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
    (pub / "llms.txt").write_text(llms_index(docs, site, md="docs/md"))
    (pub / "llms-full.txt").write_text(llms_full(docs, readme))
    return warnings

# ---------------------------------------------------------------- main

def build(src: Path, out: Path, base: str, site: str, landing: Path | None) -> list[str]:
    docs = load_docs(src)
    if not docs:
        sys.exit(f"no chapters in {src}")
    warnings = []
    slugs = {d.slug for d in docs}
    for d in docs:
        ctx = Ctx(base)
        d.html = render_blocks(d.body.split("\n"), ctx)
        d.heads = ctx.heads
        if "—" in d.body:
            warnings.append(f"{d.file.name}: contains an em dash")
    anchors = {d.slug: {hid for _, _, hid in d.heads} | set(re.findall(r'id="([^"]+)"', d.html)) for d in docs}
    for d in docs:
        for m in re.finditer(r"\]\(/docs/([^)#]*)(?:#([^)]+))?\)", d.body):
            s, a = m.group(1).strip("/").removesuffix(".md"), m.group(2)
            if s and s not in slugs:
                warnings.append(f"{d.file.name}: link to unknown page /docs/{s}")
            elif s and a and a not in anchors.get(s, set()):
                warnings.append(f"{d.file.name}: link to missing anchor /docs/{s}#{a}")
    marks = landing_marks(landing)
    css = (ASSETS / "docs.css").read_text().replace("__FONT__", "__FONTURL__")
    css += landing_tokens(landing)
    js = (ASSETS / "docs.js").read_text()
    v = hashlib.sha256((css + js).encode()).hexdigest()[:10]
    cfg = {"base": base, "marks": marks, "favicon": favicon(marks), "v": v}

    dd = out / "docs"
    (dd / "_").mkdir(parents=True, exist_ok=True)
    (dd / "_" / "docs.css").write_text(css.replace("__FONTURL__", f"{base}fonts/geist-mono-var.ttf"))
    (dd / "_" / "docs.js").write_text(js)
    (dd / "index.html").write_text(overview_page(docs, cfg))
    index = []
    for d in docs:
        (dd / d.slug).mkdir(exist_ok=True)
        (dd / d.slug / "index.html").write_text(chapter_page(d, docs, cfg))
        (dd / f"{d.slug}.md").write_text(raw_md(d))
        index.extend(search_entries(d))
    (dd / "_" / "search.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
    (out / "llms.txt").write_text(llms_index(docs, site))
    (out / "llms-full.txt").write_text(llms_full(docs, readme))
    return warnings


def main() -> None:
    ap = argparse.ArgumentParser(description="build kint's docs site from docs/site/*.md")
    ap.add_argument("--src", default=str(ROOT / "docs" / "site"))
    ap.add_argument("--out", required=True, help="site root; the docs land in <out>/docs/, llms*.txt in <out>/")
    ap.add_argument("--base", default="/", help="URL path of the site root (default /)")
    ap.add_argument("--site", default=SITE, help="absolute origin used in llms.txt (default: SITE in this file)")
    ap.add_argument("--next", action="store_true", help="write a Next.js route into <out>/app/docs and public files into <out>/public")
    ap.add_argument("--landing", default=str(ROOT / "design" / "mocks" / "index.html"),
                    help="the landing page whose tokens and marks the docs follow (skipped if missing)")
    ap.add_argument("--fonts-from", help="copy geist-mono-var.ttf from this directory into <out>/fonts/ (previews)")
    a = ap.parse_args()
    out = Path(a.out)
    base = a.base if a.base.endswith("/") else a.base + "/"
    if a.next:
        for w in build_next(Path(a.src), out, a.site.rstrip("/")):
            print("warning:", w, file=sys.stderr)
        print(f"wrote the Next route into {out / 'app' / 'docs'} and public files into {out / 'public'}")
        return
    warnings = build(Path(a.src), out, base, a.site.rstrip("/"), Path(a.landing) if a.landing else None)
    if a.fonts_from:
        (out / "fonts").mkdir(parents=True, exist_ok=True)
        shutil.copy(Path(a.fonts_from) / "geist-mono-var.ttf", out / "fonts" / "geist-mono-var.ttf")
    for w in warnings:
        print("warning:", w, file=sys.stderr)
    print(f"built {len(load_docs(Path(a.src)))} chapters into {out / 'docs'}")


if __name__ == "__main__":
    main()
