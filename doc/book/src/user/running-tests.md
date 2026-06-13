# Running Tests

## Prerequisites

### Binaries

All tests require the `zebrad` binary; most tests require the `zallet` binary;
some tests require the `zainod` binary. The opt-in zcashd compatibility profile
also requires a zebra-compat-enabled `zcashd` binary.

By default, binaries must exist in the `./src/` folder under the repository
root. Alternatively, you can set the binary paths with environment variables:

```bash
export ZEBRAD=/path/to/zebrad
export ZAINOD=/path/to/zainod
export ZALLET=/path/to/zallet
export ZCASHD=/path/to/zcashd
```

### Python dependencies

The `zmq`, `toml`, and `base58` Python libraries are required.

#### With uv (recommended)

```bash
uv sync
```

#### Without uv

On Ubuntu or Debian-based distributions:

```bash
sudo apt-get install python3-zmq python3-base58 python3-toml
```

On macOS or other platforms:

```bash
python3 -m venv venv
. venv/bin/activate
pip3 install pyzmq base58 toml
```

## Running the full test suite

With uv:

```bash
uv run ./qa/zcash/full_test_suite.py
```

Without uv:

```bash
./qa/zcash/full_test_suite.py
```

## Running individual tests

Run a single test:

```bash
./qa/pull-tester/rpc-tests.py <testname>
```

Run multiple specific tests:

```bash
./qa/pull-tester/rpc-tests.py <testname1> <testname2> <testname3>
```

Run all regression tests:

```bash
./qa/pull-tester/rpc-tests.py
```

Run the opt-in zcashd compatibility profile:

```bash
ZCASHD=/path/to/zcashd ZEBRAD=/path/to/zebrad ./qa/pull-tester/rpc-tests.py --zcashd-compat
```

This profile starts paired regtest stacks of zebrad plus `zcashd -zebra-compat`.
Mining and P2P topology operations are routed to zebrad; zcashd provides the
wallet and zcashd RPC surface. It is intended as a completeness benchmark for
tests that require zcashd RPCs, not for P2P/mininode or zcashd mining-internals
tests.

The profile uses a separate pregenerated chain cache. It caches only zebrad
datadirs; zcashd starts clean, imports the static regtest miner key, and rescans
cached blocks. Tests that depend on zcashd owning P2P connections, mining blocks
itself, or exercising chain-control reorg internals remain out of scope.

## Parallel execution

By default, tests run in parallel with 4 jobs. To change the number of jobs:

```bash
./qa/pull-tester/rpc-tests.py --jobs=n
```

## Test runner options

```
-h, --help            show this help message and exit
--nocleanup           Leave test datadirs on exit or error
--noshutdown          Don't stop nodes after the test execution
--srcdir=SRCDIR       Source directory containing binaries (default: ../../src)
--tmpdir=TMPDIR       Root directory for datadirs
--tracerpc            Print out all RPC calls as they are made
--coveragedir=COVERAGEDIR
                      Write tested RPC commands into this directory
```

## Debugging

Set `PYTHON_DEBUG=1` for debug output:

```bash
PYTHON_DEBUG=1 qa/pull-tester/rpc-tests.py wallet
```

For real-time output, run a test directly with `python3`:

```bash
python3 qa/rpc-tests/wallet.py
```

## Cache management

A 200-block regtest blockchain and wallets for four nodes are created the first
time a regression test is run and stored in the `cache/` directory. Each node has
the miner subsidy from 25 mature blocks (25*10=250 ZEC) in its wallet.

After the first run, the cached blockchain and wallets are copied into a
temporary directory and used as the initial test state.

If you get into a bad state, you can recover with:

```bash
rm -rf cache
killall zebrad
killall zcashd
killall zainod
killall zallet
```
