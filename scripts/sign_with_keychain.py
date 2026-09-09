#!/usr/bin/env python3
"""Dev helper for this machine only: sign kint's canonical payload with a key held in the
macOS Keychain, in-process, and print the 65-byte hex signature for the connect pipe.

    scripts/sign_with_keychain.py --service dev.deployer --account private-key --owner 0x... \
        | kint connect --owner 0x... --signature -

The key never touches argv or the terminal; only the signature is printed, and only to the
pipe. A Ledger or MetaMask user does the same with `cast wallet sign --data --from-file`.
"""

import argparse
import subprocess
import sys

from eth_account import Account
from eth_account.messages import encode_typed_data

from kint import crypto


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--service", required=True)
    p.add_argument("--account", default="private-key")
    p.add_argument("--owner", help="expected owner address (refuses if the key does not match)")
    p.add_argument("--typed-data-file", help="sign this typed-data JSON instead of the vault payload")
    a = p.parse_args()
    out = subprocess.run(["security", "find-generic-password", "-s", a.service, "-a", a.account, "-w"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"keychain item {a.service}/{a.account} not found")
    key = out.stdout.strip()
    acct = Account.from_key(key)
    if a.owner and acct.address.lower() != a.owner.lower():
        sys.exit(f"key in {a.service} is {acct.address}, not {a.owner}")
    if a.typed_data_file:
        import json
        td = json.load(open(a.typed_data_file))
    else:
        td = crypto.typed_data(acct.address)
    sig = acct.sign_message(encode_typed_data(full_message=td)).signature
    sys.stdout.write("0x" + bytes(sig).hex() + "\n")


if __name__ == "__main__":
    main()
