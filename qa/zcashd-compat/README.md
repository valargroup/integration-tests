# zcashd compatibility test profile

## What this is

The zcashd compatibility profile is an **opt-in stack profile** for the
integration-test harness. Instead of the standard zebrad + zallet (+ zainod)
topology, each test "node" is a **paired regtest stack**:

- a `zebrad` node, which owns consensus, block templates/mining, and the P2P
  topology between nodes; and
- a `zcashd` binary running in **zebra-compat mode** (`-zebra-compat`), which
  runs with P2P disabled and ingests blocks from its paired zebrad over
  JSON-RPC, while providing the full zcashd wallet and RPC surface.

The zcashd binary is not built from this repository; it is a
[SHA256-pinned release artifact](release.json) from
[valargroup/zcashd](https://github.com/valargroup/zcashd).

### Why it exists

The tests in this repository were migrated out of zcashd with the intention
that the repo becomes a benchmark for the stability and completeness of the
replacement stack. Many migrated tests are currently parked in
`DISABLED_SCRIPTS` because they exercise zcashd RPCs that have no zallet
equivalent yet (key export/import, `dumpprivkey`, legacy wallet history RPCs,
HTTP basic auth, ...).

This profile serves two purposes:

1. **Validate the zebra-compat wrapper itself** — block ingestion, sync/reorg
   following, transaction forwarding into zebrad's mempool, and the
   identity/health surface (`getzebracompatinfo`).
2. **Act as a completeness benchmark** — re-enable disabled zcashd-RPC tests
   against a stack where zebrad does consensus but the zcashd wallet/RPC
   surface is still available. Tests that pass here define the behavior the
   Z3 stack (zallet/zainod) is converging toward.

The CI job (`test-rpc-zcashd-compat`) is required when it runs; failures block
the workflow.

## How a compat node works

Tests receive a `CompatNode` proxy
(`qa/rpc-tests/test_framework/zcashd_compat.py`) instead of a plain RPC
proxy. Calls are routed so existing tests work unmodified:

| Call | Routed to | Notes |
| --- | --- | --- |
| `addnode`, `getpeerinfo`, `disconnectnode`, `getaddednodeinfo` | zebrad | inter-node sync is zebrad P2P; compat zcashd has no P2P |
| `generate` | zebrad | then blocks until the paired zcashd has ingested the new tip (`wait_for_compat_tip`) |
| everything else | zcashd | the surface under test |

`node.zebra` and `node.zcashd` expose the underlying proxies directly for
tests that need to assert on a specific side (e.g. that a forwarded
transaction reached zebrad's mempool).

Other plumbing details:

- **Funding semantics**: zebrad mines to a per-node static address from
  `MINER_KEYS`; the paired zcashd imports the matching private key at startup,
  so `generate` credits the zcashd wallet exactly as it did in the legacy
  zcashd test framework.
- **Network upgrade alignment**: `ZebraArgs.activation_heights` is translated
  into the equivalent zcashd `-nuparams=<branch_id>:<height>` ladder, and
  legacy per-test `-nuparams` arguments are translated back into zebrad
  activation heights, so both halves of the pair always agree on consensus
  rules.
- **Ports**: zcashd RPC uses port multiplier 6 (`zcashd_rpc_port`), leaving
  all existing port assignments untouched.
- **Restarts**: tests that stop and restart nodes (e.g. `keypool.py` after
  `encryptwallet`) use `wait_for_node_shutdown`, which reaps the zcashd
  process and terminates the surviving zebrad cleanly.
- **Activation**: the profile is enabled by `ZCASHD_COMPAT=1` in the
  environment (set automatically by `--zcashd-compat`), so re-enabled legacy
  tests run without per-test modifications. Without the flag, harness
  behavior is byte-identical to the standard profile.

## Running locally

Requirements: a `zebrad` binary and a zebra-compat-enabled `zcashd` binary
(either build [valargroup/zcashd](https://github.com/valargroup/zcashd) or
download the release pinned in [`release.json`](release.json)), plus the
Sprout parameters in `~/.zcash-params` for the tests that need them.

Run the whole profile:

```bash
ZCASHD=/path/to/zcashd ZEBRAD=/path/to/zebrad ./qa/pull-tester/rpc-tests.py --zcashd-compat
```

Run an individual test (keep `--zcashd-compat`, otherwise compat-only tests
run against the plain stack and fail):

```bash
ZCASHD=/path/to/zcashd ZEBRAD=/path/to/zebrad ./qa/pull-tester/rpc-tests.py --zcashd-compat zcashd_compat_smoke.py
```

## CI

Two jobs in `.github/workflows/ci.yml`:

- **`get-zcashd`** downloads the runtime archive pinned in
  [`release.json`](release.json), verifies its SHA256, extracts the pinned
  binary path, and uploads it as the `zcashd-ubuntu-24.04` artifact. To bump
  the zcashd version, update the tag, URL, and SHA256 in `release.json`.
- **`test-rpc-zcashd-compat`** runs `ZCASHD_COMPAT_SCRIPTS` single-threaded
  against the built zebrad and the downloaded zcashd. It does not run for
  cross-repo interop requests.

## What test paths are covered

The profile runs the `ZCASHD_COMPAT_SCRIPTS` list in
`qa/pull-tester/rpc-tests.py`. It has two layers.

### Profile-specific tests (the wrapper itself)

| Test | Covers |
| --- | --- |
| `zcashd_compat_smoke.py` | End-to-end happy path: readiness, block ingestion from zebrad, wallet credit from mined coinbase, `sendtoaddress`, transaction forwarding into zebrad's mempool (`tx_forwarding` drains), confirmation, and tip equality between zcashd and zebrad on both nodes. |
| `zcashd_compat_identity.py` | The `getzebracompatinfo` health/identity surface: service state, sync state, zebra reachability and identity verification, and network/genesis/best-hash/height agreement with the paired zebrad. |
| `zcashd_compat_reorg.py` | Reorg following: zebrad-side `invalidateblock` plus a longer replacement chain at depths 3 and 25 (crossing the sync batch size), asserting zcashd reorgs to the new tip and reports the old chain as orphaned with negative confirmations. |
| `zcashd_compat_wallet.py` | Single-node mutative wallet round-trip: fund from mined coinbase, `sendtoaddress` to a fresh address, forwarding into zebrad's mempool, confirmation, and the wallet read surface (`gettransaction`, `listunspent`, `listtransactions`) plus a `dumpprivkey` round-trip. One node mining its own blocks, so no inter-node propagation. |
| `zcashd_compat_wallet_import.py` | Cross-wallet key import-with-rescan on a directly-connected two-node stack: node 0 funds an address and exports its key via `dumpprivkey`; node 1 `importprivkey`s it with rescan and must reconstruct the same UTXO set from chain history. The funder mines its own blocks and node 1 receives them by direct delivery, avoiding the relayed-rebroadcast path. |

### Re-enabled legacy zcashd RPC tests (the benchmark)

These were in `DISABLED_SCRIPTS` because the standard stack cannot run them;
under this profile they run against the real zcashd wallet/RPC surface. The
list is deliberately scoped to tests that **pass reliably** against the wrapper
and each cover a distinct slice of the surface — it is not an attempt to
re-enable every disabled test (see [below](#not-covered-out-of-scope)).

| Area | Tests |
| --- | --- |
| RPC interface & auth | `multi_rpc.py` |
| Keypool & wallet encryption | `keypool.py` |

Both re-enabled legacy tests are single-node. Mutative wallet coverage (key
import/export, send/receive, rescan) is provided by the profile-native
`zcashd_compat_wallet.py` and `zcashd_compat_wallet_import.py` above rather than
by the legacy multi-node wallet tests, which are flaky under zebrad regtest
(see below).

Partial coverage:

- `keypool.py` — the keypool-drain-blocks-mining assertion is skipped because
  `generate` is routed to zebrad; the keypool/`encryptwallet`/restart paths
  run in full.

### Not covered (out of scope)

The profile is a benchmark for tests that need **zcashd RPCs**, not a way to
run every disabled test:

- **P2P/mininode framework tests** (`p2p-*`, `invalidblockrequest.py`, BIP
  tests, ...) — compat zcashd has no P2P; topology is zebrad's.
- **zcashd mining internals** (`getblocktemplate` paths, keypool mining
  interaction) — block production belongs to zebrad in this stack.
- **Sprout golden-cache tests** (`sprout_sapling_migration.py`, ...) — the
  cached chains are incompatible with zebrad, and sprout notes cannot be
  recreated post-Canopy.
- **`-proxy`/Tor, insight-explorer indexes, and other node options** zebrad
  does not support.
- **Flaky multi-node legacy tests** (`key_import_export.py`,
  `zkey_import_export.py`, `threeofthreerestore.py`, `wallet_isfromme.py`,
  `errors.py`) — these depend on multiple zebrad nodes converging on a tip,
  which is unreliable in regtest for two related reasons: (1) zebrad does not
  reliably rebroadcast *received* blocks, so in a 4-node star the leaf miner's
  blocks never reach the far nodes (ZcashFoundation/zebra#10329, #10332); and
  (2) tests that load the pregenerated chain cache can start with per-node
  zebrad datadirs on slightly divergent non-finalized tips, then time out on
  live P2P reconciliation. The profile-native wallet tests avoid both by using
  single-node or directly-connected topologies that mine their own blocks from
  a clean (un-cached) chain.
- **Failure injection** (zebra endpoint outages, malformed responses, chaos
  soak) — covered by the `zebra_compat_*.py` suite and
  `make compat-test-soak` in valargroup/zcashd, which uses a fake zebra
  server; this profile always runs against a real zebrad.
