/**
 * The EpochAnchor reads. The walk runs against a fake client that serves
 * getLogs out of a small in-memory table, so nothing here touches a network.
 */

import { describe, expect, test } from 'bun:test';
import { encodeFunctionData, getAddress } from 'viem';
import type { Address, Hex } from 'viem';

import { fromHex, to0x, toHex } from '../src/bytes.js';
import {
  DEFAULT_CONTRACT,
  EPOCH_ANCHOR_ABI,
  assertCiphertextMatchesDigest,
  coldStartEvents,
  decodePushCalldata,
  epochCiphertext,
  isSnapshotEvent,
  readHead,
  readSessionKeyExpiry,
  readStartSeq,
  walkEpochs,
} from '../src/chain.js';
import type { EpochEvent, EpochLog, EpochReadClient } from '../src/chain.js';
import { ciphertextDigest } from '../src/envelope.js';
import { V } from './vectors.js';

const OWNER = getAddress(V.owner) as Address;
const OTHER_OWNER = getAddress('0x000000000000000000000000000000000000dEaD') as Address;
const WRITER = getAddress('0x00000000000000000000000000000000000000A1') as Address;
const SPACE = fromHex(V.space);
const SPACE_HEX = to0x(SPACE);
const CONTRACT = getAddress(DEFAULT_CONTRACT) as Address;
const CALLDATA = V.push_calldata.data as Hex;

interface FakeEpoch {
  seq: number;
  block: number;
  prevBlock: number;
  prev: Hex;
  digest: Hex;
  tx: Hex;
  owner: Address;
  space: Hex;
}

function digestOf(seq: number): Hex {
  return `0x${seq.toString(16).padStart(64, '0')}`;
}

/** Four chained epochs at scattered blocks, exactly as a real space looks. */
function table(owner: Address = OWNER): FakeEpoch[] {
  const blocks = [100, 205, 999, 1500];
  return blocks.map((block, i) => ({
    seq: i + 1,
    block,
    prevBlock: i === 0 ? 0 : blocks[i - 1]!,
    prev: i === 0 ? (`0x${'00'.repeat(32)}` as Hex) : digestOf(i),
    digest: digestOf(i + 1),
    tx: `0x${(i + 1).toString(16).padStart(64, 'e')}` as Hex,
    owner,
    space: SPACE_HEX,
  }));
}

interface FakeClient extends EpochReadClient {
  logCalls: { fromBlock: bigint; toBlock: bigint }[];
}

function makeClient(rows: FakeEpoch[], headSeq = rows.length): FakeClient {
  const headRow = rows.find((r) => r.seq === headSeq);
  const logCalls: { fromBlock: bigint; toBlock: bigint }[] = [];
  return {
    logCalls,
    async readContract(args) {
      switch (args.functionName) {
        case 'head':
          return headRow
            ? [headRow.digest, BigInt(headRow.seq), BigInt(headRow.block)]
            : [`0x${'00'.repeat(32)}`, 0n, 0n];
        case 'startSeq':
          return 1n;
        case 'sessionKeyExpiry':
          return 1893456000n;
        default:
          throw new Error(`unexpected read ${args.functionName}`);
      }
    },
    async getLogs(args) {
      logCalls.push({ fromBlock: args.fromBlock, toBlock: args.toBlock });
      const wantOwner = args.args?.owner as Address | undefined;
      const wantSpace = args.args?.space as Hex | undefined;
      const hits = rows.filter(
        (r) =>
          BigInt(r.block) >= args.fromBlock &&
          BigInt(r.block) <= args.toBlock &&
          (wantOwner === undefined || wantOwner === r.owner) &&
          (wantSpace === undefined || wantSpace === r.space),
      );
      return hits.map(
        (r): EpochLog => ({
          args: {
            owner: r.owner,
            space: r.space,
            writer: WRITER,
            seq: BigInt(r.seq),
            prev: r.prev,
            digest: r.digest,
            prevBlock: BigInt(r.prevBlock),
          },
          blockNumber: BigInt(r.block),
          transactionHash: r.tx,
        }),
      );
    },
    async getTransaction({ hash }) {
      const row = rows.find((r) => r.tx === hash);
      if (!row) throw new Error(`no such tx ${hash}`);
      return { to: CONTRACT, input: CALLDATA };
    },
  };
}

