import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque } from "next/font/google";
import localFont from "next/font/local";
import { BrandDefs } from "@/components/site/Brand";
import "./globals.css";

const display = Bricolage_Grotesque({
  subsets: ["latin"],
  axes: ["opsz"],
  variable: "--font-display",
  display: "swap",
});

const mono = localFont({
  src: "../public/fonts/geist-mono-var.ttf",
  weight: "100 900",
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "kint",
  description: "Sibyl Memory that outlives the laptop. Encrypted to your wallet, kept on Base, restored on any machine you can sign for, verified before the agent acts on it.",
  metadataBase: new URL("https://kint.s0nderlabs.xyz"),
  openGraph: { title: "kint", description: "Sibyl Memory that outlives the laptop.", type: "website" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F4F1EA" },
    { media: "(prefers-color-scheme: dark)", color: "#12110F" },
  ],
};

// Runs before paint: an explicit choice stamps data-theme, the system default stamps nothing.
const THEME_INIT = `(function(){try{var t=localStorage.getItem('kint-theme');if(t==='dark'||t==='light')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>
        <BrandDefs />
        {children}
      </body>
    </html>
  );
}
