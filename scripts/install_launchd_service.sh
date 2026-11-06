#!/bin/bash
# ==============================================================================
# Installer for 24/7 Job Finder & Applier Background Service (LaunchAgent)
# ==============================================================================

PLIST_NAME="com.adarsh.ai_auto_applier.plist"
SRC_PLIST="$(dirname "$0")/$PLIST_NAME"
DEST_PLIST="$HOME/Library/LaunchAgents/$PLIST_NAME"

ACTION="${1:-install}"

if [ "$ACTION" == "install" ]; then
    echo "[*] Installing LaunchAgent to $DEST_PLIST..."
    mkdir -p "$HOME/Library/LaunchAgents"
    cp "$SRC_PLIST" "$DEST_PLIST"
    
    # Unload first if already loaded
    launchctl unload "$DEST_PLIST" 2>/dev/null || true
    launchctl load "$DEST_PLIST"
    
    echo "[✓] LaunchAgent loaded successfully."
    echo "[*] Daemon is now running 24/7 in background with auto-restart on boot."
    echo "[*] View live logs via:"
    echo "    tail -f /Users/adarsh/job_finder_applier/data/daemon_stdout.log"

elif [ "$ACTION" == "uninstall" ] || [ "$ACTION" == "stop" ]; then
    echo "[*] Stopping and unloading LaunchAgent..."
    launchctl unload "$DEST_PLIST" 2>/dev/null || true
    if [ "$ACTION" == "uninstall" ]; then
        rm -f "$DEST_PLIST"
        echo "[✓] Uninstalled LaunchAgent."
    else
        echo "[✓] Stopped LaunchAgent."
    fi

elif [ "$ACTION" == "status" ]; then
    launchctl list | grep "com.adarsh.ai_auto_applier" || echo "[-] Service not currently running."

else
    echo "Usage: $0 [install|stop|uninstall|status]"
fi
