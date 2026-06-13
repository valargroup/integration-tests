#!/usr/bin/env python3
# Copyright (c) 2026 The Zcash developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://www.opensource.org/licenses/mit-license.php .

from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal
from test_framework.zcashd_compat import wait_for_compat_tip


class ZcashdCompatIdentityTest(BitcoinTestFramework):

    def __init__(self):
        super().__init__()
        self.cache_behavior = 'clean'
        self.num_nodes = 1
        self.num_wallets = 0

    def run_test(self):
        node = self.nodes[0]
        wait_for_compat_tip(node)

        zebra_chain = node.zebra.getblockchaininfo()
        zebra_genesis = node.zebra.getblockhash(0)
        zebra_best_hash = node.zebra.getbestblockhash()
        zebra_count = node.zebra.getblockcount()

        info = node.getzebracompatinfo()
        assert_equal(info["service_state"], "ready")
        assert_equal(info["sync"]["state"], "synced")
        assert_equal(info["zebra"]["reachable"], True)
        assert_equal(info["zebra"]["identity_verified"], True)
        assert_equal(info["zebra"]["network"], zebra_chain["chain"])
        assert_equal(info["zebra"]["genesis"], zebra_genesis)
        assert_equal(info["zebra"]["bestblockhash"], zebra_best_hash)
        assert_equal(info["zebra"]["blocks"], zebra_count)
        assert_equal(info["local"]["bestblockhash"], zebra_best_hash)
        assert_equal(node.getblockhash(0), zebra_genesis)


if __name__ == '__main__':
    ZcashdCompatIdentityTest().main()
