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

## Versioning
`pyproject.toml` at the project root defines `name = "logulator"` and
`version = "0.1.0"` using the setuptools build backend.

`app/version.py` exposes `__version__` by calling
`importlib.metadata.version("logulator")` (available in Python 3.8+).
Falls back to `"dev"` via `PackageNotFoundError` when running from source
without installing the package. Import `__version__` from here wherever the
version string is needed (e.g. the About dialog).

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

### `app/ui/log_pane.py` — `LogPane`, `make_pane`, shared constants
Shared `QTextEdit` subclass used by both `MainWindow` and `FileViewer`. Extracted
here to avoid circular imports. Key contents:

- `LogPane(QTextEdit)`:
  - `createMimeData` always produces plain text (never HTML).
  - `append_line(segments, scroll=True)` inserts a line and enforces the
    configurable cap by trimming the oldest block when `document().blockCount()`
    exceeds `self._cap`. Smart scroll: only scrolls to bottom if the pane was
    already at the bottom before the insert.
  - `set_cap(n)` updates `self._cap` and immediately trims from the top.
    Default `_DEFAULT_CAP = 100_000`.
  - `mouseDoubleClickEvent` emits `line_double_clicked(str)` with the block
    text at the click position.
  - `dragEnterEvent` / `dropEvent` accept local file URL drops and emit
    `file_dropped(Path)`. Text drops fall through to the default QTextEdit
    handler.
- `make_pane(font, cap=None) -> LogPane` — factory used by both windows.
- `_fmt(hex_color) -> QTextCharFormat`, `_PANE_STYLE`, `_PLAIN_COLOR`,
  `_DEFAULT_CAP` — shared style constants.

### `app/ui/filter_bar.py` — `FilterBar(QWidget)`
Compact two-part filter UI. Constructor: `FilterBar(settings=None, parent=None)`.
When `settings` is `None` (file viewer), all state is in-memory only — nothing
is persisted to `AppSettings`.

- **Input row** (`_input_row`): text input, type selector
  (substring/regex/level/module), include/exclude selector, AND/OR mode
  toggle, Add button. Hidden by default; toggled by a toolbar action. Escape
  dismisses it and emits `input_bar_closed`.
- **Chip strip** (`_chip_scroll`): horizontal scrollable row of `_RuleChip`
  widgets, one per active rule. Each chip shows `+ sub: value` or `− lvl: err`
  with a `×` remove button. Hidden completely when no rules are active.
- `filters_changed(rules: list, mode: str)` — emitted on any rule/mode change.
- `input_bar_closed` — emitted when Escape dismisses the input row; used by
  the toolbar action to uncheck itself.
