#!/usr/bin/env python3
"""
CBLite Browser - Live Document Viewer Server

A Couchbase Capella-style document browser for Couchbase Lite (.cblite2) databases
running on Android emulators.

Features:
  - Background thread pulls databases from emulators every N seconds
  - /api/data endpoint serves fresh document data as JSON
  - /api/status health check endpoint
  - Serves the static HTML/JS viewer UI

Requirements:
  - cblite CLI (brew tap couchbase/tap && brew install cblite)
  - adb (Android SDK platform-tools)
  - Python 3.6+

Usage:
  python3 server.py                           # Use default config
  python3 server.py --port 9090               # Custom port
  python3 server.py --interval 5              # Pull every 5 seconds
  python3 server.py --app com.myapp           # Custom app package name
  python3 server.py --dbname mydb             # Custom database name
"""

import argparse
import subprocess
import json
import os
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler

# Defaults (overridden by CLI args or environment variables)
DEFAULT_PORT = 8091
DEFAULT_PULL_INTERVAL = 3
DEFAULT_APP_PACKAGE = "com.kitchensync"
DEFAULT_DB_NAME = "kitchensync"
DEFAULT_DB_DIR = "/tmp/cblite_dbs"

# Will be populated by main()
config = {}
latest_data = {}
data_lock = threading.Lock()
last_update_time = 0


