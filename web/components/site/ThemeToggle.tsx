"use client";
import { useEffect, useState } from "react";

type Theme = "system" | "light" | "dark";
const KEY = "kint-theme";
const EVENT = "kint-theme";
const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
const LABEL: Record<Theme, string> = { system: "Auto", light: "Light", dark: "Dark" };

function read(): Theme {
  try {
    const t = localStorage.getItem(KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

function apply(t: Theme) {
  const root = document.documentElement;
  if (t === "system") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", t);
  try { if (t === "system") localStorage.removeItem(KEY); else localStorage.setItem(KEY, t); } catch {}
  window.dispatchEvent(new CustomEvent(EVENT, { detail: t }));
}

/* Every toggle on a page shares one state through a window event, so the nav and the footer relabel together. */
export default function ThemeToggle({ className }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>("system");
  useEffect(() => {
    setTheme(read());
    const onChange = (e: Event) => setTheme((e as CustomEvent<Theme>).detail);
    const onStorage = (e: StorageEvent) => { if (e.key === KEY) setTheme(read()); };
    window.addEventListener(EVENT, onChange);
    window.addEventListener("storage", onStorage);
    return () => { window.removeEventListener(EVENT, onChange); window.removeEventListener("storage", onStorage); };
  }, []);
  return (
    <button type="button" className={className} onClick={() => apply(NEXT[theme])} aria-label={`Theme: ${LABEL[theme]}. Click to change.`}>
      {LABEL[theme]}
    </button>
  );
}
