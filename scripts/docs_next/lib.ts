// Generated content, read at build time. content.json is written by scripts/build_docs.py --next web
// from docs/site/*.md; edit the markdown, never this data.
import data from "./content.json";

export type Head = { level: number; text: string; id: string };
export type Doc = {
  slug: string; title: string; description: string; group: string; order: number;
  file: string; source: string; html: string; heads: Head[];
};
export type Cell = { groups: string[]; span: string; tint: string; cols: number };
type Content = { docs: Doc[]; groups: string[]; overview: Cell[]; repo: string; install: string; installHtml: string };

export const content = data as unknown as Content;
export const docs: Doc[] = content.docs;

export function getDoc(slug: string): Doc | null {
  return docs.find((d) => d.slug === slug) ?? null;
}

export function adjacent(slug: string): { prev: Doc | null; next: Doc | null } {
  const i = docs.findIndex((d) => d.slug === slug);
  return { prev: i > 0 ? docs[i - 1] : null, next: i >= 0 && i < docs.length - 1 ? docs[i + 1] : null };
}

export function navGroups(): { name: string; items: Doc[] }[] {
  return content.groups.map((g) => ({ name: g, items: docs.filter((d) => d.group === g) })).filter((g) => g.items.length > 0);
}
