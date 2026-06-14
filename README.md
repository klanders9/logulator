# logulator

A cross-platform desktop GUI for monitoring and filtering serial log output.

## Features

- Live serial port monitoring with configurable baud rate
- All bytes written to a timestamped log file — unmodified, regardless of active filters
- Filter display by substring, regex, log level (`<dbg>` `<inf>` `<wrn>` `<err>`), or module name
- Include and exclude rules, combinable with AND/OR logic
- Configurable rolling display buffer (default 100,000 lines; log file retains everything)
- Syntax colorization with configurable per-level and per-field colors
- Smart scroll: auto-scrolls to new output only when already at the bottom
- Double-click a line in the filtered pane to jump to and select it in the raw pane

## Requirements

- Python 3.11+
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
2. Log output streams into the display area and is written to `logs/session_YYYYMMDD_HHMMSS.log`
3. Add filter rules using the filter bar:
   - **substring** — plain text match anywhere in the line
   - **regex** — Python regular expression
   - **level** — matches a `<dbg>`, `<inf>`, `<wrn>`, or `<err>` tag in the line
   - **module** — prefix-matches the module field (e.g. `bt_hci` matches `bt_hci_core`)
4. Choose **include** or **exclude** per rule, and toggle **AND/OR** to control how include rules combine
5. Click **Disconnect** or close the window to end the session

## Log files

Session logs are saved under `logs/` and are never filtered or truncated by the UI. They are the source of truth for all captured output.

## Platform notes

| Platform | Expected port names |
|---|---|
| macOS | `/dev/tty.usbmodem*`, `/dev/tty.usbserial*` |
| Linux | `/dev/ttyACM*`, `/dev/ttyUSB*` |
| Windows | `COM*` |

---
✝ *Soli Deo Gloria* 

