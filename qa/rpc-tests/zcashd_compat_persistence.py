#!/usr/bin/env python3
# Copyright (c) 2026 The Zcash developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://www.opensource.org/licenses/mit-license.php .

from test_framework.config import ZebraArgs
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import (
    assert_equal,
    rpc_url,
    start_nodes,
    zcashd_processes,
)
from test_framework.zcashd_compat import (
    CompatNode,
    start_zcashd,
    wait_for_compat_tip,
    wait_until,
)

FLUSH_ARGS = ['-zebra-compat-flush-interval=1']


class ZcashdCompatPersistenceTest(BitcoinTestFramework):
    """Ingested chainstate survives an unclean zcashd restart.

    With `-zebra-compat-flush-interval=1` the compat ingest path flushes the
    coins database to disk as blocks are ingested (the fix for the restart bug
    where chainstate lagged the trusted boundary and forced a large replay).
    After flushing to the tip, zcashd is killed with SIGKILL (no clean-shutdown
    flush can mask the behaviour) and restarted against the still-running paired
    zebrad. Only zcashd is restarted, which is both the right scope for a
    chainstate-persistence test and avoids a heavy zebrad restart. The test
    asserts the wrapper comes back up tip-aligned with the persisted chainstate.
    """

    def __init__(self):
        super().__init__()
        self.cache_behavior = 'clean'
        self.num_nodes = 1
        self.num_wallets = 0

    def setup_nodes(self):
        return start_nodes(self.num_nodes, self.options.tmpdir, extra_args=[FLUSH_ARGS])

    def run_test(self):
        node = self.nodes[0]
        wait_for_compat_tip(node)

        node.generate(120)
        self.sync_all()
        tip_height = node.getblockcount()
        tip_hash = node.getbestblockhash()

        # The compat ingest path flushes chainstate up to the tip. Without the
        # flush fix `last_flushed_height` would never advance and this would
        # time out.
        def flushed_to_tip():
            f = node.getzebracompatinfo()["chainstate_flush"]
            return f["last_flushed_height"] == tip_height and f["last_flushed_hash"] == tip_hash

        wait_until(flushed_to_tip, timeout=60)
        flush = node.getzebracompatinfo()["chainstate_flush"]
        assert_equal(flush["interval_seconds"], 1)
        assert_equal(flush["last_error"], None)

        # Kill zcashd uncleanly (SIGKILL: no clean-shutdown flush), leaving the
        # paired zebrad running, then restart only zcashd against it. Only the
        # persisted chainstate can carry the tip across this restart.
        zebra = node.zebra
        zcashd_processes[0].kill()
        zcashd_processes[0].wait()
        del zcashd_processes[0]

        restarted_zcashd = start_zcashd(
            0, self.options.tmpdir, rpc_url(0),
            ZebraArgs().activation_heights, zcashd_args=FLUSH_ARGS)
        self.nodes[0] = CompatNode(zebra, restarted_zcashd)
        node = self.nodes[0]
        wait_for_compat_tip(node, timeout=120)

        # Recovered at the flushed tip, not replayed from genesis/an old snapshot.
        assert_equal(node.getblockcount(), tip_height)
        assert_equal(node.getbestblockhash(), tip_hash)

        recovered = node.getzebracompatinfo()
        assert_equal(recovered["chainstate_flush"]["last_error"], None)
        assert_equal(recovered["local"]["bestblockhash"], tip_hash)
        assert_equal(recovered["trusted_boundary"]["height"], tip_height)


if __name__ == '__main__':
    ZcashdCompatPersistenceTest().main()
