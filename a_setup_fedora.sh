#!/usr/bin/env bash
# =============================================================================
# setup_fedora.sh – Install all dependencies for SDN Port Monitor on Fedora
# =============================================================================
# Run as root or with sudo:
#   sudo bash setup_fedora.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

[[ $EUID -ne 0 ]] && error "Please run as root: sudo bash setup_fedora.sh"

info "=== SDN Port Monitor – Fedora Setup ==="

# System update 
info "Updating system packages …"
dnf update -y -q

# Core dependencies
info "Installing core dependencies …"
dnf install -y -q \
    python3 python3-pip python3-devel \
    git wget curl \
    net-tools iproute \
    openvswitch \
    iperf iperf3 \
    wireshark wireshark-cli \
    tcpdump \
    procps-ng \
    make gcc

# Enable and start Open vSwitch
info "Starting Open vSwitch …"
systemctl enable openvswitch --now || warn "openvswitch may already be running"
sleep 2
ovs-vsctl show && info "OVS is running ✓" || error "OVS failed to start"

# Python packages
info "Installing Python packages …"
pip3 install --quiet --upgrade pip
pip3 install --quiet \
    os-ken \
    mininet \
    eventlet \
    oslo.config \
    webob


# Mininet
info "Installing Mininet from source …"
if ! command -v mn &>/dev/null; then
    TMPDIR=$(mktemp -d)
    git clone --depth=1 https://github.com/mininet/mininet "$TMPDIR/mininet"
    cd "$TMPDIR/mininet"
    bash util/install.sh -n     # install Mininet only (no OVS, we already have it)
    cd -
    rm -rf "$TMPDIR"
fi
mn --version && info "Mininet installed ✓" || warn "mn command not found; try reloading shell"

# Kernel module
info "Loading openvswitch kernel module …"
modprobe openvswitch 2>/dev/null || warn "openvswitch module already loaded"

#  Project structure 
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$SCRIPT_DIR/logs"
info "Log directory: $SCRIPT_DIR/logs"

# Permissions 
info "Adding current user to wireshark group …"
SUDO_USER_REAL="${SUDO_USER:-$USER}"
usermod -aG wireshark "$SUDO_USER_REAL" 2>/dev/null || true

# Verify
info "=== Verification ==="
echo "Python   : $(python3 --version)"
echo "pip      : $(pip3 --version)"
echo "OVS      : $(ovs-vsctl --version | head -1)"
echo "Mininet  : $(mn --version 2>&1)"
echo "Ryu      : $(python3 -c 'import ryu; print(ryu.__version__)' 2>/dev/null || echo 'check import')"
echo "iperf    : $(iperf --version 2>&1 | head -1)"

info "=== Setup complete ==="
info "Reboot or run: newgrp wireshark"
info "Then follow README.md to start the controller and topology."
