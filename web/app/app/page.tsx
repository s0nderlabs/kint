import type { Metadata } from "next";
import SiteNav from "@/components/site/SiteNav";
import SiteFooter from "@/components/site/SiteFooter";
import AppClient from "@/components/app/AppClient";
import "@/styles/app.css";

export const metadata: Metadata = {
  title: "kint app",
  description: "Read a wallet's memory off Base and open it in the browser. Nothing decrypted leaves the page.",
};

export default function AppPage() {
  return (
    <>
      <SiteNav />
      <AppClient />
      <SiteFooter />
    </>
  );
}
