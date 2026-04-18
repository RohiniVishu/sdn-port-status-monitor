#!/usr/bin/env python3
"""
Port Status Dashboard
======================
Live terminal dashboard that reads logs/port_stats.json
and logs/port_events.log, refreshes every 2 seconds.

Usage:
    python3 tools/dashboard.py
"""

import json
import os
import sys
import time
import datetime

STAT_FILE   = os.path.join(os.path.dirname(__file__), '..', 'logs', 'port_stats.json')
EVENT_LOG   = os.path.join(os.path.dirname(__file__), '..', 'logs', 'port_events.log')
REFRESH_SEC = 2
MAX_EVENTS  = 15   # lines to show from event log


def clear():
    os.system('clear' if os.name != 'nt' else 'cls')


def load_stats():
    try:
        with open(STAT_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def last_events(n=MAX_EVENTS):
    try:
        with open(EVENT_LOG) as f:
            lines = f.readlines()
        return lines[-n:]
    except Exception:
        return []


def state_color(state):
    """ANSI color codes for terminal."""
    if state == 'UP':
        return '\033[92m'    # green
    elif state == 'DOWN':
        return '\033[91m'    # red
    else:
        return '\033[93m'    # yellow


RESET = '\033[0m'
BOLD  = '\033[1m'
CYAN  = '\033[96m'
WHITE = '\033[97m'


def render(stats, events):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"{BOLD}{CYAN}{'═'*70}{RESET}")
    print(f"{BOLD}{CYAN}  SDN Port Status Monitor Dashboard          {WHITE}{now}{RESET}")
    print(f"{BOLD}{CYAN}{'═'*70}{RESET}")

    if not stats:
        print("  Waiting for controller data …")
    else:
        for dpid, ports in stats.items():
            print(f"\n  {BOLD}Switch dpid={dpid}{RESET}")
            print(f"  {'Port':>6}  {'Name':<14}  {'State':<6}  "
                  f"{'RX Pkts':>10}  {'TX Pkts':>10}  "
                  f"{'RX Bytes':>12}  {'TX Bytes':>12}  Last Change")
            print(f"  {'─'*6}  {'─'*14}  {'─'*6}  "
                  f"{'─'*10}  {'─'*10}  {'─'*12}  {'─'*12}  {'─'*19}")
            for pno, info in sorted(ports.items(), key=lambda x: int(x[0])):
                col   = state_color(info.get('state', '?'))
                state = info.get('state', '?')
                print(
                    f"  {int(pno):>6}  {info.get('name','?'):<14}  "
                    f"{col}{state:<6}{RESET}  "
                    f"{info.get('rx_pkts',0):>10,}  {info.get('tx_pkts',0):>10,}  "
                    f"{info.get('rx_bytes',0):>12,}  {info.get('tx_bytes',0):>12,}  "
                    f"{str(info.get('last_change',''))[:19]}"
                )

    print(f"\n{BOLD}  Recent Events (last {MAX_EVENTS}){RESET}")
    print(f"  {'─'*66}")
    for line in events:
        line = line.rstrip()
        if 'ALERT' in line or 'DOWN' in line:
            print(f"\033[91m  {line}{RESET}")
        elif 'UP' in line or 'ADD' in line:
            print(f"\033[92m  {line}{RESET}")
        else:
            print(f"  {line}")

    print(f"\n{CYAN}  Refreshing every {REFRESH_SEC}s — Ctrl+C to exit{RESET}")


def main():
    print("Starting dashboard …")
    try:
        while True:
            clear()
            render(load_stats(), last_events())
            time.sleep(REFRESH_SEC)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == '__main__':
    main()
