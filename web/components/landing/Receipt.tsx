"use client";
import { cvar } from "@/lib/landing/style";

/* Live on Base mainnet: the receipt is public, the memory is not. Every number here is a real mainnet fact. */
export default function Receipt() {
  return (
    <section className="section" id="receipt" aria-labelledby="rc-h">
      <div className="wrap">
        <h2 className="sh rv" id="rc-h">Live on <span className="base" aria-hidden="true"></span>Base mainnet.</h2>
        <p className="sub rv">The receipt is public. The memory is not: Base holds ciphertext and a digest, padded to a bucket, never a byte of plaintext and never the true length.</p>
        <div className="bento">
          <div className="bx t1 c7 hold rv">
            <div className="rc">
              <div><span className="k">EpochAnchor, verified</span><a className="addr" href="https://basescan.org/address/0xa22E03f7a4145Bf4909a83595C90a38E14d79600">0xa22E03f7a4145Bf4909a83595C90a38E14d79600</a></div>
              <div className="rc-hero"><span className="big">51,081,880</span><span className="under">The block that holds the latest epoch. Epoch 2 carries 15 rows in one 4 KB bucket; digest <code>7df5378a8c4fa866</code>.</span></div>
              <dl className="rc-kv">
                <div><dt>owner</dt><dd>0xC635e6Eb223aE14143E23cEEa9440bC773dc87Ec</dd></div>
                <div><dt>space</dt><dd>bd2a3b5b8f3fb4c8</dd></div>
                <div><dt>network</dt><dd><span className="base" aria-hidden="true"></span>Base, chain 8453</dd></div>
              </dl>
              <div className="rc-cap">
                <div className="bar" aria-hidden="true"><i className="s" style={{ width: "5.86%" }}></i><i className="kk" style={{ width: ".9%" }}></i></div>
                <div className="leg"><span><i className="sw s"></i>Sibyl stores 300.0 KB</span><span><i className="sw kk"></i>kint state 46.2 KB</span><span className="tot">346.2 KB of Sibyl's 5 MB free cap</span></div>
              </div>
            </div>
          </div>
          <div className="bx t2 c5 hold rv"><div className="lift bleed"><div className="surf app bs"><div className="ui">
            <div className="bs-head st" style={cvar({ "--i": 0 })}><b>Transaction Details</b></div>
            <div className="bs-tabs st" style={cvar({ "--i": 0 })}><span className="on">Overview</span><span>Logs (1)</span><span>State</span></div>
            <div className="bs-act st" style={cvar({ "--i": 1 })}><span className="lbl">TRANSACTION ACTION</span>Call <span className="mth">Push</span> Function by <a>0xd2085B94&hellip;6803e943e</a> on <a>0xa22E03f7&hellip;E14d79600</a></div>
            <dl className="bs-rows">
              <div className="bs-r st" style={cvar({ "--i": 2 })}><dt>Transaction Hash:</dt><dd>0x369907fb1bccc3222365b2e07b4d6d831642831d481a5f7cb99357823e2a9729</dd></div>
              <div className="bs-r st" style={cvar({ "--i": 3 })}><dt>Status:</dt><dd><span className="ok">&#10003; Success</span></dd></div>
              <div className="bs-r st" style={cvar({ "--i": 4 })}><dt>Block:</dt><dd><a>51081880</a> <span className="tag">Confirmed by Sequencer</span></dd></div>
              <div className="bs-r st" style={cvar({ "--i": 5 })}><dt>Timestamp:</dt><dd>25 hrs ago <span className="tag">Sep-09-2026 11:25:07 AM +UTC</span></dd></div>
              <div className="bs-r sep st" style={cvar({ "--i": 6 })}><dt>From:</dt><dd><a>0xd2085B94849B2D98333100Fc0005ff96803e943e</a></dd></div>
              <div className="bs-r st" style={cvar({ "--i": 7 })}><dt>To:</dt><dd><a>0xa22E03f7a4145Bf4909a83595C90a38E14d79600</a></dd></div>
              <div className="bs-r sep st" style={cvar({ "--i": 8 })}><dt>Value:</dt><dd>0 ETH <span className="dim">($0.00)</span></dd></div>
              <div className="bs-r st" style={cvar({ "--i": 9 })}><dt>Transaction Fee:</dt><dd>0.00000226833835467 ETH <span className="tag">($0.005472)</span></dd></div>
              <div className="bs-r st" style={cvar({ "--i": 9 })}><dt>Gas Price:</dt><dd>0.011494974 Gwei <span className="dim">(0.000000000011494974 ETH)</span></dd></div>
            </dl>
          </div></div></div></div>
        </div>
      </div>
    </section>
  );
}
