#!/usr/bin/env python3
# Copyright (c) 2026 The Zcash developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://www.opensource.org/licenses/mit-license.php .

import errno
import os
import subprocess
import time

from . import coverage
from .authproxy import JSONRPCException
from .config import ZebraArgs, render_regtest_nuparams
from .util import (
    COVERAGE_DIR,
    PROC_START_TIMEOUT,
    ZCASHD_COMPAT_RPC_PASSWORD,
    ZCASHD_COMPAT_RPC_USERNAME,
    bitcoind_processes,
    get_rpc_auth_proxy,
    get_rpc_proxy,
    indexer_rpc_port,
    node_dir,
    p2p_port,
    rpc_port,
    rpc_url,
    update_zebrad_conf,
    wait_or_kill,
    wait_for_zebrad_start,
    zcashd_binary,
    zcashd_compat_enabled,
    zcashd_processes,
    zcashd_rpc_port,
    zcashd_rpc_url,
    zebrad_binary,
)


_BRANCH_ID_TO_NU_NAME = {
    "5ba81b19": "Overwinter",
    "76b809bb": "Sapling",
    "2bb40e60": "Blossom",
    "f5b9230b": "Heartwood",
    "e9ff75a6": "Canopy",
    "c2d6d0b4": "NU5",
    "c8e71055": "NU6",
    "4dec4df0": "NU6.1",
    "5437f330": "NU6.2",
}

_BASE_ZCASH_CONF_KEYS = {
    "regtest",
    "showmetrics",
    "rpcuser",
    "rpcpassword",
    "rpcport",
    "port",
    "listen",
    "listenonion",
}

MINER_KEYS = [
    ("cUeKHd5orzT3mz8P9pxyREHfsWtVfgsfDjiZZBcjUBAaGk1BTj7N", "tmJXomn8fhYy3AFqDEteifjHRMUdKtBuTGM"),
    ("cQMdgyv6y8pAftMKnrZDMMeJGZdfVUhMBrw3L71rctnAuP65S2HW", "tmUtDnWmxBwnNfD9P8WunnfS1aBHDUmtXeq"),
    ("cNnNF7LqiUA7rceSUK4hTwebAJ9cHAGHY77wAXWjKkmYvDN9mG5L", "tmB5BegiM72ahvATuExGQQpEC5jCKGckJHd"),
    ("cSS7GjcMd1u65YgawxgaWLNnBJavVdYYHuqib6TbNQYZvA2TurAB", "tmN1doZt6v17DiMPhqGqHdFJgEwYhoZgQe3"),
    ("cMho3JiHcubrv7bCWAnR9wnmpqeojmZjfiVTwaz41sMfkJcrjBBf", "tmYXV6wTaooc6ao1Vo4EymBMHYWiKtD7k68"),
    ("cRsvkjsxiMfB8eYmmaSrq9gunXtdqFCVDa5WVJvwiNy3CFSjbeJv", "tmPmQ89SSiRnyRMsKfKssfBTZbKMVYvkDRN"),
    ("cN5H1qu1HPBiuCHg8fJhqnbsJfAVgxpVubSLHM4E1wWTKSNuQYVt", "tmGipSp5k6bkGJHe4GuAoQa1y9ZG34kZ1kM"),
    ("cQtxddFPRoSGhsc12D2aTdz8FwGdcSKmWFBbPfN5cFv4onmes2aH", "tmW7yCZY1C4Hr31tcBmCDzDUjU7uLPtzyB9"),
]


def wait_until(predicate, wait=0.25, timeout=60):
    deadline = time.time() + timeout
    while time.time() <= deadline:
        if predicate():
            return True
        time.sleep(wait)
    raise AssertionError("timed out waiting for condition")


def zcashd_nuparams_args(activation_heights):
    return [
        "-nuparams=%s" % nuparam
        for nuparam in render_regtest_nuparams(activation_heights)
    ]


def zcashd_dir(dirname, i):
    return os.path.join(dirname, "zcashd" + str(i))


def _reap_existing_process(processes, i):
    if i not in processes:
        return
    process = processes[i]
    if process.poll() is None:
        # Still running (e.g. zebrad surviving a zcashd-only shutdown such as
        # encryptwallet); both zebrad and zcashd exit cleanly on SIGTERM.
        process.terminate()
    try:
        process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    del processes[i]


