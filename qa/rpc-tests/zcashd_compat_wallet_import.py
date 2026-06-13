#!/usr/bin/env python3
# Copyright (c) 2026 The Zcash developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://www.opensource.org/licenses/mit-license.php .

from decimal import Decimal

from test_framework.authproxy import JSONRPCException
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, assert_true
from test_framework.zcashd_compat import wait_for_compat_tip, wait_until


def wallet_balance_at_least(node, amount):
    try:
        return node.getbalance() >= amount
    except JSONRPCException as e:
        if "disabled while reindexing" in e.error["message"]:
            return False
        raise


class ZcashdCompatWalletImportTest(BitcoinTestFramework):
    """Cross-wallet key import-with-rescan for the zcashd-compat profile.

    This needs two wallets, but it is built on the reliable topology: the
    funding node (node 0) mines its own blocks and is directly connected to
    node 1, so node 1 receives those blocks by direct delivery.

    It exports a funded address's private key from node 0 and imports it into
    node 1 with rescan, asserting node 1's wallet then sees the pre-existing
    chain history for that address.
    """

    def __init__(self):
        super().__init__()
        self.cache_behavior = 'clean'
        self.num_nodes = 2
        self.num_wallets = 0

    def run_test(self):
        funder, importer = self.nodes
        wait_for_compat_tip(funder)
        wait_for_compat_tip(importer)

        # Fund node 0's wallet (zebrad mines to its imported MINER_KEYS address)
        # and mature the coinbase.
        funder.generate(101)
        self.sync_all()
        wait_until(lambda: wallet_balance_at_least(funder, Decimal("1.0")), timeout=60)

        # Fund a fresh address on node 0 with several confirmed payments. The
        # address's key exists only in node 0's wallet at this point. (Coin
        # selection may re-spend some of these outputs in later sends, which is
        # fine: the rescan check below compares node 1's reconstructed view
        # against node 0's actual view, not against the amounts sent.)
        addr = funder.getnewaddress()
        for amount in (Decimal("2.5"), Decimal("1.5"), Decimal("0.75")):
            txid = funder.sendtoaddress(addr, amount)
            wait_until(lambda t=txid: t in funder.zebra.getrawmempool(), timeout=60)
            wait_until(lambda: funder.getzebracompatinfo()["tx_forwarding"]["pending"] == 0, timeout=60)
            funder.generate(1)
            self.sync_all()

        def utxo_key(u):
            return (u["txid"], u["vout"], u["amount"])

        funder_view = sorted(map(utxo_key, funder.listunspent(1, 9999999, [addr])))
        assert_true(len(funder_view) > 0)

        # Export the key from node 0; node 1 has not seen this address yet.
        privkey = funder.dumpprivkey(addr)
        assert_equal(importer.listunspent(1, 9999999, [addr]), [])

        # Import into node 1 with rescan. The rescan must reconstruct exactly
        # the same UTXO set from the chain history node 1 already has (delivered
        # directly from node 0).
        imported_addr = importer.importprivkey(privkey, "", True)
        assert_equal(imported_addr, addr)

        importer_view = sorted(map(utxo_key, importer.listunspent(1, 9999999, [addr])))
        assert_equal(importer_view, funder_view)

        # Both nodes agree on the tip with their paired zebrad.
        assert_equal(funder.getbestblockhash(), importer.getbestblockhash())
        assert_equal(funder.getbestblockhash(), funder.zebra.getbestblockhash())
        assert_equal(importer.getbestblockhash(), importer.zebra.getbestblockhash())


if __name__ == '__main__':
    ZcashdCompatWalletImportTest().main()
