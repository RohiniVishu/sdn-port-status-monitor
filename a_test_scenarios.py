#!/usr/bin/env python3
"""
Automated Test Suite – SDN Port Status Monitoring
===================================================
Scenario 1 : Connectivity test  (allowed vs blocked)
             All-pairs ping → expect 100 % success (learning switch).

Scenario 2 : Port failure test  (normal vs failure)
             Bring s1↔s2 link DOWN → verify h1 cannot reach h4,
             restore link  UP  → verify reachability recovers.

Scenario 3 : iperf throughput baseline

Run:
    sudo python3 tests/test_scenarios.py

Results are printed to stdout AND appended to logs/test_results.log
"""

from mininet.net  import Mininet
from mininet.node import OVSKernelSwitch, RemoteController
from mininet.log  import setLogLevel
from mininet.link import TCLink

import time
import sys
import os
import logging
import re

# Logger
LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'test_results.log')),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('TestSuite')

PASS = "PASS"
FAIL = "FAIL"
SEP  = "─" * 60


def build_net():
    """Minimal version of the project topology (no CLI)."""
    net = Mininet(
        switch=OVSKernelSwitch,
        controller=RemoteController,
        link=TCLink,
        autoSetMacs=True,
    )
    c0 = net.addController('c0', controller=RemoteController,
                            ip='127.0.0.1', port=6653)

    s1 = net.addSwitch('s1', protocols='OpenFlow13')
    s2 = net.addSwitch('s2', protocols='OpenFlow13')
    s3 = net.addSwitch('s3', protocols='OpenFlow13')

    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')
    h5 = net.addHost('h5', ip='10.0.0.5/24')
    h6 = net.addHost('h6', ip='10.0.0.6/24')

    net.addLink(h1, s1, bw=100, delay='2ms')
    net.addLink(h2, s1, bw=100, delay='2ms')
    net.addLink(h3, s1, bw=100, delay='2ms')
    net.addLink(h4, s2, bw=100, delay='2ms')
    net.addLink(h5, s3, bw=100, delay='2ms')
    net.addLink(h6, s3, bw=100, delay='2ms')
    net.addLink(s1, s2, bw=10, delay='1ms')
    net.addLink(s2, s3, bw=10, delay='1ms')

    return net


def ping_test(src, dst, count=4, timeout=2):
    """Return (loss_pct, avg_rtt_ms) from a ping."""
    result = src.cmd(f'ping -c {count} -W {timeout} {dst.IP()}')
    # Parse loss
    loss_match = re.search(r'(\d+)% packet loss', result)
    loss = int(loss_match.group(1)) if loss_match else 100

    # Parse RTT
    rtt_match = re.search(r'rtt min/avg/max/mdev = [\d.]+/([\d.]+)/', result)
    avg_rtt = float(rtt_match.group(1)) if rtt_match else None

    return loss, avg_rtt


def dump_flows(switch):
    """Return flow table string for a switch."""
    return switch.cmd('ovs-ofctl -O OpenFlow13 dump-flows ' + switch.name)


# Scenario 1: All-pairs connectivity

def scenario_1_connectivity(net):
    log.info(SEP)
    log.info("SCENARIO 1 – Full Connectivity (Learning Switch)")
    log.info(SEP)

    hosts = [net[f'h{i}'] for i in range(1, 7)]
    passed = 0
    failed = 0

    for i, src in enumerate(hosts):
        for dst in hosts[i+1:]:
            loss, rtt = ping_test(src, dst, count=3)
            ok = loss == 0
            status = PASS if ok else FAIL
            log.info("  %s → %s  loss=%d%%  rtt=%s ms  %s",
                     src.name, dst.name, loss,
                     f"{rtt:.2f}" if rtt else "N/A", status)
            if ok:
                passed += 1
            else:
                failed += 1

    log.info("  Result: %d/%d pairs reachable", passed, passed + failed)
    return failed == 0


# Scenario 2: Port failure (link down/up)