def _split_compat_args(extra_args):
    if extra_args is None:
        return ZebraArgs(), []
    if isinstance(extra_args, ZebraArgs):
        return ZebraArgs() + extra_args, []
    if not isinstance(extra_args, (list, tuple)):
        raise ValueError("zcashd-compat profile expects ZebraArgs or zcashd argument list")

    zebra_args = ZebraArgs()
    zcashd_args = []
    for arg in extra_args:
        if not isinstance(arg, str):
            raise ValueError("zcashd-compat zcashd arguments must be strings")
        if arg.startswith("-nuparams="):
            branch_id, height = arg.split("=", 1)[1].split(":", 1)
            nu_name = _BRANCH_ID_TO_NU_NAME.get(branch_id.lower())
            if nu_name is None:
                raise ValueError("unknown zcashd-compat nuparams branch id " + branch_id)
            zebra_args.activation_heights[nu_name] = int(height)
        else:
            zcashd_args.append(arg)
    return zebra_args, zcashd_args


def _copy_legacy_zcash_conf(dirname, i, f):
    legacy_conf = os.path.join(node_dir(dirname, i), "zcash.conf")
    if not os.path.exists(legacy_conf):
        return

    with open(legacy_conf, "r", encoding="utf8") as legacy_file:
        for line in legacy_file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0]
            if key not in _BASE_ZCASH_CONF_KEYS:
                f.write(line)


def initialize_zcashd_datadir(dirname, i, activation_heights):
    datadir = zcashd_dir(dirname, i)
    os.makedirs(datadir, exist_ok=True)
    with open(os.path.join(datadir, "zcash.conf"), "w", encoding="utf8") as f:
        f.write("regtest=1\n")
        f.write("showmetrics=0\n")
        f.write("rpcuser=%s\n" % ZCASHD_COMPAT_RPC_USERNAME)
        f.write("rpcpassword=%s\n" % ZCASHD_COMPAT_RPC_PASSWORD)
        f.write("rpcport=%d\n" % zcashd_rpc_port(i))
        f.write("port=%d\n" % (p2p_port(i) + 1000))
        f.write("listen=0\n")
        f.write("listenonion=0\n")
        _copy_legacy_zcash_conf(dirname, i, f)
    return datadir


def wait_for_zcashd_start(process, url, i):
    deadline = time.time() + PROC_START_TIMEOUT
    while True:
        if process.poll() is not None:
            raise Exception("%s node %d exited with status %i during initialization" % (zcashd_binary(), i, process.returncode))
        if time.time() > deadline:
            raise Exception("%s node %d failed to become ready within %d seconds" % (zcashd_binary(), i, PROC_START_TIMEOUT))
        try:
            rpc = get_rpc_auth_proxy(url, i)
            rpc.getblockcount()
            break
        except IOError as e:
            if e.errno != errno.ECONNREFUSED:
                raise
        except JSONRPCException as e:
            if e.error["code"] != -28:
                raise
        time.sleep(0.25)


def start_zebrad(i, dirname, zebra_args, rpchost=None, timewait=None, stderr=None):
    _reap_existing_process(bitcoind_processes, i)
    datadir = node_dir(dirname, i)
    config = update_zebrad_conf(datadir, rpc_port(i), p2p_port(i), indexer_rpc_port(i), zebra_args)
    args = [zebrad_binary(), "-c=" + config, "start"]

    bitcoind_processes[i] = subprocess.Popen(args, stderr=stderr)
    if os.getenv("PYTHON_DEBUG", ""):
        print("start_zebrad: zebrad started, waiting for RPC to come up")
    url = rpc_url(i, rpchost)
    wait_for_zebrad_start(bitcoind_processes[i], url, i)
    if os.getenv("PYTHON_DEBUG", ""):
        print("start_zebrad: RPC successfully started for node {} with pid {}".format(i, bitcoind_processes[i].pid))
    proxy = get_rpc_proxy(url, i, timeout=timewait)
    if COVERAGE_DIR:
        coverage.write_all_rpc_commands(COVERAGE_DIR, proxy)
    return proxy


