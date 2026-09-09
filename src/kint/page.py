"""The loopback authorize page for smart-account owners (Base Account / Coinbase Smart Wallet).

`kint authorize page` starts a one-shot HTTP server on 127.0.0.1 with a random port and a
session token in the URL, serves ONE self-contained page, and waits. The page loads the Base
Account SDK, connects the owner's account (keys.coinbase.com popup, email code or passkey),
checks the address against the expected owner, and sends `setSessionKey(key, expiry)` to
EpochAnchor FROM the account (that first transaction also deploys a counterfactual account).
The page posts the result back; kint then polls `canWrite(owner, key)` on the chain.

Nothing secret crosses this page: no derive signature, no passphrase, no keys. The vault key
for a smart-account owner is a passphrase typed in the terminal (`kint connect --smart-account`).

Hardening: random port, 32-byte token in the path, Origin and Sec-Fetch-Site checks on the POST,
the server exits after one result or a timeout, and it binds loopback only.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from eth_utils import to_checksum_address

PAGE = r"""<!doctype html>
<meta charset="utf-8">
<title>kint: authorize this machine</title>
<style>
  :root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }
  body { max-width: 40rem; margin: 3rem auto; padding: 0 1rem; line-height: 1.5; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em; }
  button { font: inherit; padding: .6rem 1.1rem; border-radius: .5rem; border: 1px solid #8884; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  .box { border: 1px solid #8884; border-radius: .6rem; padding: 1rem; margin: 1rem 0; }
  .ok { color: #178a3a; } .bad { color: #c2261f; } .muted { opacity: .7; }
</style>
<h1>kint</h1>
<p>Authorize <strong>this machine's session key</strong> to append memory epochs under your Base Account.
The account sends one transaction (<code>setSessionKey</code>) to EpochAnchor on Base. If the account has never
sent a transaction, this one also deploys it.</p>
<div class="box">
  <div>Owner expected: <code id="owner">__OWNER__</code></div>
  <div>Session key: <code id="key">__KEY__</code></div>
  <div>Expiry: <code id="expiry">__EXPIRY_HUMAN__</code></div>
  <div>Contract: <code id="contract">__CONTRACT__</code> (Base, chain 8453)</div>
</div>
<p><button id="connect">1. Connect Base Account</button>
   <button id="send" disabled>2. Authorize (send setSessionKey)</button></p>
<pre id="log" class="muted"></pre>
<script type="module">
import { createBaseAccountSDK } from "https://esm.sh/@base-org/account@2.5.10";
const OWNER = "__OWNER__", KEY = "__KEY__", EXPIRY = __EXPIRY__, CONTRACT = "__CONTRACT__", TOKEN = "__TOKEN__";
const logEl = document.getElementById("log");
const log = (m, cls) => { const d = document.createElement("div"); d.textContent = m; if (cls) d.className = cls; logEl.appendChild(d); };
const sdk = createBaseAccountSDK({ appName: "kint", appChainIds: [8453] });
const provider = sdk.getProvider();
let from = null;
function calldata() {
  // setSessionKey(address,uint64) selector + abi-encoded args
  const sel = "__SELECTOR__";
  const a = KEY.toLowerCase().replace("0x", "").padStart(64, "0");
  const e = BigInt(EXPIRY).toString(16).padStart(64, "0");
  return "0x" + sel + a + e;
}
async function post(body) {
  const r = await fetch("/kint/result/" + TOKEN, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  return r.ok;
}
document.getElementById("connect").onclick = async () => {
  try {
    const accounts = await provider.request({ method: "eth_requestAccounts" });
    from = accounts[0];
    log("connected " + from);
    if (from.toLowerCase() !== OWNER.toLowerCase()) { log("this is not the expected owner; refusing", "bad"); return; }
    try { await provider.request({ method: "wallet_switchEthereumChain", params: [{ chainId: "0x2105" }] }); } catch (e) { log("chain switch: " + (e.message || e)); }
    document.getElementById("send").disabled = false;
    log("ready to authorize", "ok");
  } catch (e) { log("connect failed: " + (e.message || e), "bad"); }
};
document.getElementById("send").onclick = async () => {
  document.getElementById("send").disabled = true;
  try {
    let result;
    try {
      result = await provider.request({ method: "wallet_sendCalls", params: [{ version: "2.0.0", chainId: "0x2105", from, atomicRequired: true, calls: [{ to: CONTRACT, data: calldata(), value: "0x0" }] }] });
      log("sendCalls id " + JSON.stringify(result));
    } catch (e) {
      log("wallet_sendCalls failed (" + (e.message || e) + "), trying eth_sendTransaction");
      result = await provider.request({ method: "eth_sendTransaction", params: [{ from, to: CONTRACT, data: calldata(), value: "0x0" }] });
      log("tx " + result);
    }
    await post({ ok: true, owner: from, result });
    log("done. Back to the terminal: kint is polling the chain for the authorization.", "ok");
  } catch (e) {
    log("authorize failed: " + (e.message || e), "bad");
    await post({ ok: false, owner: from, error: String(e.message || e) });
  }
};
</script>
"""


def _selector() -> str:
    from eth_utils import keccak
    return keccak(text="setSessionKey(address,uint64)").hex()[:8]


class _Handler(BaseHTTPRequestHandler):
    server_version = "kint/0.1"

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        srv: _Server = self.server  # type: ignore[assignment]
        if self.path != f"/kint/{srv.token}":
            self.send_response(404); self.end_headers(); return
        body = srv.page.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("referrer-policy", "no-referrer")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        srv: _Server = self.server  # type: ignore[assignment]
        origin = self.headers.get("Origin", "")
        sfs = self.headers.get("Sec-Fetch-Site", "")
        if self.path != f"/kint/result/{srv.token}" or not origin.startswith(f"http://127.0.0.1:{srv.server_port}") \
                or sfs not in ("same-origin", ""):
            self.send_response(403); self.end_headers(); return
        n = int(self.headers.get("content-length", "0"))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            data = {"ok": False, "error": "bad json"}
        srv.result = data
        self.send_response(204); self.end_headers()


class _Server(HTTPServer):
    token: str
    page: str
    result: dict[str, Any] | None = None


def serve_authorize_page(owner: str, key: str, expiry: int, contract: str, timeout: float = 900.0,
                         on_url=print) -> dict[str, Any] | None:
    """Serve the page until the browser posts a result or the timeout passes. Returns the result."""
    token = secrets.token_urlsafe(32)
    srv = _Server(("127.0.0.1", 0), _Handler)
    srv.token = token
    srv.page = (PAGE.replace("__OWNER__", to_checksum_address(owner)).replace("__KEY__", to_checksum_address(key))
                .replace("__EXPIRY_HUMAN__", time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(expiry)))
                .replace("__EXPIRY__", str(int(expiry))).replace("__CONTRACT__", to_checksum_address(contract))
                .replace("__TOKEN__", token).replace("__SELECTOR__", _selector()))
    url = f"http://127.0.0.1:{srv.server_port}/kint/{token}"
    on_url(url)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    deadline = time.time() + timeout
    try:
        while srv.result is None and time.time() < deadline:
            time.sleep(0.3)
        return srv.result
    finally:
        srv.shutdown()
        srv.server_close()
