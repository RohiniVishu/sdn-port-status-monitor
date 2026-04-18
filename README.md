

# SDN Port Status Monitoring Tool

**SDN Assignment | OpenFlow 1.3 | OSKen Controller | Mininet | Fedora**

---

## Problem Statement

In traditional networks, detecting port failures requires physical inspection or SNMP polling.

In an SDN environment, the controller receives real-time **PortStatus** messages from every switch whenever a port changes state (up/down/add/delete).

This project implements a **Port Status Monitoring Tool** that provides:

| Feature | Detail |
|--------|--------|
| Detect port up/down events | `OFPPortStatus` handler in OSKen |
| Log all changes | Timestamped entries in `logs/port_events.log` |
| Generate alerts | Console and log alerts on state changes |
| Display status | Live terminal dashboard + JSON stats snapshot |
| Learning switch | `packet_in → MAC table → explicit flow rules` |

---

## Project Structure

```
sdn-port-monitor/
├── a_port_monitor.py      # OSKen controller (main logic)
├── a_topology.py          # Mininet topology (3 switches, 6 hosts)
├── a_test_scenarios.py    # Automated test suite (2+ scenarios)
├── a_dashboard.py         # Live terminal dashboard
├── a_logs/                # Auto-created at runtime
│   ├── port_events.log
│   ├── port_stats.json
│   └── test_results.log
├── setup_fedora.sh        # One-shot dependency installer
└── README.md
````

---

## Topology

```
h1(10.0.0.1) ─┐
h2(10.0.0.2) ─┤── s1 ─────── s2 ─────── s3 ─┬─ h5(10.0.0.5)
h3(10.0.0.3) ─┘               │              └─ h6(10.0.0.6)
                              h4(10.0.0.4)
```

* 3 OVS switches speaking OpenFlow 1.3
* 6 hosts across three switches
* TCLink:

  * 100 Mbps host links
  * 1 Gbps inter-switch links
  * 2 ms delay
* OSKen RemoteController on `127.0.0.1:6633`

---

## SDN Logic & Flow Rules

### Controller Events Handled

| Event                    | Dispatcher | Purpose                                       |
| ------------------------ | ---------- | --------------------------------------------- |
| `EventOFPSwitchFeatures` | `CONFIG`   | Install table-miss rule (priority 0)          |
| `EventOFPPacketIn`       | `MAIN`     | MAC learning + install flow rule (priority 1) |
| `EventOFPPortStatus`     | `MAIN`     | Detect and log port changes, generate alerts  |
| `EventOFPPortStatsReply` | `MAIN`     | Update RX/TX counters                         |
| `EventOFPStateChange`    | `DEAD`     | Log switch disconnect                         |

### Flow Rule Design

| Priority       | Match                         | Action        | Timeout     |
| -------------- | ----------------------------- | ------------- | ----------- |
| 0 (table-miss) | any                           | CONTROLLER    | permanent   |
| 1 (learned)    | `in_port + eth_dst + eth_src` | `OUTPUT port` | `idle=30 s` |

---

## Setup / Execution Steps

### 1. Install dependencies (Fedora, one-time)

```
git clone https://github.com/<YOUR_USERNAME>/sdn_port_monitor.git
cd sdn_port_monitor
sudo bash setup_fedora.sh
```

### 2. Clean any leftover Mininet state

```
sudo mn --clean
sudo systemctl restart openvswitch
```

### 3. Terminal A: Start the OSKen controller

```
os-ken-manager controller/port_monitor.py --verbose
```

Expected output:

```
PortMonitorController started. Log → logs/port_events.log
[SWITCH CONNECTED] dpid=0000000000000001
[SWITCH CONNECTED] dpid=0000000000000002
[SWITCH CONNECTED] dpid=0000000000000003
```

### 4. Terminal B: Start the Mininet topology

```
sudo python3 topology/topology.py
```

### 5. Terminal C (optional): Live dashboard

```
python3 tools/dashboard.py
```

### 6. Run automated tests

OSKen must already be running in Terminal A.

```
sudo python3 tests/test_scenarios.py
```

---

## Expected Output

### Normal ping (all pairs reachable)

```
mininet> pingall
*** Results: 0% dropped (30/30 received)
```

### Port failure alert (controller terminal)

```
*** ALERT: PORT STATUS CHANGE ***

