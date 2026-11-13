#!/bin/bash
# ==============================================================================
# Mac Hardware & Power Preservation Setup for 24/7 Background Operation
# Target Machine: Apple Silicon Mac mini (macOS Darwin arm64)
# ==============================================================================

echo "========================================================================"
echo "[*] CONFIGURING MAC HARDWARE & POWER MANAGEMENT FOR 24/7 EXECUTION"
echo "========================================================================"

# 1. Kill any legacy caffeinate process that blocks display sleep
echo "[Step 1] Auditing caffeinate assertions..."
ROGUE_CAFFEINATE=$(pgrep -f "caffeinate -dims" || true)
if [ -n "$ROGUE_CAFFEINATE" ]; then
    echo "  [!] Found rogue caffeinate with display lock (PIDs: $ROGUE_CAFFEINATE). Terminating..."
    kill -9 $ROGUE_CAFFEINATE 2>/dev/null || true
    echo "  [✓] Terminated. Display sleep lock cleared."
else
    echo "  [✓] No rogue caffeinate display-lock processes detected."
fi

# 2. Display current power management settings
echo ""
echo "[Step 2] Current System Power Settings:"
pmset -g | grep -E "sleep|displaysleep|disksleep|powernap|womp|tcpkeepalive"

echo ""
echo "[Step 3] Recommended Power Commands for 24/7 Operation:"
echo "  To let your monitor sleep after 5 minutes (saving monitor chips/pixels)"
echo "  while keeping the Mac mini in ultra-low-power idle (~2W) for the 24/7 daemon:"
echo ""
echo "    sudo pmset -a displaysleep 5"
echo "    sudo pmset -a sleep 0"
echo "    sudo pmset -a disksleep 10"
echo "    sudo pmset -a womp 1"
echo "    sudo pmset -a tcpkeepalive 1"
echo ""

# 3. Run hardware & memory flush
echo "[Step 4] Running hardware & memory flush..."
python3 "$(dirname "$0")/../cli.py" flush

echo "========================================================================"
echo "[✓] Hardware preservation audit complete."
echo "========================================================================"
