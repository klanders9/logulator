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
cause blank lines in the display panes. Also emits `error_occurred(str)` on
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
font size dropdown (8–24 pt, defaults to 12), and a Clear button. Disables
port/baud controls while connected. Clear button is always enabled regardless
of connection state. Emits `connect_requested(port, baud)`,
`disconnect_requested()`, `font_size_changed(int)`, and `clear_requested()`.

### `app/settings.py` — `AppSettings`
Wraps `QSettings` (org: `logulator`, app: `logulator`) with typed
getters/setters and hardcoded defaults. Covers: window geometry, splitter
state, sidebar open/closed, and all colorization settings (enabled, mode,
apply-to, per-level colors, per-syntax-field colors). All future persistent
settings go through this class.

### `app/colorizer.py` — `Colorizer`
Reads settings from `AppSettings` and converts a log line string into a list
of `(text, QTextCharFormat)` segments for insertion into `QTextEdit`.

Two modes:
- `level` — whole line gets one color based on the `<level>` tag.
- `syntax` — four segments: timestamp, level tag, module name, message body,
  each colored independently.

Parses with a single compiled regex against the standard Zephyr format.
Falls back to `#cccccc` for lines that don't match. The `Colorizer` instance
is owned by `MainWindow` and shared; it reads live settings on every call so
color changes apply immediately on the next line or rebuild.

Default colors (Dracula-inspired palette):
- `<err>` → `#ff5555`, `<wrn>` → `#ffb86c`, `<inf>` → `#50fa7b`,
  `<dbg>` → `#888888`
- Timestamp → `#666666`, Module → `#bd93f9`, Message body → `#f8f8f2`

### `app/ui/settings_sidebar.py` — `SettingsSidebar(QWidget)`
Fixed-width (280 px) collapsible panel shown on the right side of
`MainWindow`. Contains a "Display" section with a "Colorization" subsection:
enable checkbox, mode selector (Level/Syntax), apply-to selector (All panes /
Raw log only / Filtered log only / None), and color-picker rows for all seven
configurable colors. Each color row shows a live swatch; clicking `…` opens
`QColorDialog`. Emits `settings_changed()` on any change. Reads/writes
directly through `AppSettings`.

### `app/main_window.py` — `MainWindow(QMainWindow)`
Composes all panels. Key behaviors:

**Layout:** Central widget uses `QHBoxLayout`: left side holds the serial
panel, filter bar, and vertical splitter (stretch=1); right side is
`SettingsSidebar` (fixed 280 px, hidden when collapsed). A `⚙ Settings`
checkable `QAction` in a `QToolBar` toggles the sidebar; open/closed state
is persisted via `AppSettings`. Window geometry and splitter state are also
saved to `AppSettings` on close and restored on startup.

**Display panes:** Both `_raw_pane` and `_filtered_pane` are `LogPane`
instances (a `QTextEdit` subclass defined in this file). `LogPane` overrides
`createMimeData` to always produce plain text (via
`selection.toPlainText()`), never HTML. Lines are inserted via
`LogPane.append_line(segments, scroll=True)` which enforces the 10,000-line
cap by trimming from the top using a `Start→NextBlock` cursor selection when
`document().blockCount()` exceeds the limit.

**Split pane display:**
- Top pane (`_raw_pane`): all incoming lines, unfiltered, always visible.
- Bottom pane (`_filtered_pane`): lines matching active filter rules.
  Hidden when no rules are active; shown automatically when the first rule
  is added. Initial split is 60/40 (raw/filtered) on first show (or
  restored from saved state); user can drag after that.
- When filters change, `_rebuild_filtered_pane()` clears the filtered pane
  and re-walks `_raw_pane.document()` blocks to rebuild from scratch.
- When colorization settings change, `_on_settings_changed()` calls
  `_rebuild_raw_pane()` and (if visible) `_rebuild_filtered_pane()` to
  recolor all displayed lines. Both rebuilds use `setUpdatesEnabled(False)`
  to suppress flicker.
