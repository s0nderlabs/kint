"use client";

/* Five minutes, once per machine. The terminal types a first session when it scrolls in; any command line replays. */
export default function Start() {
  return (
    <section className="section" id="start" aria-labelledby="st-h">
      <div className="wrap">
        <h2 className="sh rv" id="st-h">Five minutes, once per machine.</h2>
        <div className="bento">
          <div className="bx t1 c8 hold rv"><div className="surf app cc term" id="term"><div className="ui">
            <button type="button" className="replay" id="replay" aria-label="Replay the session"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9" /><path d="M13.5 2.5v3h-3" /></svg></button>
            <pre className="tty" id="tty" aria-live="polite" aria-label="A wiped machine joining its memory, typed out"></pre>
          </div></div></div>
          <div className="bx t2 c4 prose rv">
            <p>Base Account owners type a vault passphrase and approve one transaction from a loopback page. Hardware-wallet owners sign once through cast instead. Either way, a few cents of ETH on this machine's session key pays for every push, and every harness you run starts kint-server in place of Sibyl's.</p>
            <ul className="harness" aria-label="Harnesses">
              <li>Claude Code<span>kint setup claude</span></li>
              <li>Codex<span>kint setup codex</span></li>
              <li>Hermes<span>kint setup hermes</span></li>
              <li>OpenClaw<span>kint setup openclaw</span></li>
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
