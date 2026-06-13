#!/usr/bin/env python3
# Copyright (c) 2026 The Zcash developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://www.opensource.org/licenses/mit-license.php .

from decimal import Decimal

from test_framework.authproxy import JSONRPCException
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal
from test_framework.zcashd_compat import wait_for_compat_tip, wait_until


def wallet_balance_at_least(node, amount):
    try:
        return node.getbalance() >= amount
    except JSONRPCException as e:
        if "disabled while reindexing" in e.error["message"]:
            return False
        raise


class ZcashdCompatSmokeTest(BitcoinTestFramework):

    def __init__(self):
        super().__init__()
        self.cache_behavior = 'clean'
        self.num_nodes = 2
        self.num_wallets = 0

    def run_test(self):
        sender, receiver = self.nodes

        wait_for_compat_tip(sender)
        wait_for_compat_tip(receiver)

        sender.generate(101)
        self.sync_all()
        wait_until(lambda: wallet_balance_at_least(sender, Decimal("0.1")), timeout=60)

        destination = receiver.getnewaddress()
        txid = sender.sendtoaddress(destination, Decimal("0.1"))

        wait_until(lambda: txid in sender.getrawmempool(), timeout=60)
        wait_until(lambda: txid in sender.zebra.getrawmempool(), timeout=60)
        wait_until(lambda: sender.getzebracompatinfo()["tx_forwarding"]["pending"] == 0, timeout=60)

        sender.generate(1)
        self.sync_all()
        wait_until(lambda: txid not in sender.getrawmempool(), timeout=60)
        wait_until(lambda: wallet_balance_at_least(receiver, Decimal("0.1")), timeout=60)

        assert_equal(sender.getbestblockhash(), sender.zebra.getbestblockhash())
        assert_equal(receiver.getbestblockhash(), receiver.zebra.getbestblockhash())


if __name__ == '__main__':
    ZcashdCompatSmokeTest().main()
