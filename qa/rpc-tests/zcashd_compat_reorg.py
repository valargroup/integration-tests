#!/usr/bin/env python3
# Copyright (c) 2026 The Zcash developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://www.opensource.org/licenses/mit-license.php .

from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, start_nodes
from test_framework.zcashd_compat import wait_for_compat_tip


class ZcashdCompatReorgTest(BitcoinTestFramework):

    def __init__(self):
        super().__init__()
        self.cache_behavior = 'current'
        self.num_nodes = 1
        self.num_wallets = 0

    def setup_nodes(self):
        return start_nodes(self.num_nodes, self.options.tmpdir, extra_args=[[
            '-zebra-compat-sync-batch-size=30',
        ]])

    def assert_reorg_followed(self, node, depth):
        node.generate(max(10, depth))
        old_tip = node.getbestblockhash()
        old_height = node.getblockcount()

        fork_hash = node.getblockhash(old_height - depth + 1)
        node.zebra.invalidateblock(fork_hash)
        node.zebra.generate(depth + 1)
        wait_for_compat_tip(node)

        assert_equal(node.getbestblockhash(), node.zebra.getbestblockhash())
        assert_equal(node.getblock(old_tip)['confirmations'], -1)

        orphaned_tip = None
        for tip in node.getchaintips():
            if tip['hash'] == old_tip:
                orphaned_tip = tip
                break

        assert orphaned_tip is not None
        assert_equal(orphaned_tip['status'], 'valid-fork')
        assert_equal(orphaned_tip['branchlen'], depth)

    def run_test(self):
        node = self.nodes[0]
        wait_for_compat_tip(node)

        self.assert_reorg_followed(node, 3)
        self.assert_reorg_followed(node, 25)


if __name__ == '__main__':
    ZcashdCompatReorgTest().main()
