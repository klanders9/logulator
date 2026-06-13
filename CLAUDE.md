# logulator

## Project Purpose
A cross-platform desktop GUI tool (macOS, Linux, Windows) for monitoring and
filtering serial output from embedded targets running Zephyr RTOS. Primary
use case: nRF54L15 development with nRF Connect SDK.

## Core Design Principle
Raw log collection and filtered display are strictly separated:
- The serial worker writes ALL bytes to a file-backed log, unmodified
- The UI applies filters purely as a view transform — the log file is never
  filtered, truncated, or modified by UI state
- This is non-negotiable: do not blur this boundary

## Tech Stack
- Python 3.11+ (note: the existing .venv uses Python 3.9 — avoid `X | Y`
  union syntax in type hints; use `Optional[X]` from typing instead)
- PySide6 (Qt6 bindings) for GUI — Qt Widgets, not QML
- pyserial for serial port access
- No other dependencies without asking first

## Architecture

### `app/log_writer.py` — `LogWriter`
Opens a new timestamped `logs/session_YYYYMMDD_HHMMSS.log` per connection
session. Append-only, flushes after every write. Exposes `current_path:
Optional[Path]` for the status bar to read file size. Path is cleared on
`close()`.

### `app/serial_worker.py` — `SerialWorker(QThread)`
Reads bytes from the serial port, appends raw bytes to `LogWriter`, then
splits on `\n` and emits `new_line(str)` per line. Strips trailing `\r`
before decoding — Zephyr UART output uses `\r\n` and the bare `\r` would
cause blank lines in `QPlainTextEdit`. Also emits `error_occurred(str)` on
`SerialException`. Never applies filters.

### `app/filter_engine.py` — stateless functions
`match(line, rules, mode) -> bool`. Rule dict keys: `type`, `value`, `mode`.

Rule types:
- `substring` — plain `in` check
- `regex` — `re.search`; silently returns False on bad pattern
- `level` — matches `<dbg>/<inf>/<wrn>/<err>` tag in the line
- `module` — prefix-matches the module field (after the level tag)

`mode` (`'AND'`/`'OR'`) controls how include rules combine. Exclude rules
always win regardless of mode. If there are no include rules, all lines pass
(subject to excludes).

### `app/ui/filter_bar.py` — `FilterBar(QWidget)`
Text input + type selector (substring/regex/level/module) + include/exclude
toggle + Add button + AND/OR mode toggle. Active rules shown in a scrollable
list with per-rule remove buttons. Emits `filters_changed(rules: list, mode:
str)` whenever anything changes.

### `app/ui/serial_panel.py` — `SerialPanel(QWidget)`
Port `QComboBox` (populated from `serial.tools.list_ports`), baud rate
selector (defaults to 115200), Refresh button, Connect/Disconnect toggle,
and a font size dropdown (8–24 pt, defaults to 12). Disables port/baud
controls while connected. Emits `connect_requested(port, baud)`,
`disconnect_requested()`, and `font_size_changed(int)`.

### `app/main_window.py` — `MainWindow(QMainWindow)`
Composes all panels. Key behaviors:

**Split pane display:**
- Top pane (`_raw_pane`): all incoming lines, unfiltered, always visible.
- Bottom pane (`_filtered_pane`): lines matching active filter rules.
  Hidden when no rules are active; shown automatically when the first rule
  is added. Initial split is 60/40 (raw/filtered) on first show; user can
  drag the splitter handle after that.
- When filters change, `_rebuild_filtered_pane()` clears the filtered pane
  and re-walks `_raw_pane.document()` blocks to rebuild from scratch. This
  means filters apply to all lines currently in the raw pane buffer, not
  just lines received after the filter was added.
- Both panes: `setMaximumBlockCount(10_000)`, black background (`#000000`),
  grey text (`#cccccc`), monospace font (Menlo with Monospace style hint).

**Status bar:**
- Left: current log filename while connected; "Not connected" otherwise.
- Right: session runtime (HH:MM:SS), line count, log file size — updated
  every second via `QTimer`.

**Font size:** `font_size_changed` from `SerialPanel` updates point size on
both panes simultaneously.

**Lifecycle:** `_on_connect` opens a new log session, resets line count and
connect time, starts the worker and the status timer. `_on_disconnect` stops
the timer, stops the worker, closes the log. `closeEvent` calls
`_on_disconnect`.

### `main.py`
`QApplication` entry point. Run with `.venv/bin/python main.py`.

## Zephyr Log Format
Zephyr RTT/UART log lines typically look like:
  [00:00:01.234,567] <inf> my_module: Some message here
  [00:00:01.234,567] <err> my_module: Something failed: -5
Level tags: <dbg> <inf> <wrn> <err>

## Current Status
Initial implementation complete and tested on macOS. All core features
working:
- Serial connect/disconnect with per-session timestamped log files
- Live display in raw pane; filtered pane appears when rules are active
- Filter types: substring, regex, level, module prefix; AND/OR mode;
  include/exclude per rule
- Filters retroactively apply to all lines in the raw pane buffer
- Black/grey terminal-style display, configurable font size
- Status bar with log filename, runtime, line count, file size

**Under investigation:**
- Possible bug where disconnecting and reconnecting reuses the same log
  file rather than opening a new one. Not yet reproduced reliably — tabled
  until confirmed.

## Known Constraints
- Serial port device paths: /dev/tty.usbmodem* or /dev/tty.usbserial* on
  macOS, /dev/ttyACM* or /dev/ttyUSB* on Linux, COM* on Windows
- Log files must survive a GUI crash — flush after every write
- Raw pane buffer capped at 10,000 lines; filtered pane rebuilt from raw
  pane blocks, so filter history is bounded by the same 10k limit. The log
  file is the source of truth for full history.
- `\r\n` line endings from Zephyr UART must be stripped to `\r` before
  display — handled in `SerialWorker.run()` with `line.rstrip(b"\r")`.
- The .venv is Python 3.9 despite the 3.11+ requirement. Avoid new-style
  union type hints (`X | Y`) until the venv is upgraded.