- Both panes: black background (`#000000`), grey default text (`#cccccc`),
  selection highlight (`#1a5fa8`), monospace font (Menlo).
- Selection is mutually exclusive between panes: starting a selection in one
  clears any selection in the other. Implemented via `selectionChanged`
  signals with `blockSignals(True/False)` around the clear.

**Colorization:** `_get_segments(line, pane)` checks `AppSettings` for
enabled/apply-to and delegates to `Colorizer.colorize()` if active for that
pane. Falls back to a plain `#cccccc` format. `pane` is `'raw'` or
`'filtered'`.

**Status bar:**
- Left: current log filename while connected; "Not connected" otherwise.
- Right: session runtime (HH:MM:SS), line count, log file size — updated
  every second via `QTimer`.

**Font size:** `font_size_changed` from `SerialPanel` updates point size on
both panes simultaneously.

**Clearing the display:** `_on_clear()` clears both panes and resets
`_line_count`. Does not affect the log file.

**Lifecycle:** `_on_connect` opens a new log session, resets line count and
connect time, starts the worker and the status timer. `_on_disconnect(prompt_clear)`
stops the timer, stops the worker, closes the log. When `prompt_clear=True`
(explicit user disconnect), shows a Yes/No dialog offering to clear the
display. `closeEvent` saves geometry/splitter state, then calls
`_on_disconnect(prompt_clear=False)`.

### `main.py`
`QApplication` entry point. Run with `.venv/bin/python main.py`. Loads
`icon.png` from the repo root (if present) and sets it as the app icon via
`QIcon`.

## Zephyr Log Format
Zephyr RTT/UART log lines typically look like:
  [00:00:01.234,567] <inf> my_module: Some message here
  [00:00:01.234,567] <err> my_module: Something failed: -5
Level tags: <dbg> <inf> <wrn> <err>

## Current Status
Implementation complete and tested on macOS. All core features working:
- Serial connect/disconnect with per-session timestamped log files
- Live display in raw pane; filtered pane appears when rules are active
- Filter types: substring, regex, level, module prefix; AND/OR mode;
  include/exclude per rule
- Filters retroactively apply to all lines in the raw pane buffer
- Log colorization: level mode (whole-line color) and syntax mode
  (per-field coloring) with Dracula-inspired defaults; all colors
  user-configurable via color pickers in the settings sidebar
- Collapsible settings sidebar (⚙ Settings toolbar button); sidebar
  open/closed state persisted across launches
- Persistent settings via QSettings: window geometry, splitter position,
  sidebar state, all colorization preferences
- App icon loaded from icon.png at startup
- Black/grey terminal-style display, configurable font size
- Status bar with log filename, runtime, line count, file size
- Mutual exclusion of text selection between raw and filtered panes
- Copy from either pane always produces plain text (never HTML)
- Clear button (always enabled); clear-on-disconnect dialog

**Under investigation:**
- Possible bug where disconnecting and reconnecting reuses the same log
  file rather than opening a new one. Not yet reproduced reliably — tabled
  until confirmed.

## Known Constraints
- Serial port device paths: /dev/tty.usbmodem* or /dev/tty.usbserial* on
  macOS, /dev/ttyACM* or /dev/ttyUSB* on Linux, COM* on Windows
- Log files must survive a GUI crash — flush after every write
- Raw pane buffer capped at 10,000 lines; enforced manually in
  `LogPane.append_line()` by trimming the oldest block when
  `document().blockCount()` exceeds the limit. Filtered pane is rebuilt
  from raw pane blocks, so it is bounded by the same 10k limit. The log
  file is the source of truth for full history.
- `\r\n` line endings from Zephyr UART must be stripped to `\r` before
  display — handled in `SerialWorker.run()` with `line.rstrip(b"\r")`.
- The .venv is Python 3.9 despite the 3.11+ requirement. Avoid new-style
  union type hints (`X | Y`) until the venv is upgraded.