describe('reads', () => {
  test('readHead decodes the tuple', async () => {
    const head = await readHead(makeClient(table()), CONTRACT, V.owner, SPACE);
    expect(head.seq).toBe(4);
    expect(head.blockNumber).toBe(1500);
    expect(toHex(head.digest)).toBe(digestOf(4).slice(2));
  });

  test('readSessionKeyExpiry and readStartSeq come back as numbers', async () => {
    const c = makeClient(table());
    expect(await readSessionKeyExpiry(c, CONTRACT, V.owner, OTHER_OWNER)).toBe(1893456000);
    expect(await readStartSeq(c, CONTRACT, V.owner, SPACE)).toBe(1);
  });
});

describe('walkEpochs', () => {
  test('walks head to genesis, newest first', async () => {
    const c = makeClient(table());
    const evs = await walkEpochs(c, CONTRACT, V.owner, SPACE);
    expect(evs.map((e) => e.seq)).toEqual([4, 3, 2, 1]);
    expect(evs.map((e) => e.blockNumber)).toEqual([1500, 999, 205, 100]);
    expect(evs.map((e) => e.prevBlock)).toEqual([999, 205, 100, 0]);
    expect(evs[0]!.owner).toBe(OWNER);
    expect(toHex(evs[0]!.space)).toBe(V.space);
  });

  test('one exact-block getLogs per hop, never a range', async () => {
    const c = makeClient(table());
    await walkEpochs(c, CONTRACT, V.owner, SPACE);
    expect(c.logCalls.length).toBe(4);
    for (const call of c.logCalls) expect(call.fromBlock).toBe(call.toBlock);
    expect(c.logCalls.map((x) => Number(x.fromBlock))).toEqual([1500, 999, 205, 100]);
  });

  test('stopSeq is an exclusive floor', async () => {
    const evs = await walkEpochs(makeClient(table()), CONTRACT, V.owner, SPACE, { stopSeq: 2 });
    expect(evs.map((e) => e.seq)).toEqual([4, 3]);
  });

  test('stopWhen ends the walk with that event included', async () => {
    const evs = await walkEpochs(makeClient(table()), CONTRACT, V.owner, SPACE, {
      stopWhen: (e) => e.seq === 3,
    });
    expect(evs.map((e) => e.seq)).toEqual([4, 3]);
  });

  test('maxEpochs caps the walk', async () => {
    const evs = await walkEpochs(makeClient(table()), CONTRACT, V.owner, SPACE, { maxEpochs: 1 });
    expect(evs.map((e) => e.seq)).toEqual([4]);
  });

  test('an empty space walks to nothing', async () => {
    const evs = await walkEpochs(makeClient([], 0), CONTRACT, V.owner, SPACE);
    expect(evs).toEqual([]);
  });

  test('a hole in the chain refuses instead of guessing', async () => {
    const rows = table().filter((r) => r.seq !== 2);
    await expect(walkEpochs(makeClient(rows, 4), CONTRACT, V.owner, SPACE)).rejects.toThrow(
      /no Epoch event for seq 2 at block 205/,
    );
  });

  test('logs for another owner are filtered out', async () => {
    const rows = table(OTHER_OWNER);
    const head = { digest: fromHex(digestOf(4)), seq: 4, blockNumber: 1500 };
    await expect(
      walkEpochs(makeClient(rows, 4), CONTRACT, V.owner, SPACE, { head }),
    ).rejects.toThrow(/no Epoch event for seq 4/);
  });

  test('a supplied head skips the head() call', async () => {
    const c = makeClient(table());
    const evs = await walkEpochs(c, CONTRACT, V.owner, SPACE, {
      head: { digest: fromHex(digestOf(2)), seq: 2, blockNumber: 205 },
    });
    expect(evs.map((e) => e.seq)).toEqual([2, 1]);
  });
});

