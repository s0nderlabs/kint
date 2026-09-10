import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import Sidebar, { MenuButton } from "../Sidebar";
import { adjacent, content, docs, getDoc } from "../lib";

export const dynamicParams = false;

export function generateStaticParams() {
  return docs.map((d) => ({ slug: d.slug }));
}

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const d = getDoc(slug);
  return d ? { title: d.title, description: d.description, alternates: { types: { "text/markdown": `/docs/md/${d.slug}.md` } } } : {};
}

export default async function DocPage({ params }: Props) {
  const { slug } = await params;
  const d = getDoc(slug);
  if (!d) notFound();
  const { prev, next } = adjacent(d.slug);
  return (
    <div className="shell">
      <MenuButton title={d.title} />
      <Sidebar active={d.slug} />
      <main className="doc" id="main">
        <article dangerouslySetInnerHTML={{ __html: d.html }} />
        <nav className="pager" aria-label="Previous and next">
          {prev && (
            <Link className="prev" href={`/docs/${prev.slug}`}>
              <span className="t"><span className="ar">&larr;</span> {prev.title}</span>
              <span className="d">{prev.description}</span>
            </Link>
          )}
          {next && (
            <Link className="next" href={`/docs/${next.slug}`}>
              <span className="t">{next.title} <span className="ar">&rarr;</span></span>
              <span className="d">{next.description}</span>
            </Link>
          )}
        </nav>
      </main>
      <aside className="toc" aria-label="On this page">
        <nav>
          {d.heads.map((h) => (
            <a key={h.id} className={`h${h.level}`} href={`#${h.id}`}>{h.text}</a>
          ))}
        </nav>
        <div className="meta">
          <a href={`/docs/md/${d.slug}.md`}>Markdown</a>
          <a href={`${content.repo}/edit/main/docs/site/${d.file}`}>Edit on GitHub</a>
        </div>
      </aside>
    </div>
  );
}
