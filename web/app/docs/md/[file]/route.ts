// /docs/md/<slug>.md: each chapter as raw markdown, for agents (llms.txt links here). Static at build time.
// Served by a route handler, not from public/docs/, because a public directory named like a route makes the
// route 404 in development.
import raw from "../../_gen/raw.json";

export const dynamic = "force-static";
export const dynamicParams = false;

const RAW = raw as Record<string, string>;

export function generateStaticParams() {
  return Object.keys(RAW).map((slug) => ({ file: `${slug}.md` }));
}

export async function GET(_req: Request, { params }: { params: Promise<{ file: string }> }) {
  const { file } = await params;
  const body = RAW[file.replace(/\.md$/, "")];
  if (!body) return new Response("not found\n", { status: 404, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  return new Response(body, { headers: { "Content-Type": "text/markdown; charset=utf-8" } });
}
