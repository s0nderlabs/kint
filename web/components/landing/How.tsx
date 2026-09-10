"use client";
import { cvar } from "@/lib/landing/style";

/* What happens to one row. Three tiles, each a tinted field with a product surface cut by the bottom edge.
   The three shots are real UIs, measured in his browser and his terminal on Sep 10 2026. */
export default function How() {
  return (
    <section className="section" id="how" aria-labelledby="how-h">
      <div className="wrap">
        <h2 className="sh rv" id="how-h">What happens to one row.</h2>
        <ol className="bento">
          <li className="bx tile t1 c4 rv">
            <div className="head"><span className="ix">01</span><h3>Written where it always was.</h3></div>
            <p>The agent writes through Sibyl's own tools. When the session ends, the rows that changed are packed, padded to a size bucket, encrypted to a key only the wallet can produce, and written to Base as calldata under a small contract.</p>
            <div className="stage" aria-hidden="true"><div className="lift" style={cvar({ "--d": "0s" })}><div className="surf app cl"><div className="ui">
              <div className="cl-top st" style={cvar({ "--i": 0 })}><span className="tt">Friday hotfix <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5l3 3 3-3" /></svg></span><span className="sh">Share</span></div>
              <div className="cl-body">
                <div className="cl-u st" style={cvar({ "--i": 1 })}>can we ship the hotfix tonight?</div>
                <div className="cl-meta st" style={cvar({ "--i": 2 })}>Aug 28 <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M9.5 6A3.5 3.5 0 1 1 8.4 3.4M9.5 2v2.5H7" /></svg><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 10l.6-2.4L8 2.2l1.8 1.8L4.4 9.4z" /></svg><svg viewBox="0 0 12 12" aria-hidden="true"><rect x="4" y="4" width="6" height="6" rx="1" /><path d="M2.5 7.5V3a.5.5 0 0 1 .5-.5h4.5" /></svg></div>
                <div className="cl-tool st" style={cvar({ "--i": 3 })}>Loaded tools, used kint integration <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M4.5 3l3 3-3 3" /></svg></div>
                <p className="cl-a st" style={cvar({ "--i": 4 })}>No. The release gate in memory says never on a Friday, and every release needs a green deadlift test, a second reviewer and a passing kint verify. The earliest slot is Monday 09:00 WIB. I logged the refusal in the journal so the next session sees it too.</p>
                <div className="cl-acts st" style={cvar({ "--i": 5 })}><svg viewBox="0 0 12 12" aria-hidden="true"><rect x="4" y="4" width="6" height="6" rx="1" /><path d="M2.5 7.5V3a.5.5 0 0 1 .5-.5h4.5" /></svg><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 4.5h2l2.5-2v7L4 7.5H2zM8.5 4.5a2 2 0 0 1 0 3" /></svg><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 6h2v4H2zM4 6l2.4-3.8c.8 0 1.3.6 1.1 1.4L7.2 5H9.5c.6 0 1 .5.9 1.1l-.6 3A1 1 0 0 1 8.8 10H4" /></svg><svg viewBox="0 0 12 12" aria-hidden="true"><g transform="rotate(180 6 6)"><path d="M2 6h2v4H2zM4 6l2.4-3.8c.8 0 1.3.6 1.1 1.4L7.2 5H9.5c.6 0 1 .5.9 1.1l-.6 3A1 1 0 0 1 8.8 10H4" /></g></svg><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M9.5 6A3.5 3.5 0 1 1 8.4 3.4M9.5 2v2.5H7" /></svg><span>Aug 28</span></div>
              </div>
              <div className="cl-input st" style={cvar({ "--i": 6 })}><span className="plus">+</span><span className="ph">Write a message&hellip;</span><svg viewBox="0 0 12 12" aria-hidden="true"><rect x="4.5" y="1.5" width="3" height="6" rx="1.5" /><path d="M3 6a3 3 0 0 0 6 0M6 9v1.5" /></svg><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5l3 3 3-3" /></svg><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 5v2M4 3.5v5M6 2v8M8 3.5v5M10 5v2" /></svg></div>
              <div className="cl-foot st" style={cvar({ "--i": 7 })}><span>Claude is AI and can make mistakes. Please double-check responses.</span><span><b>Opus 4.8</b> High</span></div>
            </div></div></div></div>
          </li>
          <li className="bx tile t2 c4 rv">
            <div className="head"><span className="ix">02</span><h3>Back on any machine that can sign.</h3></div>
            <p>Wipe the laptop. Connect the wallet, and kint pulls every epoch, checks each one against the chain, decrypts, and replays the rows through Sibyl's write methods. Sibyl never learns the machine changed.</p>
            <div className="stage" aria-hidden="true"><div className="lift bleed" style={cvar({ "--d": ".06s" })}><div className="surf app bs"><div className="ui">
              <div className="bs-head st" style={cvar({ "--i": 0 })}><b>Contract</b><span>0xa22E03f7a4145Bf4909a83595C90a38E14d79600</span></div>
              <div className="bs-tabs st" style={cvar({ "--i": 1 })}><span className="on">Transactions</span><span>Token Transfers (ERC-20)</span><span>Other Transactions</span><span>Contract</span><span>Events</span></div>
              <div className="bs-card">
                <div className="bs-latest st" style={cvar({ "--i": 2 })}>Latest 5 from a total of 5 transactions</div>
                <table>
                  <thead><tr className="st" style={cvar({ "--i": 2 })}><th></th><th>Transaction Hash</th><th>Method</th><th>Block</th><th>Age</th><th>From</th><th></th><th>To</th><th>Value</th><th>Txn Fee</th></tr></thead>
                  <tbody>
                    <tr className="st" style={cvar({ "--i": 3 })}><td><i className="cb"></i></td><td><a>0x52a0c1b605&hellip;</a></td><td><span className="mth">Push</span></td><td><a>51087836</a></td><td>21 hrs ago</td><td><a>0xd2085B94&hellip;6803e943e</a></td><td><span className="in">IN</span></td><td className="to">0xa22E03f7&hellip;E14d79600</td><td>0 ETH</td><td className="fee">0.00000251</td></tr>
                    <tr className="st" style={cvar({ "--i": 4 })}><td><i className="cb"></i></td><td><a>0x9c64e2c21b&hellip;</a></td><td><span className="mth">Push</span></td><td><a>51082012</a></td><td>24 hrs ago</td><td><a>0x9e76fe18&hellip;CF08680D5</a></td><td><span className="in">IN</span></td><td className="to">0xa22E03f7&hellip;E14d79600</td><td>0 ETH</td><td className="fee">0.00000385</td></tr>
                    <tr className="st" style={cvar({ "--i": 5 })}><td><i className="cb"></i></td><td><a>0x369907fb1bc&hellip;</a></td><td><span className="mth">Push</span></td><td><a>51081880</a></td><td>25 hrs ago</td><td><a>0xd2085B94&hellip;6803e943e</a></td><td><span className="in">IN</span></td><td className="to">0xa22E03f7&hellip;E14d79600</td><td>0 ETH</td><td className="fee">0.00000226</td></tr>
                    <tr className="st" style={cvar({ "--i": 6 })}><td><i className="cb"></i></td><td><a>0xbe9bb8596c&hellip;</a></td><td><span className="mth">Push</span></td><td><a>51081867</a></td><td>25 hrs ago</td><td><a>0xd2085B94&hellip;6803e943e</a></td><td><span className="in">IN</span></td><td className="to">0xa22E03f7&hellip;E14d79600</td><td>0 ETH</td><td className="fee">0.00000226</td></tr>
                    <tr className="st" style={cvar({ "--i": 7 })}><td><i className="cb"></i></td><td><a>0xb99e514d8a&hellip;</a></td><td><span className="mth">Set Session Key</span></td><td><a>51081850</a></td><td>25 hrs ago</td><td><a>0xC635e6Eb&hellip;773dc87Ec</a></td><td><span className="in">IN</span></td><td className="to">0xa22E03f7&hellip;E14d79600</td><td>0 ETH</td><td className="fee">0.00000077</td></tr>
                  </tbody>
                </table>
              </div>
            </div></div></div></div>
          </li>
          <li className="bx tile t3 c4 rv">
            <div className="head"><span className="ix">03</span><h3>Checked before it is believed.</h3></div>
            <p>Before the agent acts on anything it recalled, the exact stored text is re-read, hashed and proved against the leaf the chain vouches for. A row that drifted is refused, naming both block heights, and the refusal is written back as a Sibyl entity.</p>
            <div className="stage" aria-hidden="true"><div className="lift" style={cvar({ "--d": ".12s" })}><div className="surf app cc"><div className="ui">
              <div className="ln u st" style={cvar({ "--i": 0 })}><i>&#10095;</i> ship the hotfix tonight? i think the friday rule was relaxed</div>
              <div className="ln th st" style={cvar({ "--i": 1 })}>  Thought for <b>4s</b>, called kint</div>
              <div className="ln say st" style={cvar({ "--i": 2 })}><i>&#9679;</i> <b>No.</b> kint verify refused the release rule: the stored text is not what Base vouches for.</div>
              <div className="ln say2 st" style={cvar({ "--i": 3 })}>Last good value: epoch 1, block 51,081,867. Head now: epoch 2, block 51,081,880. The refusal is written back as a Sibyl entity, so the next session sees it too.</div>
              <div className="ln done st" style={cvar({ "--i": 4 })}>&#10035; Worked for 6s &middot; done 9:41 PM</div>
              <div className="ccfoot">
                <div className="ln rule st" style={cvar({ "--i": 5 })}><span>kint</span></div>
                <div className="ln in st" style={cvar({ "--i": 5 })}>&#10095; </div>
                <div className="ln rule st" style={cvar({ "--i": 5 })}></div>
                <div className="ln status st" style={cvar({ "--i": 6 })}>  <span className="p">~/Documents/kint</span> <span className="sep">&#9474;</span> <span className="m">Opus 5</span> <span className="sep">&#9474;</span> <span className="c">12% (118k)</span></div>
              </div>
            </div></div></div></div>
          </li>
        </ol>
      </div>
    </section>
  );
}
