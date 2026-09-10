"use client";
import How from "./How";
import Receipt from "./Receipt";
import Sibyl from "./Sibyl";
import Start from "./Start";

/* The deck: each lower section is a full-height card that rides over the last. The beat adds body.stacked
   on desktop with motion allowed; otherwise these are plain sections in flow. */
export default function Deck() {
  return (
    <div className="deck">
      <How />
      <Receipt />
      <Sibyl />
      <Start />
    </div>
  );
}
