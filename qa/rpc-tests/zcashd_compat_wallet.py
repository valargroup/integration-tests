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


class ZcashdCompatWalletTest(BitcoinTestFramework):
    """Single-node mutative wallet API coverage for the zcashd-compat profile.

    Everything happens on one node that mines its own blocks via its paired
    zebrad. It exercises the full mutative round-trip:
    funding, sendtoaddress, forwarding into zebrad's mempool, confirmation,
    and the wallet read surface (gettransaction/listunspent/listtransactions).
    """

    def __init__(self):
        super().__init__()
        self.cache_behavior = 'clean'
        self.num_nodes = 1
        self.num_wallets = 0

    def run_test(self):
        node = self.nodes[0]
        wait_for_compat_tip(node)

        # zebrad mines to the imported MINER_KEYS[0] address, so `generate`
        # credits this node's zcashd wallet. Mature the coinbase (regtest
        # coinbase maturity is 100 blocks).
        node.generate(101)
        self.sync_all()
        wait_until(lambda: wallet_balance_at_least(node, Decimal("1.0")), timeout=60)

        # Mutative path: create a fresh address and send to it.
        dest = node.getnewaddress()
        amount = Decimal("1.25")
        txid = node.sendtoaddress(dest, amount)

        # The send must reach zebrad's mempool before mining, otherwise the
        # zebrad-mined block would omit it.
        wait_until(lambda: txid in node.getrawmempool(), timeout=60)
        wait_until(lambda: txid in node.zebra.getrawmempool(), timeout=60)
        wait_until(lambda: node.getzebracompatinfo()["tx_forwarding"]["pending"] == 0, timeout=60)

        # gettransaction is available while still unconfirmed.
        unconfirmed = node.gettransaction(txid)
        assert_equal(unconfirmed["txid"], txid)
        assert_equal(unconfirmed["confirmations"], 0)

        node.generate(1)
        self.sync_all()
        wait_until(lambda: txid not in node.getrawmempool(), timeout=60)

        # Confirmed: the new address holds exactly the sent amount, spendable.
        confirmed = node.gettransaction(txid)
        assert_greater_than(confirmed["confirmations"], 0)

        utxos = node.listunspent(1, 9999999, [dest])
        assert_equal(len(utxos), 1)
        assert_equal(utxos[0]["amount"], amount)
        assert_equal(utxos[0]["address"], dest)

        # The transaction shows up in wallet history.
        assert_true(any(t["txid"] == txid for t in node.listtransactions("*", 100)))

        # dumpprivkey round-trips: re-importing the key is a no-op, not an error.
        privkey = node.dumpprivkey(dest)
        node.importprivkey(privkey, "", False)

        # Wrapper stays healthy and tip-aligned after all wallet activity.
        assert_equal(node.getbestblockhash(), node.zebra.getbestblockhash())
        info = node.getzebracompatinfo()
        assert_equal(info["service_state"], "ready")
        assert_equal(info["sync"]["state"], "synced")


if __name__ == '__main__':
    ZcashdCompatWalletTest().main()
