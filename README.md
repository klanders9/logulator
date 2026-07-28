# logulator

A cross-platform desktop GUI for monitoring and filtering serial log output.

## Features

- Live serial port monitoring with configurable baud rate
- All bytes written to a timestamped log file — unmodified, regardless of active filters
- Session logs go to `~/logs` by default; change the directory under **⚙ Settings → Logging**
- Filter display by substring, regex, log level (`<dbg>` `<inf>` `<wrn>` `<err>`), or module name
- Include and exclude rules, combinable with AND/OR logic
- Configurable rolling display buffer (default 100,000 lines; log file retains everything)
- Syntax colorization with configurable per-level and per-field colors; understands Zephyr, syslog (traditional and ISO 8601), and generic keyword-based severity detection
- ANSI/VT100 escape sequences from the target are stripped from the display by default, so colored firmware output reads cleanly and still gets logulator's own colorization and module filtering; switch to **Render colors** to honor the target's colors instead, or **Show raw** to see the escapes, under **⚙ Settings → Display → Escape sequences**. The session log always keeps the raw bytes
- Smart scroll: auto-scrolls to new output only when already at the bottom
- Double-click a line in the filtered pane to jump to and select it in the raw pane
- Send characters out the serial port with the TX bar (Enter to send, ↑/↓ history, CRLF/LF/CR/None line ending); sent lines are echoed to the display and recorded in the session log with a `>> ` marker
- Pressing Enter on an empty send field transmits a bare line ending (handy for nudging a wedged prompt); the empty `>> ` echo is suppressed by default and can be re-enabled under **⚙ Settings → Sent data**
- Unterminated output — a shell prompt like `uart:~$ ` with no trailing newline — appears as soon as the port goes quiet, instead of waiting for the next line to arrive
- Control keys go straight to the port: **Ctrl+C** sends `^C` to interrupt the target, Escape sends `^[`, and Ctrl+A–Z cover the rest — sent immediately, with no line ending appended
- Advanced serial configuration (data bits, parity, stop bits, flow control, initial DTR/RTS state) via the config dialog next to the port selector
- Auto-reconnect: automatically retries the connection after an unexpected disconnect, preserving the log file and display
- Multiple serial connection windows: **New Window** toolbar button opens an additional independent monitor on any port
- Open log files in standalone viewer windows (File → Open Log File…, drag-and-drop, or **Open File…** in any viewer toolbar)
- File viewer: filter bar, inline find (Ctrl+F), **Follow mode** to tail live-appended files, and **⚙ Settings** dialog
- Recent Files submenu (last 10 opened files, greyed out if unavailable)
- Help → About dialog with version, license, and GitHub link
- User-selectable app theme (Dracula or VS Code Dark) and font size in the settings sidebar; switches live; theme-matched pane backgrounds
- Status bar shows session runtime, line count, and log file size; click the filename to reveal it in Finder/Explorer

## Requirements

- Python 3.9+
- PySide6 6.7+
- pyserial 3.5+

## Setup

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Usage

1. Select a serial port and baud rate, then click **Connect**
2. Log output streams into the display area and is written to `~/logs/session_YYYYMMDD_HHMMSS.log`
3. Add filter rules using the filter bar:
   - **substring** — plain text match anywhere in the line
   - **regex** — Python regular expression
   - **level** — pick `err`/`wrn`/`inf`/`dbg` from the dropdown; matches the Zephyr tag *or* the equivalent keyword (`warning`, `fatal`, …), so it works on syslog and unstructured logs too
   - **module** — prefix-matches the module field (e.g. `bt_hci` matches `bt_hci_core`)
4. Choose **include** or **exclude** per rule, and toggle **AND/OR** to control how include rules combine
5. Click **Disconnect** or close the window to end the session

To monitor multiple serial ports simultaneously, click **New Window** in the toolbar to open an additional independent connection window.

To view a saved log file, use **File → Open Log File…** (Ctrl+O), drag a file onto either display pane, pick from **File → Recent Files**, or click **Open File…** in any file viewer's toolbar. Enable **Follow** in the file viewer toolbar to tail a file that is still being written to; scrolling up pauses following and a **⬇ Resume** button appears to jump back to the bottom. Click **⚙ Settings** in the file viewer toolbar to adjust colorization and theme without returning to the serial window.

## Log files

Session logs are saved under `~/logs` (configurable in **⚙ Settings → Logging**) and are never filtered or truncated by the UI. They are the source of truth for all captured output. Each connection gets its own file — reconnecting never appends to a previous session's log.

## Linux desktop integration (Ubuntu / GNOME)

To get the app icon in the GNOME panel, run the install script once after cloning (re-run if you move the repo):

```bash
bash install-desktop.sh
```

This writes `~/.local/share/applications/logulator.desktop` and installs the icon to the hicolor theme. It uses the venv's installed `logulator` script if present, otherwise falls back to running `main.py` directly.

## Platform notes

| Platform | Expected port names |
|---|---|
| macOS | `/dev/tty.usbmodem*`, `/dev/tty.usbserial*` |
| Linux | `/dev/ttyACM*`, `/dev/ttyUSB*` |
| Windows | `COM*` |

---
✝ *Soli Deo Gloria* 

