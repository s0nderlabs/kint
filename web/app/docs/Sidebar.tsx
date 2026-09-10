import Link from "next/link";
import { navGroups } from "./lib";

export default function Sidebar({ active }: { active: string | null }) {
  return (
    <nav className="side" id="side" aria-label="Chapters">
      <button className="sbtn" type="button" data-search="" aria-label="Search the docs">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
          <circle cx="7" cy="7" r="4.75" /><path d="M10.5 10.5 14 14" />
        </svg>
        <span className="sl">Search the docs</span><kbd>/</kbd>
      </button>
      <Link href="/docs" aria-current={active === null ? "page" : undefined}>Overview</Link>
      {navGroups().map((g) => (
        <div className="grp" key={g.name}>
          <p className="gh">{g.name}</p>
          {g.items.map((d) => (
            <Link key={d.slug} href={`/docs/${d.slug}`} aria-current={d.slug === active ? "page" : undefined}>{d.title}</Link>
          ))}
        </div>
      ))}
    </nav>
  );
}

export function MenuButton({ title }: { title: string }) {
  return (
    <button className="mnav" id="mnav" type="button" aria-expanded="false" aria-controls="side">
      <span>{title}</span>
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 6l4 4 4-4" /></svg>
    </button>
  );
}
