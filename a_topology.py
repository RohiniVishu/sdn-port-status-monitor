#!/usr/bin/env python3
"""
Mininet Topology for SDN Port Status Monitoring
================================================
Topology (linear, 3 switches, 6 hosts):

  h1 ─┐                    ┌─ h5
  h2 ─┤─ s1 ─── s2 ─── s3 ─┤
  h3 ─┘         |           └─ h6
                h4

Each switch connects to the osken controller on 127.0.0.1:6633.

Usage:
    sudo python3 topology.py

Requirements:
    mininet, osken (controller must already be running)
"""

from mininet.net  import Mininet
from mininet.node import OVSKernelSwitch, RemoteController
from mininet.cli  import CLI
from mininet.log  import setLogLevel, info
from mininet.link import TCLink
import time
import sys


def build_topology():
    """Build and return the Mininet network."""

    net = Mininet(
        switch=OVSKernelSwitch,
        controller=RemoteController,
        link=TCLink,          # supports bw/delay parameters
        autoSetMacs=True,     # deterministic MACs: 00:00:00:00:00:01 …
    )

    info('\n*** Adding osken controller\n')
    c0 = net.addController(
        'c0',
        controller=RemoteController,
        ip='127.0.0.1',
        port=6633
    )

    info('*** Adding switches\n')
    s1 = net.addSwitch('s1', protocols='OpenFlow13')
    s2 = net.addSwitch('s2', protocols='OpenFlow13')
    s3 = net.addSwitch('s3', protocols='OpenFlow13')

    info('*** Adding hosts\n')
    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')
    h5 = net.addHost('h5', ip='10.0.0.5/24')
    h6 = net.addHost('h6', ip='10.0.0.6/24')

    info('*** Adding links\n')
    # Host–switch links (100 Mbps, 2 ms delay)
    net.addLink(h1, s1, bw=100, delay='2ms')
    net.addLink(h2, s1, bw=100, delay='2ms')
    net.addLink(h3, s1, bw=100, delay='2ms')
    net.addLink(h4, s2, bw=100, delay='2ms')
    net.addLink(h5, s3, bw=100, delay='2ms')
    net.addLink(h6, s3, bw=100, delay='2ms')

    # Switch–switch inter-links (1 Gbps, 1 ms delay)
    net.addLink(s1, s2, bw=1000, delay='1ms')
    net.addLink(s2, s3, bw=1000, delay='1ms')

    return net, c0


def run():
    setLogLevel('info')

    net, c0 = build_topology()

    info('\n*** Starting network\n')
    net.start()

    info('\n*** Waiting 3 s for controller to install flows …\n')
    time.sleep(3)

    info('\n*** Verifying OVS OpenFlow version\n')
    for sw in ['s1', 's2', 's3']:
        net[sw].cmd(f'ovs-vsctl set bridge {sw} protocols=OpenFlow13')

    info('\n')
    info('=' * 60 + '\n')
    info('  Topology ready. Try these commands in the CLI:\n')
    info('\n')
    info('  pingall                      – full mesh ping\n')
    info('  h1 ping -c4 h6               – end-to-end ping\n')
    info('  h1 iperf -s &                – iperf server on h1\n')
    info('  h6 iperf -c 10.0.0.1 -t 10  – throughput test\n')
    info('  sh ovs-ofctl dump-flows s1   – show flow table\n')
    info('\n')
    info('  # Simulate port-down event:\n')
    info('  link s1 s2 down              – bring inter-switch link down\n')
    info('  link s1 s2 up                – restore it\n')
    info('=' * 60 + '\n')

    CLI(net)

    info('\n*** Stopping network\n')
    net.stop()


if __name__ == '__main__':
    run()
