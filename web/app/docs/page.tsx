import Link from "next/link";
import Sidebar, { MenuButton } from "./Sidebar";
import { content, docs } from "./lib";

export default function DocsOverview() {
  return (
    <div className="shell ov">
      <MenuButton title="Chapters" />
      <Sidebar active={null} />
      <main className="doc" id="main">
        <div className="intro">
          <h1>How kint works, from install to refusal.</h1>
          <p>Install it once per machine, connect the wallet, and every harness you run reads Sibyl Memory through kint-server. These pages cover each step, each mechanism, and every command, tool and setting, read from the code at v0.3.0.</p>
          <div dangerouslySetInnerHTML={{ __html: content.installHtml }} />
          <Link className="go" href="/docs/quickstart">Read the quickstart &rarr;</Link>
        </div>
        <ul className="bento">
          {content.overview.map((cell, ci) => {
            const groups = cell.groups.map((g) => ({ g, items: docs.filter((d) => d.group === g) })).filter((x) => x.items.length > 0);
            if (!groups.length) return null;
            return (
              <li key={ci} className={`bx ${cell.tint} ${cell.span}`}>
                {groups.map(({ g, items }, k) => (
                  <div key={g}>
                    <h2 className={k ? "gsep" : undefined}>{g}</h2>
                    <ul style={{ ["--cols" as string]: String(cell.cols) }}>
                      {items.map((d) => (
                        <li key={d.slug}>
                          <Link href={`/docs/${d.slug}`}>
                            <span className="t">{d.title}<i aria-hidden="true">&rarr;</i></span>
                            <span className="d">{d.description}</span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </li>
            );
          })}
        </ul>
        <div className="more">
          <p>The README is the GitHub side of these pages, and every page names the source files it explains. Agents can read any page as markdown, or all of it at once.</p>
          <div className="links">
            <a href={`${content.repo}#readme`}>README</a>
            <a href={`${content.repo}/blob/main/CHANGELOG.md`}>Changelog</a>
            <a href={`${content.repo}/blob/main/docs/judge.md`}>Claims table</a>
            <a href="/llms.txt">llms.txt</a>
            <a href="/llms-full.txt">llms-full.txt</a>
          </div>
        </div>
      </main>
    </div>
  );
}
