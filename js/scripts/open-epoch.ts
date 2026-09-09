#!/usr/bin/env bun
/**
 * Open one Python-sealed epoch with the TypeScript path and print its plaintext.
 *
 * This is the cross-language check the verifier runs: kint seals an epoch in
 * Python, this opens it in JavaScript, and the bytes have to be identical.
 *
 * It goes through readEpoch, not openEpoch, so the header has to agree with the
 * plaintext it travelled in. FLAG_SNAPSHOT is not covered by the AAD: a blob
 * with that bit flipped still decrypts, and a script that only printed the flag
 * would report the forgery as fact and exit 0. A disagreement exits non-zero
 * naming the field.
 *
 *   KINT_DEK=<64 hex chars> bun run scripts/open-epoch.ts <blob> \
 *       --owner 0x... --tenant demo [--seq 1] [--prev <64 hex chars>]
 *
 * The DEK comes from the environment, never from argv: a process list is public
 * on a shared machine. Pass --space <hex> instead of --tenant when the caller
 * already has the 32-byte space id.
 */

import {
  fromHex,
  isSnapshotHeader,
  parseHeader,
  readEpoch,
  spaceId,
  toHex,
  utf8String,
} from '../src/index.js';

const USAGE = `usage: KINT_DEK=<hex> bun run scripts/open-epoch.ts <blob-file>
              --owner <0x address>
              (--tenant <name> | --space <64 hex chars>)
              [--seq <n>] [--prev <64 hex chars>] [--raw]

  --raw  write the plaintext bytes to stdout with no trailing newline
`;

function fail(message: string): never {
  process.stderr.write(`open-epoch: ${message}\n`);
  process.exit(1);
}

function parseArgs(argv: string[]): { positional: string[]; flags: Map<string, string> } {
  const positional: string[] = [];
  const flags = new Map<string, string>();
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a.startsWith('--')) {
      const name = a.slice(2);
      if (name === 'raw' || name === 'help') {
        flags.set(name, '1');
        continue;
      }
      const value = argv[i + 1];
      if (value === undefined) fail(`--${name} needs a value\n\n${USAGE}`);
      flags.set(name, value);
      i++;
    } else {
      positional.push(a);
    }
  }
  return { positional, flags };
}

async function main(): Promise<void> {
  const { positional, flags } = parseArgs(process.argv.slice(2));
  if (flags.has('help')) {
    process.stdout.write(USAGE);
    return;
  }

  const blobPath = flags.get('blob') ?? positional[0];
  if (!blobPath) fail(`no blob file given\n\n${USAGE}`);

  const owner = flags.get('owner');
  if (!owner) fail(`--owner is required\n\n${USAGE}`);

  const tenant = flags.get('tenant');
  const spaceHex = flags.get('space');
  if (!tenant && !spaceHex) fail(`one of --tenant or --space is required\n\n${USAGE}`);
  const space = spaceHex ? fromHex(spaceHex) : spaceId(tenant!);
  if (space.length !== 32) fail(`--space must be 32 bytes, got ${space.length}`);

  const dekHex = process.env.KINT_DEK;
  if (!dekHex) fail('set KINT_DEK to the 32-byte data key in hex (never pass it on argv)');
  const dek = fromHex(dekHex);
  if (dek.length !== 32) fail(`KINT_DEK must be 32 bytes, got ${dek.length}`);

  const seq = Number(flags.get('seq') ?? '1');
  if (!Number.isInteger(seq) || seq < 1) fail(`--seq must be a positive integer, got ${seq}`);

  const prev = fromHex(flags.get('prev') ?? '00'.repeat(32));
  if (prev.length !== 32) fail(`--prev must be 32 bytes, got ${prev.length}`);

  const file = Bun.file(blobPath);
  if (!(await file.exists())) fail(`no such file: ${blobPath}`);
  const blob = new Uint8Array(await file.arrayBuffer());

  // print the header before anything can refuse, so a refusal still says what it saw
  const { header } = parseHeader(blob);
  process.stderr.write(
    [
      `blob        ${blob.length} bytes`,
      `version     ${header.version}`,
      `flags       0x${header.flags.toString(16).padStart(2, '0')}` +
        (isSnapshotHeader(header) ? ' (snapshot)' : ''),
      `bucket      ${header.bucket}`,
      `dek_id      ${toHex(header.dekId)}`,
      `rows_root   ${toHex(header.rowsRoot)}`,
      `wraps       ${header.wraps.map((w) => `kind=${w.kind} tag=${toHex(w.tag)}`).join(', ')}`,
      '',
    ].join('\n'),
  );

  // readEpoch = openEpoch + parsePlaintext + assertEpochConsistent. It throws on a
  // seq, space, prev, rows_root or snapshot-flag disagreement, and main's catch
  // turns that into exit 1.
  const { doc, plaintext } = await readEpoch(blob, { dek, owner, space, seq, prev });

  process.stderr.write(
    [
      `plaintext   v${doc.v} seq=${doc.seq} rows=${doc.rows.length} deleted=${doc.deleted.length} n_rows=${doc.n_rows} snapshot=${doc.snapshot}`,
      'consistent  seq, space, prev, rows_root and the snapshot flag all agree with the header',
      '',
    ].join('\n'),
  );

  if (flags.has('raw')) {
    process.stdout.write(plaintext);
  } else {
    process.stdout.write(`${utf8String(plaintext)}\n`);
  }
}

try {
  await main();
} catch (e) {
  // a refusal is the normal outcome of a wrong key or a wrong seq; say so plainly
  fail((e as Error).message || String(e));
}
