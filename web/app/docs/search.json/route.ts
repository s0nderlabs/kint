// /docs/search.json: every h2/h3 section of every chapter, for the docs search. Static at build time.
import search from "../_gen/search.json";

export const dynamic = "force-static";

export function GET() {
  return Response.json(search);
}
