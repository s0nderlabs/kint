import Link from "next/link";
import { Lockup } from "./Brand";
import ThemeToggle from "./ThemeToggle";

/* Page-agnostic footer, the landing's footer with absolute links. Styles in styles/site.css (loaded by SiteNav). */
export default function SiteFooter() {
  return (
    <footer className="sfoot" id="foot">
      <div className="wrap">
        <div className="sfgrid">
          <div className="sfbrand">
            <Link href="/" aria-label="kint, home" className="sfwm"><Lockup height={22} /></Link>
            <p>Sibyl Memory that outlives the laptop. Wallet-owned, kept on <span className="base" aria-hidden="true"></span>Base, restored on any machine that can sign, verified before the agent acts.</p>
            <p className="sfmono">v0.3.0 &middot; MIT &middot; Python 3.10+</p>
          </div>
          <nav className="sfcol" aria-label="Product"><span className="sfh">Product</span><Link href="/app">App</Link><Link href="/#how">How it works</Link><Link href="/#receipt">Live on Base</Link><Link href="/#sibyl">Under Sibyl</Link><Link href="/#start">Start</Link><a href="/docs/">Docs</a></nav>
          <nav className="sfcol" aria-label="Source"><span className="sfh">Source</span><a href="https://github.com/s0nderlabs/kint" rel="noopener">GitHub</a><a href="https://github.com/s0nderlabs/kint#readme" rel="noopener">README</a><a href="https://github.com/s0nderlabs/kint/blob/main/docs/judge.md" rel="noopener">For judges</a></nav>
          <nav className="sfcol" aria-label="Chain"><span className="sfh">Chain</span><a href="https://basescan.org/address/0xa22E03f7a4145Bf4909a83595C90a38E14d79600" rel="noopener">EpochAnchor on Basescan</a><a href="https://basescan.org/tx/0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729" rel="noopener">Epoch 2, block 51,081,880</a><a href="https://github.com/s0nderlabs/kint/tree/main/contracts" rel="noopener">Contract source</a></nav>
        </div>
        <div className="sfbar"><span>s0nderlabs</span><span className="sflinks"><a href="#top">Top</a><ThemeToggle className="snav-toggle" /></span></div>
      </div>
    </footer>
  );
}
