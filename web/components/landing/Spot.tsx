"use client";

/* The spotlight: the leaf lands here, large, centred, the only thing in the section. */
export default function Spot() {
  return (
    <section className="spot" id="spot" aria-label="One leaf, kept">
      <div className="spot-inner">
        <div className="stage"><div className="slot" id="slot"><div className="vec"><svg><use href="#leafm" /></svg></div></div></div>
        <p className="spot-line">One row. Written on the machine, kept on Base, and back on any machine that can sign for it.</p>
        <div className="spot-more">
          <p className="spot-what">Sibyl Memory decides what a coding agent remembers: five tiers, full-text search, eight tools, one SQLite file on one machine. kint makes that memory the owner's instead of the laptop's. Every change is packed, padded, encrypted to a key only the owner's wallet can produce, and written to Base under a small contract. Nothing decrypted ever leaves the machine.</p>
          <dl className="spot-moves">
            <div><dt>Kept</dt><dd>Each session end, the rows that changed become one encrypted epoch on Base. The chain holds ciphertext and a digest, never a byte of plaintext.</dd></div>
            <div><dt>Restored</dt><dd>On any machine the owner can sign for, kint pulls, verifies every epoch, and replays the rows through Sibyl's own write methods.</dd></div>
            <div><dt>Verified</dt><dd>Before the agent acts on a recalled row, its exact text is proved against the chain. A row that drifted is refused, naming both block heights.</dd></div>
          </dl>
        </div>
      </div>
    </section>
  );
}