def run_cblite(args):
    """Run a cblite CLI command and return stdout."""
    try:
        result = subprocess.run(
            ["cblite"] + args,
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def detect_emulators():
    """Detect running Android emulators via adb."""
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True, text=True, timeout=5
        )
        emulators = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("emulator-") and "device" in line:
                serial = line.split()[0]
                emulators.append(serial)
        return sorted(emulators)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def pull_db(serial, local_path, app_package, db_name):
    """Pull a .cblite2 database from an emulator to local path."""
    try:
        remote_path = f"/data/data/{app_package}/files/{db_name}.cblite2"
        cmd = f'adb -s {serial} shell "run-as {app_package} tar cf - {remote_path}"'
        proc = subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        tar_cmd = ["tar", "xf", "-", "-C", local_path, "--strip-components=5"]
        tar_proc = subprocess.Popen(
            tar_cmd,
            stdin=proc.stdout,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        proc.stdout.close()
        tar_proc.communicate(timeout=5)
        return tar_proc.returncode == 0
    except Exception:
        return False


def get_doc_ids(db_path):
    """Parse document IDs, revisions, sequences from cblite ls -l output."""
    out = run_cblite(["ls", "-l", db_path])
    docs = []
    for line in out.splitlines():
        if line.startswith("Document ID") or not line.strip():
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        seq_str = parts[-2]
        rev_short = parts[-4]
        rev_start = line.find(rev_short)
        doc_id = line[:rev_start].strip()
        try:
            seq = int(seq_str)
        except ValueError:
            seq = 0
        flags_str = parts[-3]
        flags = 0
        if 'd' in flags_str:
            flags |= 1  # deleted
        if 'c' in flags_str:
            flags |= 2  # conflict
        docs.append({"id": doc_id, "seq": seq, "flags": flags})
    return docs


def get_collections(db_path):
    """Get scopes and collections from a cblite database."""
    out = run_cblite(["ls", "-c", db_path])
    if not out:
        return [{"scope": "_default", "collection": "_default"}]
    colls = []
    for line in out.splitlines():
        line = line.strip()
        # Skip empty lines and the header line ("Collection  Docs  Deleted  Expiring")
        if not line or line.startswith("Collection"):
            continue
        name = line.split()[0]
        if '.' in name:
            parts = name.split('.', 1)
            colls.append({"scope": parts[0], "collection": parts[1]})
        else:
            colls.append({"scope": "_default", "collection": name})
    return colls or [{"scope": "_default", "collection": "_default"}]


def export_db(name, db_path):
    """Export all documents from a cblite database as structured data."""
    try:
        collections = get_collections(db_path)
        docs_meta = get_doc_ids(db_path)
        db_docs = []
        for meta in docs_meta:
            doc_id = meta["id"]
            raw = run_cblite(["cat", "--rev", db_path, doc_id])
            try:
                body = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue

            # Get version vector from revision history
            revs_out = run_cblite(["revs", db_path, doc_id])
            vv = ""
            for line in revs_out.splitlines():
                if line.strip().startswith("*"):
                    vv = line.strip()
                    break

            rev_id = body.pop("_rev", "")
            body.pop("_id", None)
            db_docs.append({
                "id": doc_id,
                "rev": rev_id,
                "sequence": meta["seq"],
                "flags": meta["flags"],
                "expiration": 0,
                "versionVector": vv,
                "body": body,
            })

        # Build scope -> collections map
        scopes = {}
        for c in collections:
            s = c["scope"]
            if s not in scopes:
                scopes[s] = []
            scopes[s].append(c["collection"])

        return {"scopes": scopes, "documents": db_docs, "path": db_path}
    except Exception as e:
        print(f"  Error exporting {name}: {e}")
        return None


def get_emulator_label(serial, index):
    """Generate a human-readable label for an emulator."""
    # Map common port numbers to roles (convention from KitchenSync demo)
    role_map = {
        "emulator-5554": "Manager",
        "emulator-5556": "Kitchen",
        "emulator-5558": "Kiosk",
    }
    if serial in role_map:
        return f"{role_map[serial]} ({serial})"
    return f"Device-{index + 1} ({serial})"


def refresh_cycle():
    """Background thread: pull DBs from emulators and re-export."""
    global latest_data, last_update_time
    app_package = config["app_package"]
    db_name = config["db_name"]
    db_dir = config["db_dir"]
    interval = config["interval"]

    while True:
        try:
            emulators = detect_emulators()
            new_data = {}
            for i, serial in enumerate(emulators):
                label = get_emulator_label(serial, i)
                local_path = os.path.join(
                    db_dir,
                    serial.replace("-", "_") + ".cblite2"
                )
                os.makedirs(local_path, exist_ok=True)

                pulled = pull_db(serial, local_path, app_package, db_name)
                db_file = os.path.join(local_path, "db.sqlite3")
                if pulled or os.path.exists(db_file):
                    result = export_db(label, local_path)
                    if result:
                        new_data[label] = result

            if new_data:
                with data_lock:
                    latest_data = new_data
                    last_update_time = time.time()
        except Exception as e:
            print(f"Refresh error: {e}")
        time.sleep(interval)


class ViewerHandler(SimpleHTTPRequestHandler):
    """HTTP handler that serves static files and API endpoints."""

    def __init__(self, *args, **kwargs):
        viewer_dir = os.path.dirname(os.path.abspath(__file__))
        super().__init__(*args, directory=viewer_dir, **kwargs)

    def do_GET(self):
        if self.path == "/api/data":
            with data_lock:
                payload = json.dumps({
                    "data": latest_data,
                    "timestamp": last_update_time
                })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(payload.encode())
        elif self.path == "/api/status":
            emulators = detect_emulators()
            status = {
                "ok": True,
                "lastUpdate": last_update_time,
                "emulators": emulators,
                "config": {
                    "app_package": config["app_package"],
                    "db_name": config["db_name"],
                    "interval": config["interval"],
                }
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode())
        else:
            super().do_GET()

    def log_message(self, format, *args):
        # Suppress routine request logs, show only errors
        if args and "404" not in str(args[0]) and "500" not in str(args[0]):
            return
        super().log_message(format, *args)


def main():
    global config

    parser = argparse.ArgumentParser(
        description="CBLite Browser - Live document viewer for Couchbase Lite databases"
    )
    parser.add_argument(
        "--port", type=int,
        default=int(os.environ.get("CBLITE_PORT", DEFAULT_PORT)),
        help=f"Server port (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--interval", type=int,
        default=int(os.environ.get("CBLITE_INTERVAL", DEFAULT_PULL_INTERVAL)),
        help=f"Pull interval in seconds (default: {DEFAULT_PULL_INTERVAL})"
    )
    parser.add_argument(
        "--app", dest="app_package",
        default=os.environ.get("CBLITE_APP_PACKAGE", DEFAULT_APP_PACKAGE),
        help=f"Android app package name (default: {DEFAULT_APP_PACKAGE})"
    )
    parser.add_argument(
        "--dbname", dest="db_name",
        default=os.environ.get("CBLITE_DB_NAME", DEFAULT_DB_NAME),
        help=f"Couchbase Lite database name (default: {DEFAULT_DB_NAME})"
    )
    parser.add_argument(
        "--dbdir", dest="db_dir",
        default=os.environ.get("CBLITE_DB_DIR", DEFAULT_DB_DIR),
        help=f"Local directory for pulled databases (default: {DEFAULT_DB_DIR})"
    )
    args = parser.parse_args()

    config = {
        "port": args.port,
        "interval": args.interval,
        "app_package": args.app_package,
        "db_name": args.db_name,
        "db_dir": args.db_dir,
    }

    # Ensure DB directory exists
    os.makedirs(config["db_dir"], exist_ok=True)

    # Initial export from existing local copies
    print(f"CBLite Browser")
    print(f"  App package : {config['app_package']}")
    print(f"  DB name     : {config['db_name']}")
    print(f"  Pull interval: {config['interval']}s")
    print()

    emulators = detect_emulators()
    if emulators:
        print(f"Found {len(emulators)} emulator(s): {', '.join(emulators)}")
        for i, serial in enumerate(emulators):
            label = get_emulator_label(serial, i)
            local_path = os.path.join(
                config["db_dir"],
                serial.replace("-", "_") + ".cblite2"
            )
            os.makedirs(local_path, exist_ok=True)
            pulled = pull_db(serial, local_path, config["app_package"], config["db_name"])
            db_file = os.path.join(local_path, "db.sqlite3")
            if pulled or os.path.exists(db_file):
                result = export_db(label, local_path)
                if result:
                    latest_data[label] = result
                    print(f"  {label}: {len(result['documents'])} docs")
                else:
                    print(f"  {label}: export failed")
            else:
                print(f"  {label}: pull failed (app may not be installed)")
    else:
        print("No emulators found. Server will wait for emulators to appear.")

    global last_update_time
    last_update_time = time.time()

    # Start background refresh thread
    t = threading.Thread(target=refresh_cycle, daemon=True)
    t.start()

    print(f"\nServer running at http://localhost:{config['port']}")
    print(f"Auto-refreshing from emulators every {config['interval']}s")
    print("Press Ctrl+C to stop\n")

    server = HTTPServer(("", config["port"]), ViewerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
