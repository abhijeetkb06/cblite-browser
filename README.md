# CBLite Browser

A Couchbase Capella-style document browser for **Couchbase Lite** (`.cblite2`) databases running on Android emulators. Browse documents, inspect JSON bodies, and view metadata (version vectors, sequences, revision IDs) in real-time.

![CBLite Browser](https://img.shields.io/badge/Couchbase_Lite-4.x-ea2328) ![Python](https://img.shields.io/badge/Python-3.6+-3776ab) ![License](https://img.shields.io/badge/License-Apache_2.0-green)

## Features

- **Capella-style UI** -- Left sidebar tree (Database > Scope > Collection), document table, modal viewer with JSON and Metadata tabs
- **Live auto-refresh** -- Pulls databases from emulators every N seconds, UI polls for changes every 2 seconds
- **Version vector inspection** -- See version vectors, revision IDs, sequences, and flags per document
- **Multi-emulator support** -- Auto-detects all running Android emulators
- **Configurable** -- Works with any Android app using Couchbase Lite (not just KitchenSync)
- **Zero dependencies** -- Pure Python 3 + single HTML file, no npm/node/frameworks required

## Prerequisites

| Tool | Install |
|------|---------|
| **cblite** CLI | `brew tap couchbase/tap && brew install cblite` |
| **adb** | Android SDK platform-tools (via Android Studio or `brew install android-platform-tools`) |
| **Python 3.6+** | Pre-installed on macOS, or `brew install python3` |
| **Android emulators** | Running with a Couchbase Lite app installed |

## Quick Start

```bash
# Clone the repo
git clone https://github.com/abhijeetkb06/cblite-browser.git
cd cblite-browser

# Make launch script executable
chmod +x launch.sh

# Launch (opens browser automatically)
./launch.sh
```

The browser opens at `http://localhost:8091`.

## Usage

### Default (KitchenSync app)

```bash
./launch.sh
```

### Custom app

```bash
./launch.sh --app com.mycompany.myapp --dbname mydb
```

### All options

```bash
./launch.sh \
  --app com.mycompany.myapp \   # Android app package name
  --dbname mydb \               # Couchbase Lite database name
  --port 9090 \                 # Server port (default: 8091)
  --interval 5                  # Pull interval in seconds (default: 3)
```

### Environment variables

You can also configure via environment variables:

```bash
export CBLITE_APP_PACKAGE=com.mycompany.myapp
export CBLITE_DB_NAME=mydb
export CBLITE_PORT=9090
export CBLITE_INTERVAL=5
./launch.sh
```

### Direct Python

```bash
python3 server.py --app com.mycompany.myapp --dbname mydb
```

## How It Works

```
Android Emulator(s)              CBLite Browser Server              Browser UI
+------------------+         +----------------------+         +------------------+
| App with CBLite  |  adb    | Python HTTP server   |  HTTP   | Capella-style    |
| .cblite2 files   | ------> | + background puller  | ------> | document viewer  |
| in app sandbox   |  tar    | + cblite CLI export  |  JSON   | with live update |
+------------------+         +----------------------+         +------------------+
```

1. **Background thread** pulls `.cblite2` databases from emulators every N seconds via:
   ```
   adb shell "run-as <package> tar cf - <db_path>" | tar xf - -C <local_dir>
   ```
2. **cblite CLI** extracts documents (`ls -l`, `cat --rev`, `revs`, `ls -c`)
3. **HTTP server** serves `/api/data` (JSON) and static files
4. **Frontend** polls `/api/data` every 2 seconds, only re-renders on data change

## UI Overview

| Component | Description |
|-----------|-------------|
| **Left sidebar** | Tree view: Database [DB] > Scope [SCOPE] > Collection [COL] |
| **Top toolbar** | Database/Scope/Collection dropdowns, Limit/Offset filters, Doc ID search |
| **Document table** | Clickable doc IDs with JSON preview |
| **Document modal** | **JSON tab**: Syntax-highlighted document body. **Metadata tab**: revision ID, version vector, sequence, flags |
| **Live indicator** | Green pulsing dot when connected, shows last update time |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/data` | All documents from all emulators as JSON |
| `GET /api/status` | Health check with emulator list and config |

## Files

```
cblite-browser/
  index.html     # Capella-style single-page viewer UI
  server.py      # Python HTTP server + background emulator puller
  launch.sh      # One-command launcher
  .gitignore
  README.md
  LICENSE
```

## Emulator Port Mapping

The tool auto-detects emulators via `adb devices`. For the KitchenSync demo, the default port mapping is:

| Emulator | Role |
|----------|------|
| emulator-5554 | Manager |
| emulator-5556 | Kitchen |
| emulator-5558 | Kiosk |

For other apps, emulators are labeled Device-1, Device-2, etc.

## License

Apache License 2.0
