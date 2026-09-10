"use client";
import Nav from "./Nav";

/* The hero: the image IS the hero, edge to edge. The bottom leaf is missing from both renders on purpose; it
   travels on its own layer (Flyer) from here into the spotlight below. */
export default function Hero() {
  return (
    <header className="hero" id="hero">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="scene day" src="/assets/hero-day-noleaf.png" alt="The Sibyl seated at the mouth of her cave, oak leaves lifting from her hand and thinning out across an open sky." />
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="scene night" src="/assets/hero-night-noleaf.png" alt="" />
      <div className="grain" aria-hidden="true"></div>
      <div className="haze" aria-hidden="true"></div>
      <Nav />
      <div className="stack">
        <h1>Sibyl Memory that <em>outlives</em> the laptop.</h1>
        <p className="lede">Wipe the machine, connect the wallet, and the agent comes back knowing what it knew, and proves it was not tampered with.</p>
        <div className="cta"><a className="pill" href="/app">Open the app</a><a className="readme" href="/docs/">Read the docs</a></div>
      </div>
    </header>
  );
}
