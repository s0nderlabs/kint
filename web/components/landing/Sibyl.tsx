"use client";

/* Built on Sibyl Memory, under it: their eight tools exactly as shipped, six added. */
export default function Sibyl() {
  return (
    <section className="section" id="sibyl" aria-labelledby="sb-h">
      <div className="wrap">
        <h2 className="sh rv" id="sb-h">Built on Sibyl Memory, under it.</h2>
        <div className="bento">
          <div className="bx t1 c5 prose rv">
            <p className="line">Their server, imported untouched. Their eight tools, exactly as shipped. Six added.</p>
            <div>
              <p>The decision beat reaches the row through their search and keys on their typed verdict.</p>
              <p>Delete the Sibyl layer and the epoch is a decrypted blob with no query surface: a fresh session neither refuses nor proceeds. Base holds the ciphertext. Sibyl is what turns it back into an answerable store.</p>
            </div>
          </div>
          <div className="bx t2 c7 rv">
            <table className="tools"><tbody>
              <tr><td>memory_remember</td><td>Store an entity in long-term memory.</td></tr>
              <tr><td>memory_recall</td><td>Read an entity by exact (category, name) lookup.</td></tr>
              <tr><td>memory_search</td><td>Full-text search across all Sibyl tiers: entities, state, reference, journal. Each hit carries its tier.</td></tr>
              <tr><td>memory_list</td><td>List entities, optionally filtered by category, most recently updated first.</td></tr>
              <tr><td>memory_forget</td><td>Archive an entity. Not destroyed: moved to archived_entities.</td></tr>
              <tr><td>memory_set_state</td><td>Write a hot-tier state document.</td></tr>
              <tr><td>memory_get_state</td><td>Read a hot-tier state document by key.</td></tr>
              <tr><td>memory_record_event</td><td>Append a cold-tier journal event. Append-only, never overwrites.</td></tr>
            </tbody><tbody className="k">
              <tr><td>memory_status</td><td>Where this memory lives and whether it is in step with Base.</td></tr>
              <tr><td>memory_connect</td><td>Connect this machine to the wallet-owned vault, or say exactly what a human must do.</td></tr>
              <tr><td>memory_pull</td><td>Restore or refresh this machine's Sibyl store from Base.</td></tr>
              <tr><td>memory_push</td><td>Anchor every unanchored change now.</td></tr>
              <tr><td>memory_verify</td><td>Before acting on something recalled, verify it against Base and get a decision.</td></tr>
              <tr><td>memory_history</td><td>What this row held at every anchored epoch. A temporal read Sibyl cannot do.</td></tr>
            </tbody></table>
          </div>
        </div>
      </div>
    </section>
  );
}