Time      : 2025-04-18 14:22:05
Switch    : dpid=0000000000000001
Port No   : 3
Port Name : s1-eth3
Reason    : MODIFY
State     : UP → DOWN
============================================================
```

### Flow table after learning

```
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
```

Example output:

```
cookie=0x0, priority=1, in_port=1,dl_src=00:00:00:00:00:01,dl_dst=00:00:00:00:00:04 actions=output:3
cookie=0x0, priority=0, actions=CONTROLLER:65535
```

### iperf throughput

```
[ ID] Interval       Transfer     Bandwidth
[  3] 0.0-10.0 sec   1.10 GBytes   943 Mbits/sec
```

### Automated test results

```
─────────────────────────────────────────────────────────────
TEST SUMMARY
─────────────────────────────────────────────────────────────
connectivity         PASS
port_failure         PASS
throughput           PASS
─────────────────────────────────────────────────────────────
Overall: ALL TESTS PASSED 
```

---

## Test Scenarios

### Scenario 1 – Allowed vs Blocked (Connectivity)

| Step               | Command                        | Expected           |
| ------------------ | ------------------------------ | ------------------ |
| Full mesh ping     | `mininet> pingall`             | 0% drop            |
| Single pair        | `h1 ping -c4 h6`               | 0% drop, RTT ~5 ms |
| After link down    | `link s1 s2 down → h1 ping h4` | 100% drop          |
| After link restore | `link s1 s2 up → h1 ping h4`   | 0% drop            |

### Scenario 2 – Normal vs Failure (Port Events)

| Step             | What to observe                                       |
| ---------------- | ----------------------------------------------------- |
| Bring link down  | Controller logs `ALERT: DOWN` for affected port       |
| Check flow table | `ovs-ofctl dump-flows s1` shows stale rules aging out |
| Bring link up    | Controller logs `ALERT: UP`, traffic recovers         |
| Port stats       | `ovs-ofctl dump-ports s1` shows error counters        |

---

## Proof of Execution

Screenshots and logs are available in the `logs/` directory after a run:

* `logs/port_events.log` — timestamped port events
* `logs/port_stats.json` — last snapshot of all port counters
* `logs/test_results.log` — automated test run output

---

## Capture with Wireshark / tcpdump

Capture OpenFlow messages on loopback (controller ↔ switch):

```
sudo tcpdump -i lo -w logs/openflow_capture.pcap port 6633
```

Or open Wireshark GUI:

```
sudo wireshark -k -i lo -f "port 6633"
```

In Wireshark, filter with:

```
openflow_v4
```

You should see:

* `OFPT_PORT_STATUS` messages (port events)
* `OFPT_PACKET_IN` messages (new MAC → controller)
* `OFPT_FLOW_MOD` messages (controller installing rules)

---

## Tools Used

| Tool                | Purpose                  |
| ------------------- | ------------------------ |
| Mininet             | Network emulation        |
| Open vSwitch        | Software OpenFlow switch |
| OSKen               | OpenFlow 1.3 controller  |
| iperf               | Throughput measurement   |
| Wireshark / tcpdump | OpenFlow packet capture  |
| ovs-ofctl           | Flow table inspection    |

---

## References

1. Mininet documentation – [http://mininet.org/](http://mininet.org/)
2. OSKen SDN Framework – [https://docs.openstack.org/os-ken/latest/](https://docs.openstack.org/os-ken/latest/)
3. Ryu – [https://ryu.readthedocs.io/](https://ryu.readthedocs.io/)
4. OpenFlow 1.3 Specification – [https://opennetworking.org/wp-content/uploads/2014/10/openflow-spec-v1.3.0.pdf](https://opennetworking.org/wp-content/uploads/2014/10/openflow-spec-v1.3.0.pdf)
5. Open vSwitch – [https://www.openvswitch.org/](https://www.openvswitch.org/)
6. McKeown et al., "OpenFlow: Enabling Innovation in Campus Networks," ACM SIGCOMM CCR, 2008.
 
   
## My Outputs:  
### Issues I faced [documentational purposes]:  
1. Ryu, the suggested controller is no longer maintained. Switched to OSKen. OSKen installation requires pip, hence to be done in venv.  
2. Python 3.14 Compatibility: Removed legacy collections aliases and updated function names like early_init_log to oslo_config   
3. Incomplete OS-Ken Installation since the pip installer failed to copy the cmd directory and create entry point binaries. Manually created the os_ken/cmd folder and the osken-manager executable script.  
4. Missing Ryu Dependencies: OS-Ken (a Ryu fork) requires specific class names and import paths that differ from Ryu. Renamed functions like RyuApp to OsKenApp and updated imports from ryu. to os_ken.   
5. Kernel sch_htb Warnings: High bandwidth settings (1000Mbps) triggered scheduler errors on virtual links. Didnt clear the mininet sessions in the beginning. Removed bw and delay constraints to bypass the TCLink scheduler issues.  
6. Environment Path Conflicts: The osken-manager command was not found in the system's global search path. Installed everything inside a dedicated sdn_env virtual environment for isolated pathing.  
7. Controller App Path Errors: OS-Ken failed to load relative paths (../) due to Python's relative import security. Used absolute paths (via realpath) to point the controller to the monitor script and bypass existing pointers.  
   