describe('calldata', () => {
  test('push decodes to the same owner, space, prev and ciphertext', () => {
    const call = decodePushCalldata(CALLDATA);
    expect(call.owner).toBe(getAddress(V.push_calldata.owner));
    expect(toHex(call.space)).toBe(V.push_calldata.space);
    expect(toHex(call.prev)).toBe(V.push_calldata.prev);
    expect(call.ct.length).toBe(V.push_calldata.ct_length);
    expect(toHex(call.ct)).toBe(V.epoch1.blob);
  });

  test('keccak256 of the ciphertext matches the anchored digest', () => {
    const call = decodePushCalldata(CALLDATA);
    expect(toHex(ciphertextDigest(call.ct))).toBe(V.push_calldata.ct_keccak);
    expect(V.push_calldata.ct_keccak).toBe(V.epoch1.digest);
    expect(() => assertCiphertextMatchesDigest(call.ct, fromHex(V.epoch1.digest))).not.toThrow();
  });

  test('a mismatched digest refuses the epoch', () => {
    const call = decodePushCalldata(CALLDATA);
    expect(() => assertCiphertextMatchesDigest(call.ct, new Uint8Array(32))).toThrow(
      /does not match the anchored digest/,
    );
  });

  test('the selector is the one the ABI defines', () => {
    expect(CALLDATA.slice(0, 10)).toBe(V.push_calldata.selector);
  });

  test('epochCiphertext pulls it out of a transaction', async () => {
    const rows = table();
    const call = await epochCiphertext(makeClient(rows), rows[0]!.tx, CONTRACT);
    expect(toHex(call.ct)).toBe(V.epoch1.blob);
  });

  test('a transaction addressed elsewhere is refused', async () => {
    const rows = table();
    const c = makeClient(rows);
    const wrong: EpochReadClient = {
      ...c,
      async getTransaction() {
        return { to: OTHER_OWNER, input: CALLDATA };
      },
    };
    await expect(epochCiphertext(wrong, rows[0]!.tx, CONTRACT)).rejects.toThrow(
      /not addressed to EpochAnchor/,
    );
  });
});

describe('isSnapshotEvent', () => {
  function clientServing(blobHex: string): EpochReadClient {
    const ct = fromHex(blobHex);
    const input = encodeFunctionData({
      abi: EPOCH_ANCHOR_ABI,
      functionName: 'push',
      args: [OWNER, SPACE_HEX, `0x${'00'.repeat(32)}`, to0x(ct)],
    });
    return { ...makeClient(table()), async getTransaction() { return { to: CONTRACT, input }; } };
  }

  function eventFor(blobHex: string, digest: Hex): EpochEvent {
    return {
      owner: OWNER,
      space: SPACE,
      writer: WRITER,
      seq: 1,
      prev: new Uint8Array(32),
      digest: fromHex(digest),
      prevBlock: 0,
      blockNumber: 100,
      txHash: `0x${'ab'.repeat(32)}`,
    };
  }

  test('true for the epoch whose header carries FLAG_SNAPSHOT', async () => {
    const ev = eventFor(V.epoch2.blob, `0x${V.epoch2.digest}`);
    expect(await isSnapshotEvent(clientServing(V.epoch2.blob), ev, CONTRACT)).toBe(true);
  });

  test('false for an ordinary epoch', async () => {
    const ev = eventFor(V.epoch1.blob, `0x${V.epoch1.digest}`);
    expect(await isSnapshotEvent(clientServing(V.epoch1.blob), ev, CONTRACT)).toBe(false);
  });

  test('false when the ciphertext does not match the anchored digest', async () => {
    const ev = eventFor(V.epoch2.blob, `0x${'11'.repeat(32)}`);
    expect(await isSnapshotEvent(clientServing(V.epoch2.blob), ev, CONTRACT)).toBe(false);
  });

  test('an async stopWhen ends the walk', async () => {
    const evs = await walkEpochs(makeClient(table()), CONTRACT, V.owner, SPACE, {
      stopWhen: async (e) => Promise.resolve(e.seq === 3),
    });
    expect(evs.map((e) => e.seq)).toEqual([4, 3]);
  });
});

