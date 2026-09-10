// The docs shell: the site nav in a sticky bar, the page, the site footer, one search dialog. Owned by the docs
// session; generated into web/app/docs/ by scripts/build_docs.py --next web (edit scripts/docs_next/, not the copy).
import type { Metadata } from "next";
import SiteNav from "@/components/site/SiteNav";
import SiteFooter from "@/components/site/SiteFooter";
import DocsClient from "./DocsClient";
import "./docs.css";

export const metadata: Metadata = {
  title: { default: "kint docs", template: "%s · kint docs" },
  description: "How kint works, from install to refusal: every step, mechanism, command, tool and setting.",
};

const LENS = (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
    <circle cx="7" cy="7" r="4.75" /><path d="M10.5 10.5 14 14" />
  </svg>
);

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="kdocs" id="kdocs">
      <div className="dbar"><SiteNav /></div>
      {children}
      <SiteFooter />
      <div className="sd" id="sd" aria-hidden="true">
        <div className="box" role="dialog" aria-modal="true" aria-label="Search the docs">
          <div className="fld">
            {LENS}
            <input id="sin" type="search" placeholder="Search commands, tools, flags, ideas" autoComplete="off" spellCheck={false} aria-controls="sul" />
            <button className="esc" id="sesc" type="button" aria-label="Close search">esc</button>
          </div>
          <ul id="sul" role="listbox"></ul>
        </div>
      </div>
      <DocsClient />
    </div>
  );
}
