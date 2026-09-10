"use client";
import { useEffect } from "react";
import Hero from "./Hero";
import Flyer from "./Flyer";
import Spot from "./Spot";
import Deck from "./Deck";
import Footer from "./Footer";
import { initLanding } from "@/lib/landing/beat";
import "@/styles/landing.css";

export default function Landing() {
  useEffect(() => initLanding(), []);

  return (
    <>
      <Hero />
      <Flyer />
      <main id="main">
        <Spot />
        <Deck />
      </main>
      <Footer />
    </>
  );
}
