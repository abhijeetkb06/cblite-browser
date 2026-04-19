#!/bin/bash
#
# CBLite Browser - Launch Script
#
# A Couchbase Capella-style document browser for Couchbase Lite (.cblite2)
# databases running on Android emulators.
#
# Usage:
#   ./launch.sh                              # Use defaults
#   ./launch.sh --app com.myapp              # Custom app package
#   ./launch.sh --dbname mydb                # Custom database name
#   ./launch.sh --port 9090                  # Custom port
#   ./launch.sh --interval 5                 # Pull every 5 seconds
#
# Prerequisites:
#   - Android emulators running with a Couchbase Lite app installed
#   - cblite CLI (brew tap couchbase/tap && brew install cblite)
#   - Python 3.6+
#   - adb (Android SDK platform-tools)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${CBLITE_PORT:-8091}"

# Parse --port from args for the kill step
for arg in "$@"; do
    if [[ "$prev" == "--port" ]]; then
        PORT="$arg"
    fi
    prev="$arg"
done

# Check prerequisites
check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo "ERROR: $1 not found. $2"
        exit 1
    fi
}

check_command cblite "Install with: brew tap couchbase/tap && brew install cblite"
check_command adb "Make sure Android SDK platform-tools is in your PATH."
check_command python3 "Install Python 3.6+."

# Check for running emulators
EMULATORS=$(adb devices 2>/dev/null | grep "emulator-" | awk '{print $1}')
if [ -z "$EMULATORS" ]; then
    echo "WARNING: No running emulators found. Server will wait for emulators to appear."
fi

# Kill any existing server on the port
if lsof -ti:"$PORT" &>/dev/null; then
    echo "Stopping existing server on port $PORT..."
    kill $(lsof -ti:"$PORT") 2>/dev/null || true
    sleep 1
fi

echo "Starting CBLite Browser on http://localhost:$PORT"
echo ""

# Open browser after a short delay
(sleep 2 && open "http://localhost:$PORT" 2>/dev/null || xdg-open "http://localhost:$PORT" 2>/dev/null) &

# Run the server (foreground, Ctrl+C to stop)
cd "$SCRIPT_DIR"
python3 server.py "$@"