def scenario_2_port_failure(net):
    log.info(SEP)
    log.info("SCENARIO 2 – Port Failure Detection (s1 ↔ s2 link)")
    log.info(SEP)

    h1 = net['h1']   # behind s1
    h4 = net['h4']   # behind s2

    # 2a) Normal: h1 → h4 should work
    log.info("  [2a] Normal state – h1 → h4")
    loss_before, rtt_before = ping_test(h1, h4, count=3)
    ok_before = loss_before == 0
    log.info("       loss=%d%%  rtt=%s ms  %s",
             loss_before,
             f"{rtt_before:.2f}" if rtt_before else "N/A",
             PASS if ok_before else FAIL)

    # Show flow table BEFORE failure
    log.info("  [FLOW TABLE s1 – BEFORE failure]\n%s", dump_flows(net['s1']))

    # 2b) Bring link DOWN
    log.info("  [2b] Bringing s1 ↔ s2 link DOWN …")
    net.configLinkStatus('s1', 's2', 'down')
    time.sleep(3)   # give controller time to react

    loss_down, _ = ping_test(h1, h4, count=3, timeout=1)
    ok_down = loss_down > 0  # we EXPECT failure
    log.info("       loss=%d%%  (expect >0)  %s",
             loss_down, PASS if ok_down else FAIL)

    # Show flow table AFTER failure (flows should have been removed/changed)
    log.info("  [FLOW TABLE s1 – AFTER link down]\n%s", dump_flows(net['s1']))

    # 2c) Restore link UP
    log.info("  [2c] Restoring s1 ↔ s2 link UP …")
    net.configLinkStatus('s1', 's2', 'up')
    time.sleep(5)   # wait for topology to reconverge

    loss_after, rtt_after = ping_test(h1, h4, count=4)
    ok_after = loss_after == 0
    log.info("       loss=%d%%  rtt=%s ms  %s",
             loss_after,
             f"{rtt_after:.2f}" if rtt_after else "N/A",
             PASS if ok_after else FAIL)

    return ok_before and ok_down and ok_after


# Scenario 3: Throughput measurement 

def scenario_3_throughput(net):
    log.info(SEP)
    log.info("SCENARIO 3 – iperf Throughput (h1 → h6)")
    log.info(SEP)

    h1 = net['h1']
    h6 = net['h6']

    # Start iperf server on h6
    h6.cmd('iperf -s -u -p 5001 &')
    time.sleep(1)

    # Run iperf client from h1 (TCP, 10 seconds)
    result = h1.cmd('iperf -c 10.0.0.6 -p 5001 -t 10 -i 2')
    log.info("  iperf TCP output:\n%s", result)

    # Kill server
    h6.cmd('kill %iperf 2>/dev/null; true')

    # Quick sanity: look for "Gbits/sec" or "Mbits/sec"
    ok = 'bits/sec' in result
    log.info("  Throughput measured: %s", PASS if ok else FAIL)
    return ok


# Port stats dump

def dump_port_stats(net):
    log.info(SEP)
    log.info("PORT STATISTICS (ovs-ofctl)")
    log.info(SEP)
    for sw in ['s1', 's2', 's3']:
        stats = net[sw].cmd(f'ovs-ofctl -O OpenFlow13 dump-ports {sw}')
        log.info("  [%s]\n%s", sw, stats)


# Main

def main():
    setLogLevel('warning')   # suppress Mininet verbosity; our logger handles it

    log.info("=" * 60)
    log.info("  SDN Port Monitor – Automated Test Suite")
    log.info("=" * 60)

    net = build_net()
    net.start()

    # Force OpenFlow 1.3
    for sw in ['s1', 's2', 's3']:
        net[sw].cmd(f'ovs-vsctl set bridge {sw} protocols=OpenFlow13')

    log.info("  Network started. Waiting 4 s for controller …")
    time.sleep(15)

    results = {}

    try:
        results['connectivity']  = scenario_1_connectivity(net)
        results['port_failure']  = scenario_2_port_failure(net)
        results['throughput']    = scenario_3_throughput(net)
        dump_port_stats(net)
    finally:
        net.stop()

    # Summary
    log.info(SEP)
    log.info("TEST SUMMARY")
    log.info(SEP)
    all_pass = True
    for name, ok in results.items():
        status = PASS if ok else FAIL
        log.info("  %-20s %s", name, status)
        if not ok:
            all_pass = False

    log.info(SEP)
    log.info("Overall: %s", "ALL TESTS PASSED" if all_pass else "SOME TESTS FAILED ")
    log.info("Results saved to logs/test_results.log")
    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