def start_zcashd(i, dirname, zebra_rpc_url, activation_heights, zcashd_args=None, rpchost=None, timewait=None, stderr=None):
    _reap_existing_process(zcashd_processes, i)
    datadir = initialize_zcashd_datadir(dirname, i, activation_heights)
    args = [
        zcashd_binary(),
        "-datadir=" + datadir,
        "-keypool=1",
        "-discover=0",
        "-maxtipage=9999999999",
        "-rest",
        "-allowdeprecated=getnewaddress",
        "-i-am-aware-zcashd-will-be-replaced-by-zebrad-and-zallet-in-2025",
        "-zebra-compat",
        "-zebra-compat-url=" + zebra_rpc_url,
        "-zebra-compat-rpc-user=" + ZCASHD_COMPAT_RPC_USERNAME,
        "-zebra-compat-rpc-password=" + ZCASHD_COMPAT_RPC_PASSWORD,
        "-zebra-compat-poll-interval=1",
    ]
    args.extend(zcashd_nuparams_args(activation_heights))
    args.extend(zcashd_args or [])

    zcashd_processes[i] = subprocess.Popen(args, stderr=stderr)
    if os.getenv("PYTHON_DEBUG", ""):
        print("start_zcashd: zcashd started, waiting for RPC to come up")
    url = zcashd_rpc_url(i, rpchost)
    wait_for_zcashd_start(zcashd_processes[i], url, i)
    if os.getenv("PYTHON_DEBUG", ""):
        print("start_zcashd: RPC successfully started for node {} with pid {}".format(i, zcashd_processes[i].pid))
    proxy = get_rpc_auth_proxy(url, i, timeout=timewait)
    if COVERAGE_DIR:
        coverage.write_all_rpc_commands(COVERAGE_DIR, proxy)
    return proxy


def wait_for_compat_tip(node, timeout=60):
    def fully_ready():
        info = node.zcashd.getzebracompatinfo()
        zebra_tip = node.zebra.getbestblockhash()
        return (
            info["service_state"] == "ready" and
            info["sync"]["state"] == "synced" and
            info["zebra"]["bestblockhash"] == zebra_tip and
            info["local"]["bestblockhash"] == zebra_tip
        )

    wait_until(fully_ready, timeout=timeout)


def wait_for_node_shutdown(i):
    processes = zcashd_processes if zcashd_compat_enabled() else bitcoind_processes
    wait_or_kill(processes[i])
    del processes[i]


def import_miner_key(node, i, rescan):
    try:
        node.zcashd.importprivkey(MINER_KEYS[i][0], "", rescan)
    except JSONRPCException as e:
        message = e.error.get("message", "")
        if (
            "already" in message.lower() or
            "walletpassphrase" in message.lower() or
            "wallet is locked" in message.lower()
        ):
            return
        raise


class CompatNode:
    def __init__(self, zebra, zcashd):
        self.zebra = zebra
        self.zcashd = zcashd
        self.url = zcashd.url

    def __getattr__(self, name):
        if name in ("addnode", "getpeerinfo", "disconnectnode", "getaddednodeinfo"):
            return getattr(self.zebra, name)
        return getattr(self.zcashd, name)

    def generate(self, *args, **kwargs):
        result = self.zebra.generate(*args, **kwargs)
        wait_for_compat_tip(self)
        return result

    def stop(self):
        for proxy, label in ((self.zcashd, "zcashd"), (self.zebra, "zebrad")):
            try:
                proxy.stop()
            except Exception as e:
                print("WARN: Unable to stop %s: %r" % (label, e))


def start_compat_pair(i, dirname, extra_args=None, rpchost=None, timewait=None, stderr=None):
    zebra_args, zcashd_args = _split_compat_args(extra_args)
    zebra_args.miner_address = MINER_KEYS[i][1]
    zebra = start_zebrad(i, dirname, zebra_args, rpchost, timewait, stderr)
    zcashd = start_zcashd(i, dirname, rpc_url(i, rpchost), zebra_args.activation_heights, zcashd_args, rpchost, timewait, stderr)
    node = CompatNode(zebra, zcashd)
    wait_for_compat_tip(node)
    import_miner_key(node, i, zebra.getblockcount() > 0)
    return node
