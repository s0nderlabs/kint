import Link from "next/link";
import { Lockup } from "./Brand";
import ThemeToggle from "./ThemeToggle";
import "@/styles/site.css";

export default function SiteNav() {
  return (
    <nav className="snav" aria-label="Site">
      <Link href="/" className="snav-wm" aria-label="kint, home"><Lockup height={24} /></Link>
      <div className="snav-links">
        <Link href="/app">App</Link>
        <Link href="/#start">Start</Link>
        <a href="/docs/">Docs</a>
        <a href="https://github.com/s0nderlabs/kint" rel="noopener">GitHub</a>
        <ThemeToggle className="snav-toggle" />
      </div>
    </nav>
  );
}
