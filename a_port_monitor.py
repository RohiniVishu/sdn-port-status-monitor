"""
SDN Port Status Monitoring Tool
================================
os_ken-based OpenFlow 1.3 controller that:
  - Handles packet_in events (learning switch)
  - Detects port up/down events via PortStatus messages
  - Installs explicit match+action flow rules
  - Logs all events to file and console
  - Generates alerts on port changes
  - Tracks packet/byte counts per port
"""

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from os_ken.controller.handler import set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet, ethernet, ether_types
from os_ken.lib import hub

import datetime
import logging
import os
import json

# Logging setup
LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE  = os.path.join(LOG_DIR, 'port_events.log')
STAT_FILE = os.path.join(LOG_DIR, 'port_stats.json')

# Root logger (writes to file AND console)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('PortMonitor')


# Helper
PORT_REASON = {
    0: 'ADD',
    1: 'DELETE',
    2: 'MODIFY',
}

ALERT_BANNER = "=" * 60


class PortMonitorController(app_manager.OSKenApp):
    """
    Learning switch + port-status monitor.

    Flow rule design
    ----------------
    Priority 0  – table-miss: send to controller (packet_in)
    Priority 1  – per-(dpid, src_mac, in_port) learned entries:
                  match dst_mac → output learned_port
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # { dpid: { mac: port } }   – MAC learning table
        self.mac_to_port = {}

        # { dpid: { port_no: { 'name': str, 'state': str,
        #                       'rx_pkts': int, 'tx_pkts': int,
        #                       'rx_bytes': int, 'tx_bytes': int } } }
        self.port_info = {}

        # Background thread: poll port statistics every 10 s
        self.monitor_thread = hub.spawn(self._port_stats_loop)

        logger.info("PortMonitorController started. Log → %s", LOG_FILE)

    # Switch Handshake

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Install table-miss flow rule on every new switch connection."""
        dp      = ev.msg.datapath
        ofp     = dp.ofproto
        parser  = dp.ofproto_parser

        # Table-miss: match anything → send to controller (no buffer)
        match  = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER,
                                          ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, priority=0, match=match, actions=actions)

        logger.info("[SWITCH CONNECTED] dpid=%016x", dp.id)

        # Seed port_info dict for this datapath
        self.port_info.setdefault(dp.id, {})
        self.mac_to_port.setdefault(dp.id, {})

    # Packet-In (Learning Switch)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg    = ev.msg
        dp     = msg.datapath
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return  # ignore LLDP

        dst = eth.dst
        src = eth.src
        dpid = dp.id

        # Learn source MAC to port
        self.mac_to_port[dpid][src] = in_port
        logger.debug("[LEARN] dpid=%016x  %s → port %s", dpid, src, in_port)

        # Decide output port
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofp.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # Install a proactive flow rule so future packets bypass controller
        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            # idle_timeout=30 keeps table clean; hard_timeout=0 = never expires
            self._add_flow(dp, priority=1, match=match, actions=actions,
                           idle_timeout=30, hard_timeout=0)

        # Forward the current buffered packet
        data = None
        if msg.buffer_id == ofp.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(
            datapath=dp,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data
        )
        dp.send_msg(out)

    # Port Status Events

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, ev):
        """
        Handles OFPPortStatus messages.
        Reason codes: ADD=0, DELETE=1, MODIFY=2
        Port state flag OFPPS_LINK_DOWN=1 means the link is down.
        """
        msg    = ev.msg
        dp     = msg.datapath
        reason = PORT_REASON.get(msg.reason, 'UNKNOWN')
        port   = msg.desc
        dpid   = dp.id

        port_no   = port.port_no
        port_name = port.name.decode('utf-8', errors='replace').rstrip('\x00')

        # Determine link state
        is_down = bool(port.state & dp.ofproto.OFPPS_LINK_DOWN)
        state   = 'DOWN' if is_down else 'UP'

        # Update internal table
        self.port_info.setdefault(dpid, {})
        prev = self.port_info[dpid].get(port_no, {})
        prev_state = prev.get('state', 'UNKNOWN')

        self.port_info[dpid][port_no] = {
            'name'     : port_name,
            'state'    : state,
            'reason'   : reason,
            'rx_pkts'  : prev.get('rx_pkts',  0),
            'tx_pkts'  : prev.get('tx_pkts',  0),
            'rx_bytes' : prev.get('rx_bytes', 0),
            'tx_bytes' : prev.get('tx_bytes', 0),
            'last_change': str(datetime.datetime.now()),
        }

        # Structured log entry
        log_entry = {
            'timestamp' : str(datetime.datetime.now()),
            'dpid'      : format(dpid, '016x'),
            'port_no'   : port_no,
            'port_name' : port_name,
            'reason'    : reason,
            'state'     : state,
        }
        logger.info("[PORT EVENT] %s", json.dumps(log_entry))

        # Alert on state change 
        if prev_state != state or reason in ('ADD', 'DELETE'):
            self._generate_alert(dpid, port_no, port_name, reason,
                                 prev_state, state)

        # Persist snapshot to disk
        self._save_stats()

    # Port Statistics Poll 

    def _port_stats_loop(self):
        """Background greenlet: request port stats from all live datapaths."""
        while True:
            hub.sleep(10)
            for dp in list(self._get_all_datapaths()):
                self._request_port_stats(dp)

    def _get_all_datapaths(self):
        """Return all currently connected os_ken datapaths."""
        from os_ken.base.app_manager import lookup_service_brick
        try:
            wsgi = lookup_service_brick('wsgi')
        except Exception:
            wsgi = None
        # Access internal datapath registry via os_ken hub
        from os_ken.controller.controller import Datapath
        return [v for v in Datapath.instances.values()] if hasattr(Datapath, 'instances') else []

    def _request_port_stats(self, dp):
        """Send OFPPortStatsRequest to a datapath."""
        parser = dp.ofproto_parser
        ofp    = dp.ofproto
        req    = parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY)
        dp.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        """Process OFPPortStatsReply and update counters."""
        dp   = ev.msg.datapath
        dpid = dp.id
        self.port_info.setdefault(dpid, {})

        for stat in ev.msg.body:
            p = self.port_info[dpid].setdefault(stat.port_no, {
                'name': str(stat.port_no), 'state': 'UP', 'reason': 'N/A',
                'rx_pkts': 0, 'tx_pkts': 0, 'rx_bytes': 0, 'tx_bytes': 0,
                'last_change': str(datetime.datetime.now()),
            })
            p['rx_pkts']  = stat.rx_packets
            p['tx_pkts']  = stat.tx_packets
            p['rx_bytes'] = stat.rx_bytes
            p['tx_bytes'] = stat.tx_bytes

        logger.info("[STATS] dpid=%016x  ports_tracked=%d",
                    dpid, len(self.port_info[dpid]))
        self._save_stats()

    # Datapath Disconnect

    @set_ev_cls(ofp_event.EventOFPStateChange, DEAD_DISPATCHER)
    def state_change_handler(self, ev):
        dpid = ev.datapath.id
        logger.warning("[SWITCH DISCONNECTED] dpid=%016x", dpid)

    # Helpers

    def _add_flow(self, dp, priority, match, actions,
                  idle_timeout=0, hard_timeout=0):
        """Utility: build and send OFPFlowMod."""
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        inst   = [parser.OFPInstructionActions(
                      ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=dp,
            priority=priority,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
            match=match,
            instructions=inst
        )
        dp.send_msg(mod)

    def _generate_alert(self, dpid, port_no, port_name,
                        reason, prev_state, new_state):
        """Print a prominent alert to console and log file."""
        ts  = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        msg = (
            f"\n{ALERT_BANNER}\n"
            f"  *** ALERT: PORT STATUS CHANGE ***\n"
            f"  Time      : {ts}\n"
            f"  Switch    : dpid={dpid:016x}\n"
            f"  Port No   : {port_no}\n"
            f"  Port Name : {port_name}\n"
            f"  Reason    : {reason}\n"
            f"  State     : {prev_state}  →  {new_state}\n"
            f"{ALERT_BANNER}\n"
        )
        logger.warning(msg)

    def _save_stats(self):
        """Persist port_info snapshot to JSON for external consumption."""
        snapshot = {
            format(dpid, '016x'): ports
            for dpid, ports in self.port_info.items()
        }
        try:
            with open(STAT_FILE, 'w') as f:
                json.dump(snapshot, f, indent=2, default=str)
        except Exception as e:
            logger.error("Failed to write stats: %s", e)
