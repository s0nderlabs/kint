"use client";

export default function Footer() {
  return (
    <footer className="foot" id="foot">
      <div className="wrap">
        <div className="fgrid">
          <div className="fbrand">
            <svg className="fwm" viewBox="0 -1 80 29" role="img" aria-label="kint"><use href="#lockh" /></svg>
            <p>Sibyl Memory that outlives the laptop. Wallet-owned, kept on <span className="base" aria-hidden="true"></span>Base, restored on any machine that can sign, verified before the agent acts.</p>
            <p className="fmono">v0.3.0 &middot; MIT &middot; Python 3.10+</p>
          </div>
          <nav className="fcol" aria-label="Product"><span className="fh">Product</span><a href="/app">App</a><a href="#how">How it works</a><a href="#receipt">Live on Base</a><a href="#sibyl">Under Sibyl</a><a href="#start">Start</a><a href="/docs/">Docs</a></nav>
          <nav className="fcol" aria-label="Source"><span className="fh">Source</span><a href="https://github.com/s0nderlabs/kint">GitHub</a><a href="https://github.com/s0nderlabs/kint#readme">README</a><a href="https://github.com/s0nderlabs/kint/blob/main/docs/judge.md">Claims a judge can check</a><a href="https://github.com/s0nderlabs/kint/releases/tag/v0.3.0">Release v0.3.0</a></nav>
          <nav className="fcol" aria-label="Chain"><span className="fh">Chain</span><a href="https://basescan.org/address/0xa22E03f7a4145Bf4909a83595C90a38E14d79600">EpochAnchor on Basescan</a><a href="https://basescan.org/tx/0xbe9bb8596c825a8891c3eafe4381e0c6522d647641735c635ca58fcf4bbe4455">Epoch 1, block 51,081,867</a><a href="https://basescan.org/tx/0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729">Epoch 2, block 51,081,880</a><a href="https://github.com/Sibyl-Labs/Sibyl-Memory">Sibyl Memory</a></nav>
        </div>
        <div className="fbar"><span>s0nderlabs</span><span className="flinks"><a href="#hero">Top</a><button className="toggle ftoggle" type="button" aria-label="Toggle theme"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" focusable="false"><rect x="0.5" y="0.5" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1"></rect><path d="M7 0.5 H13.5 V13.5 H7 Z" fill="currentColor"></path></svg></button></span></div>
      </div>
    </footer>
  );
}