- `add_rule(value, rule_type, mode)` — programmatic rule injection (used by
  the file viewer find bar's "Filter to matches" button).
- `toggle_input_bar()` / `is_input_bar_open() -> bool` — called by the
  toolbar action.

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
state, sidebar open/closed, colorization settings (enabled, mode, apply-to,
per-level colors, per-syntax-field colors), buffer cap, filter state, and
recent files.
All future persistent settings go through this class.

Buffer cap: `buffer_cap() -> int` / `set_buffer_cap(val: int)`. Default
100,000, clamped to [1,000, 500,000] on read and write.

Filter persistence (main window only — file viewers don't persist):
- `filter_rules() -> list` / `set_filter_rules(rules: list)` — stored as JSON.
- `filter_mode() -> str` / `set_filter_mode(mode: str)` — `'AND'` or `'OR'`.
- `filter_bar_open() -> bool` / `set_filter_bar_open(val: bool)`.

Recent files:
- `recent_files() -> list` — ordered list of path strings, most recent first.
  Stored as JSON under `files/recent`.
- `add_recent_file(path)` — prepends `path`, deduplicates, caps at 10 entries.

### `app/colorizer.py` — `Colorizer`
Reads settings from `AppSettings` and converts a log line string into a list
of `(text, QTextCharFormat)` segments for insertion into `QTextEdit`.

Two modes:
- `level` — whole line gets one color based on the `<level>` tag.
- `syntax` — four segments: timestamp, level tag, module name, message body,
  each colored independently.

Parses with a single compiled regex against the standard Zephyr format.
Falls back to `#cccccc` for lines that don't match. The `Colorizer` instance
is owned by the window that created it and reads live settings on every call
so color changes apply immediately on the next line or rebuild.

Default colors (Dracula-inspired palette):
- `<err>` → `#ff5555`, `<wrn>` → `#ffb86c`, `<inf>` → `#50fa7b`,
  `<dbg>` → `#888888`
- Timestamp → `#666666`, Module → `#bd93f9`, Message body → `#f8f8f2`

### `app/ui/settings_sidebar.py` — `SettingsSidebar(QWidget)`
Fixed-width (280 px) collapsible panel shown on the right side of
`MainWindow`. Contains:

- **Display / Colorization:** enable checkbox, mode selector (Level/Syntax),
  apply-to selector (All panes / Raw log only / Filtered log only / None),
  and color-picker rows for all seven configurable colors. Each color row
  shows a live swatch; clicking `…` opens `QColorDialog`. Emits
  `settings_changed()` on any change.
- **Buffer:** `QSpinBox` for the display line cap (range 1,000–500,000, step
  1,000, default 100,000). Emits `buffer_cap_changed(int)` — a separate
  signal so changes don't trigger a full pane rebuild.

Reads/writes directly through `AppSettings`.

### `app/ui/file_loader.py` — `FileLoaderWorker(QThread)`
Background worker that streams a static log file in chunks of 2,000 lines.
Emits `chunk_ready(list[str])` per chunk and `load_complete(int total_lines)`
when done. Emits `error_occurred(str)` on `OSError`. Caller calls `cancel()`
to abort early (e.g. on window close). Decodes with UTF-8, replacing errors.
Strips `\r\n` / `\r` line endings.

### `app/ui/find_bar.py` — `FindBar(QWidget)`
Inline find bar for `FileViewer`. Hidden by default; toggled with Ctrl+F,
dismissed with Escape.

Layout: `Find:` label, text input, `◀` Prev, `▶` Next, match counter label
(`X of Y` / `No matches`), `Filter to matches` button, close button.

Signals:
- `text_changed(str)` — live as user types (drives debounced search).
- `go_next` / `go_prev` — Enter / Shift+Enter in the input, or button clicks.
- `filter_to_matches(str)` — emits current search text; connected to
  `FilterBar.add_rule()` to add it as a substring include rule.
- `closed` — emitted when Escape or the close button hides the bar.

`set_match_status(current, total, has_query)` updates the counter label and
colors the input red when there are no matches.

### `app/ui/about_dialog.py` — `AboutDialog(QDialog)`
Simple modal dialog opened from Help → About Logulator. Shows: `icon.png`
(if present, scaled to 64×64), app name, version from `app.version.__version__`,
description, MIT license, clickable GitHub link (`https://github.com/klanders9/logulator`),
and "† Soli Deo Gloria". Fixed width, OK button to dismiss.

### `app/ui/file_viewer.py` — `FileViewer(QMainWindow)`
Standalone log file viewer. Multiple instances may coexist; none are parented
to `MainWindow` so closing the main window does not close them.

**Opening:** `MainWindow.open_file(path)` records the path in
`AppSettings.add_recent_file`, rebuilds the Recent Files submenu, creates a
`FileViewer` instance, stores it in `_file_viewers` to prevent GC, connects
`about_to_close` for cleanup and `open_file_requested` so drags within a
viewer open additional viewers through `MainWindow`.

**Loading:** `FileLoaderWorker` streams the file in 2,000-line chunks.
`_on_chunk_ready` appends to `_raw_pane` (and to `_filtered_pane` if rules
are active). `_on_load_complete` records `_follow_pos = path.stat().st_size`,
scrolls both panes to the bottom, then triggers a full filtered-pane rebuild
and any pending find-bar search so they cover the complete file.

**Display cap:** `_FILE_PANE_CAP = 2_000_000` — effectively unlimited for
static files. The serial window's `buffer_cap` setting does not apply here.

**Filter bar:** Same `FilterBar` widget with `settings=None` (in-memory, not
persisted). The toolbar `▽ Filter` action toggles it. `_rebuild_filtered_pane()`
iterates all `_raw_pane` document blocks so it always covers the full loaded file.

**Find bar:** `FindBar` docked at the bottom, hidden until Ctrl+F. Search uses
`QTextDocument.find()` to iterate the full loaded document — operates on all
lines, not just the visible portion. 300ms debounce on text input. Highlights:
- Non-current matches: `QTextEdit.ExtraSelection` with dark amber background
  (`#443900`). Capped at `_MAX_HIGHLIGHTS = 5000` ExtraSelections for
  performance, centered around the current match.
- Current match: `setTextCursor(cursor)` (standard Qt blue selection) +
  `ensureCursorVisible()` + scrollbar centering.
Navigation wraps. "Filter to matches" calls `FilterBar.add_rule()` with the
current search text as a substring include rule.

**Follow (tail) mode:** "Follow" checkable toolbar action (default off).
When enabled, `QFileSystemWatcher` monitors the file for changes. On
`fileChanged`, new bytes are read from `_follow_pos` (byte offset after last
read) into `_tail_buffer` to handle partial lines, then complete lines are
appended to both panes. If the user scrolls up, `_follow_paused` is set and
a "⬇ Resume" toolbar action appears; scrolling back to the bottom or clicking
Resume clears the pause. `_programmatic_scroll` flag prevents spurious pause
detection when the code scrolls to bottom. `QFileSystemWatcher` is cleaned up
in `closeEvent` and the path is re-added if the watcher drops it (some
platforms remove the watch after the first change event).

**Signals:** `about_to_close` (for `MainWindow` cleanup),
`open_file_requested(Path)` (for drag-drops inside the viewer).

**Colorization:** `_get_segments(line, pane)` follows the same logic as
`MainWindow`, delegating to a `Colorizer` instance that reads live settings.

### `app/main_window.py` — `MainWindow(QMainWindow)`
Composes all panels. Key behaviors:

**Layout:** Toolbar at top with `▽ Filter` (checkable, toggles `FilterBar`
input row) and `⚙ Settings` (checkable, toggles sidebar). Central widget
uses `QHBoxLayout`: left side holds `FilterBar` at top, then `SerialPanel`,
then the vertical splitter (stretch=1); right side is `SettingsSidebar`
(fixed 280 px, hidden when collapsed). Menu bar has a `File` menu with
`Open Log File…` (Ctrl+O), a `Recent Files` submenu (last 10 paths, greyed
out if the file no longer exists), and a `Help` menu with `About Logulator`.
Window geometry and splitter state are saved to `AppSettings` on close and
restored on startup.

**Filter bar:** `FilterBar(self._settings)` persists rules, mode, and
input-bar open/closed state. The `▽ Filter` toolbar action is kept in sync
with the bar's visibility (including Escape-to-close). On startup,
`_on_filters_changed` is called with the persisted rules to restore filter
state (show/hide filtered pane, rebuild from raw pane buffer which is empty
at startup).

**Display panes:** `_raw_pane` and `_filtered_pane` are `LogPane` instances
(from `app/ui/log_pane.py`). Both panes emit `file_dropped(Path)` which is
connected to `MainWindow.open_file()`.

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
- Double-clicking a line in `_filtered_pane` calls `_jump_to_raw_line(line)`:
  finds the first matching block in `_raw_pane`, selects it
  (`StartOfBlock → EndOfBlock` with `KeepAnchor`), gives the raw pane focus,
  then centers it in the viewport via `ensureCursorVisible()` + scrollbar
  adjustment. Silent no-op if the line is not in the raw pane buffer.

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

**File viewers:** `open_file(path)` calls `AppSettings.add_recent_file`,
rebuilds `_recent_menu`, creates a `FileViewer`, stores it in `_file_viewers`,
and connects `about_to_close` / `open_file_requested`. `_on_viewer_closed`
removes closed viewers from the list. `_rebuild_recent_menu()` repopulates
`_recent_menu` from `AppSettings.recent_files()` each time a file is opened.

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
  sidebar state, all colorization preferences, filter rules/mode/bar-state
- App icon loaded from icon.png at startup
- Black/grey terminal-style display, configurable font size
- Status bar with log filename, runtime, line count, file size
- Mutual exclusion of text selection between raw and filtered panes
- Copy from either pane always produces plain text (never HTML)
- Clear button (always enabled); clear-on-disconnect dialog
- Double-click in filtered pane selects and centers matching line in raw pane,
  with focus transferred so Cmd/Ctrl+C works immediately
- Configurable display buffer cap (default 100,000 lines; 1,000–500,000) in
  settings sidebar; applied immediately, trims from top if over cap
- Smart scroll: both panes only auto-scroll to bottom on new data when already
  at the bottom; scrolling up pauses auto-scroll without any toggle
- Compact filter bar: collapsible input row (▽ Filter toolbar button, Escape
  to close) + horizontal chip strip showing active rules; strip hidden when
  no rules active; filter state persists across launches
- File viewer: standalone window opened via File → Open Log File… (Ctrl+O) or
  drag-and-drop onto any display pane; multiple viewers may be open
  simultaneously; closing main window does not close viewers
- File viewer uses chunked background loading (2,000 lines/chunk) so large
  files don't block the UI; filter and find operate on the full loaded content
- File viewer filter bar: same compact design as main window; rules are
  in-memory only (not persisted)
- File viewer find bar (Ctrl+F): text search with Enter/Shift+Enter navigation,
  match counter, non-current match highlights (amber ExtraSelections), current
  match highlight (blue selection), "Filter to matches" button
- Versioning: `pyproject.toml` defines version 0.1.0; `app/version.py` exposes
  `__version__` via `importlib.metadata`, falls back to `"dev"` from source
- Recent Files submenu (File menu): last 10 opened files, most-recent-first,
  greyed out if no longer on disk; persisted via `AppSettings`
- Help → About Logulator dialog: icon, version, description, MIT license,
  GitHub link, † Soli Deo Gloria
- File viewer Follow mode: "Follow" toolbar toggle tails live-appended content
  via `QFileSystemWatcher`; scrolling up pauses following with a "⬇ Resume"
  button; scrolling back to bottom resumes automatically

**Under investigation:**
- Possible bug where disconnecting and reconnecting reuses the same log
  file rather than opening a new one. Not yet reproduced reliably — tabled
  until confirmed.

## Known Constraints
- Serial port device paths: /dev/tty.usbmodem* or /dev/tty.usbserial* on
  macOS, /dev/ttyACM* or /dev/ttyUSB* on Linux, COM* on Windows
- Log files must survive a GUI crash — flush after every write
- Display buffer cap is configurable (default 100,000, range 1,000–500,000),
  persisted via `AppSettings`. Enforced in `LogPane.append_line()` and
  `LogPane.set_cap()` by trimming oldest blocks when `document().blockCount()`
  exceeds `self._cap`. Filtered pane is rebuilt from raw pane blocks so it is
  bounded by the same cap. The log file is the source of truth for full history.
- File viewer panes use `_FILE_PANE_CAP = 2_000_000` (no effective cap for
  static files). The serial buffer cap setting does not apply to file viewers.
- File viewer find/filter operate on `QTextDocument` content (the full loaded
  file). For files that exceed `_FILE_PANE_CAP`, the oldest lines are trimmed
  from the top and search will miss them — this is not expected in practice.
- `\r\n` line endings from Zephyr UART must be stripped to `\r` before
  display — handled in `SerialWorker.run()` with `line.rstrip(b"\r")`.
  `FileLoaderWorker` strips `\r\n` / `\r` via `rstrip("\r\n")`.
- `LogPane` is defined in `app/ui/log_pane.py` (not `main_window.py`) to
  avoid circular imports between `MainWindow` and `FileViewer`.
- `filter_engine.py` is stateless and must remain untouched.
- The .venv is Python 3.9 despite the 3.11+ requirement. Avoid new-style
  union type hints (`X | Y`) until the venv is upgraded.
- File viewer Follow mode reads new content in binary mode and tracks a byte
  offset (`_follow_pos`). `QFileSystemWatcher` may drop the watch path after
  the first change event on some platforms — `_on_file_changed` re-adds it.
- `app/version.py` returns `"dev"` unless the package is pip-installed.
  `pyproject.toml` is the single source of truth for the version number.
