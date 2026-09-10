"use client";

/* The hero nav. Full bleed: the mark sits on the cave rock at every width, so it stays paper. */
export default function Nav() {
  return (
    <nav className="nav" aria-label="Primary">
      <a className="wm" href="#" aria-label="kint"><svg viewBox="0 -1 80 29" aria-hidden="true" focusable="false"><use href="#lockh" /></svg></a>
      <a className="link" href="/app">App</a>
      <a className="link" href="#start">Start</a>
      <a className="link" href="/docs/">Docs</a>
      <a className="link" href="https://github.com/s0nderlabs/kint">GitHub</a>
      <button className="toggle" id="themeToggle" type="button" aria-label="Toggle theme"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" focusable="false"><rect x="0.5" y="0.5" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1"></rect><path d="M7 0.5 H13.5 V13.5 H7 Z" fill="currentColor"></path></svg></button>
    </nav>
  );
}