describe('coldStartEvents', () => {
  const ZERO = `0x${'00'.repeat(32)}` as Hex;

  /**
   * The same four epochs, except each one's anchored digest is the real keccak
   * of the blob its transaction serves, so isSnapshotEvent gets past the digest
   * check and actually reads the header flag.
   */
  function servedTable(blobBySeq: Record<number, string>): FakeEpoch[] {
    const blocks = [100, 205, 999, 1500];
    const rows: FakeEpoch[] = [];
    let prev = ZERO;
    blocks.forEach((block, i) => {
      const seq = i + 1;
      const blobHex = blobBySeq[seq] ?? V.epoch1.blob;
      const digest = `0x${toHex(ciphertextDigest(fromHex(blobHex)))}` as Hex;
      rows.push({
        seq,
        block,
        prevBlock: i === 0 ? 0 : blocks[i - 1]!,
        prev,
        digest,
        tx: `0x${seq.toString(16).padStart(64, 'e')}` as Hex,
        owner: OWNER,
        space: SPACE_HEX,
      });
      prev = digest;
    });
    return rows;
  }

  function servingClient(rows: FakeEpoch[], blobBySeq: Record<number, string>): FakeClient {
    return {
      ...makeClient(rows),
      async getTransaction({ hash }) {
        const row = rows.find((r) => r.tx === hash);
        if (!row) throw new Error(`no such tx ${hash}`);
        const ct = fromHex(blobBySeq[row.seq] ?? V.epoch1.blob);
        return {
          to: CONTRACT,
          input: encodeFunctionData({
            abi: EPOCH_ANCHOR_ABI,
            functionName: 'push',
            args: [OWNER, SPACE_HEX, ZERO, to0x(ct)],
          }),
        };
      },
    };
  }

  test('a genuine snapshot at the head stops the walk', async () => {
    const blobs = { 4: V.epoch2.blob };
    const rows = servedTable(blobs);
    const asked: number[] = [];
    const res = await coldStartEvents(servingClient(rows, blobs), CONTRACT, V.owner, SPACE, {
      tryOpen: (ev) => {
        asked.push(ev.seq);
        return true;
      },
    });
    expect(res.events.map((e) => e.seq)).toEqual([4]);
    expect(res.refusedSnapshotSeq).toBe(null);
    expect(res.stoppedAtSnapshot).toBe(true);
    expect(asked).toEqual([4]);
  });

  test('a snapshot mid-chain returns it and everything after it, oldest first', async () => {
    const blobs = { 3: V.epoch2.blob };
    const rows = servedTable(blobs);
    const res = await coldStartEvents(servingClient(rows, blobs), CONTRACT, V.owner, SPACE, {
      tryOpen: () => true,
    });
    expect(res.events.map((e) => e.seq)).toEqual([3, 4]);
    expect(res.stoppedAtSnapshot).toBe(true);
  });

  test('a forged FLAG_SNAPSHOT that will not open re-walks the whole history', async () => {
    const blobs = { 4: V.epoch2.blob };
    const rows = servedTable(blobs);
    const res = await coldStartEvents(servingClient(rows, blobs), CONTRACT, V.owner, SPACE, {
      tryOpen: () => false,
    });
    expect(res.events.map((e) => e.seq)).toEqual([1, 2, 3, 4]);
    expect(res.refusedSnapshotSeq).toBe(4);
    expect(res.stoppedAtSnapshot).toBe(false);
  });

  test('a tryOpen that throws counts as a refusal, not a crash', async () => {
    const blobs = { 4: V.epoch2.blob };
    const rows = servedTable(blobs);
    const res = await coldStartEvents(servingClient(rows, blobs), CONTRACT, V.owner, SPACE, {
      tryOpen: () => {
        throw new Error('this epoch does not open');
      },
    });
    expect(res.events.map((e) => e.seq)).toEqual([1, 2, 3, 4]);
    expect(res.refusedSnapshotSeq).toBe(4);
  });

  test('no snapshot anywhere walks everything and never asks tryOpen', async () => {
    const rows = servedTable({});
    const res = await coldStartEvents(servingClient(rows, {}), CONTRACT, V.owner, SPACE, {
      tryOpen: () => {
        throw new Error('tryOpen must not be called when no epoch claims to be a snapshot');
      },
    });
    expect(res.events.map((e) => e.seq)).toEqual([1, 2, 3, 4]);
    expect(res.refusedSnapshotSeq).toBe(null);
    expect(res.stoppedAtSnapshot).toBe(false);
  });
});
