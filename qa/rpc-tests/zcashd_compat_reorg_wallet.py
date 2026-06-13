#!/usr/bin/env python3
# Copyright (c) 2026 The Zcash developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://www.opensource.org/licenses/mit-license.php .

from decimal import Decimal

from test_framework.authproxy import JSONRPCException
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, assert_greater_than, assert_true
from test_framework.zcashd_compat import wait_for_compat_tip, wait_until


def wallet_balance_at_least(node, amount):
    try:
        return node.getbalance() >= amount
    except JSONRPCException as e:
        if "disabled while reindexing" in e.error["message"]:
            return False
        raise


class ZcashdCompatReorgWalletTest(BitcoinTestFramework):
    """A confirmed wallet transaction survives a zebrad-side reorg correctly.

    Single node, so there is no inter-node propagation. The node mines a wallet
    transaction, the confirming block is then replaced on the zebra side by a
    longer competing chain. The wrapper follows the reorg; the transaction
    returns to the mempool and is re-mined into the new chain. The test asserts
    the orphaned block is reported as off-chain (-1 confirmations), the wallet
    re-confirms the deposit in a *different* block, and the balance is not
    double-counted. This is the deposit-reorg path that matters to exchanges.

    Note: the wrapper deliberately does not follow a strict truncation (zebra
    regressing below the trusted boundary leaves it in `sync state = degraded`
    holding the confirmed chain), so a durable "unconfirmed" only arises from an
    actual double-spend; that conflict case is out of scope here.
    """

    def __init__(self):
        super().__init__()
        self.cache_behavior = 'clean'
        self.num_nodes = 1
        self.num_wallets = 0

    def run_test(self):
        node = self.nodes[0]
        wait_for_compat_tip(node)

        node.generate(101)
        self.sync_all()
        wait_until(lambda: wallet_balance_at_least(node, Decimal("1.0")), timeout=60)

        # Send and confirm a wallet transaction.
        addr = node.getnewaddress()
        txid = node.sendtoaddress(addr, Decimal("1.0"))
        wait_until(lambda: txid in node.zebra.getrawmempool(), timeout=60)
        wait_until(lambda: node.getzebracompatinfo()["tx_forwarding"]["pending"] == 0, timeout=60)
        node.generate(1)
        self.sync_all()

        tx_block = node.getbestblockhash()
        before = node.gettransaction(txid)
        assert_greater_than(before["confirmations"], 0)
        assert_equal(before["blockhash"], tx_block)
        received_before = node.getreceivedbyaddress(addr, 1)

        # Replace the confirming block with a longer competing chain on the
        # zebra side. The transaction returns to zebra's mempool and is re-mined.
        node.zebra.invalidateblock(tx_block)
        wait_until(lambda: txid in node.zebra.getrawmempool(), timeout=60)
        node.zebra.generate(2)
        wait_for_compat_tip(node)
        # wait_for_compat_tip only guarantees chain-tip agreement; sync_all also
        # waits for the zcashd wallet to process the reconnected block (via
        # validation_notifications_caught_up), without which gettransaction can
        # momentarily still report the tx conflicted from the disconnect.
        self.sync_all()

        # The old confirming block is now off the active chain.
        assert_equal(node.getblock(tx_block)["confirmations"], -1)

        # The wallet re-confirms the deposit in a new block, without
        # double-counting it.
        after = node.gettransaction(txid)
        assert_greater_than(after["confirmations"], 0)
        assert_true(after["blockhash"] != tx_block)
        assert_equal(node.getreceivedbyaddress(addr, 1), received_before)
        assert_equal(node.getbestblockhash(), node.zebra.getbestblockhash())


if __name__ == '__main__':
    ZcashdCompatReorgWalletTest().main()
