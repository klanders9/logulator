# logulator

## Project Purpose
A cross-platform desktop GUI tool (macOS, Linux, Windows) for monitoring and
filtering serial log output. Designed for embedded development workflows where
a target device streams structured log output over a serial port.

## Core Design Principle
Raw log collection and filtered display are strictly separated:
- The serial worker writes ALL received bytes to a file-backed log, unmodified
- The UI applies filters purely as a view transform — the log file is never
  filtered, truncated, or modified by UI state
- This is non-negotiable: do not blur this boundary
- One deliberate extension (user-approved): sent (TX) lines are also recorded
  in the session log, marked with a `>> ` prefix, so the file captures both
  directions of the conversation. TX never modifies or filters RX bytes.

## Tech Stack
- Python 3.9+ (matches `requires-python` in `pyproject.toml` and the .venv —
  avoid `X | Y` union syntax in type hints; use `Optional[X]` from typing instead)
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
cause blank lines in the display panes. Emits `connected()` immediately after
the serial port opens (used by auto-reconnect to confirm reconnect succeeded),
`error_occurred(str)` on `SerialException`. Never applies filters.

Constructor takes an optional `options` dict: `databits` (5–8), `parity`
(`'N'/'E'/'O'/'M'/'S'`), `stopbits` (`'1'/'1.5'/'2'`), `flow`
(`'none'/'rtscts'/'xonxoff'`), `dtr` (bool), `rts` (bool). The port is
constructed unopened so DTR/RTS initial state is set before `open()` (matters
for boards that reset on a DTR/RTS edge); RTS is left driver-managed when
hardware flow control is on.

TX: `send(data: bytes)` queues bytes (thread-safe `queue.Queue`); the run
loop drains the queue and writes before each read so all port access stays on
the worker thread. Worst-case TX latency is one read timeout (0.1 s).

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
- `doc_line_count(pane) -> int` — displayed line count (0 for an empty
  document; Qt reports blockCount()==1 when empty).
- `pane_with_header(pane, title, side_widget=None) -> (container, header_label)`
  — wraps a pane with a slim grey header label; the container goes in the
  splitter and the label can be updated live (filtered match counts). Both
  windows use this; show/hide the **container** (`_filtered_box`), not the
  pane itself. For the filtered pane, both windows insert `FilterBar` into
  the returned container's layout at index 1
  (`container.layout().insertWidget(1, filter_bar)`) — between the header
  label and the pane — so the filter controls sit directly above the content
  they filter. `side_widget` (e.g. a `Minimap`) is placed beside the pane,
  below the header, in an inner `QHBoxLayout` — so its bands line up with
  pane rows rather than spanning the header too.
- `_fmt(hex_color) -> QTextCharFormat`, `_PANE_STYLE`, `_PLAIN_COLOR`,
  `_DEFAULT_CAP` — shared style constants.

### `app/ui/minimap.py` — `Minimap(QWidget)`
Slim colored-band strip placed beside a pane via `pane_with_header`'s
`side_widget` param. One band per tracked line, colored by severity (not a
literal shrunk-text rendering like Sublime/VS Code — see rationale below).
Optional and off by default; see `AppSettings.minimap_enabled` /
`minimap_apply_to` and the Settings sidebar's "Minimap" subsection.

- Maintains its own rolling `List[QColor]`, independent of the `QTextDocument`
  it sits beside — callers (`MainWindow`, `FileViewer`) push colors in via
  `append_color(color)` as each line arrives, mirroring `LogPane.append_line`.
  `set_cap(n)` trims from the front like `LogPane.set_cap`. `set_colors(list)`
  replaces the whole list (used for backfilling when the minimap is newly
  enabled, or after a colorization-settings rebuild). `clear()` empties it.
- `paintEvent` renders by **nearest-neighbor sampling down to the widget's
  pixel height**, not by aggregating every line: for each pixel row, it picks
  the color at `index = row * len(colors) // height`. This makes repaint cost
  O(widget height), not O(line count) — necessary because panes can hold up
  to 500,000 (serial) or 2,000,000 (file viewer) lines, and repainting is
  triggered on nearly every appended line. The tradeoff is that an isolated
  error line surrounded by thousands of other lines may not land on a sampled
  row and so may not show up in the band — acceptable for an overview widget,
  not attempted to be fixed with bucketed aggregation (which would cost
  O(line count) per paint).
- `set_viewport(start_frac, end_frac)` draws a translucent highlight rect
  showing the pane's current scroll position; callers recompute this from
  `pane.verticalScrollBar()` on `valueChanged`/`rangeChanged` (both windows
  also refresh it opportunistically — `MainWindow` on its 1 Hz status timer,
  `FileViewer` after `_on_load_complete` — since a pure widget resize can
  change `pageStep` without emitting either signal).
- Click or drag emits `position_clicked(fraction: float)`; callers translate
  that into a `verticalScrollBar().setValue(...)` call, centering the
  viewport on the clicked point.
- Callers (see `MainWindow`/`FileViewer` below) guard every `append_color`
  call with `if minimap.isVisible():` so no work happens while hidden, and
  call `set_colors([])` — **not** an unguarded document walk — when rebuilding
  from an empty pane: an empty `QTextDocument` reports `blockCount() == 1`
  with an empty first block (the same quirk `doc_line_count()` works around),
  and naively walking it seeds one phantom neutral band before any real line
  ever arrives.

### `app/ui/filter_bar.py` — `FilterBar(QWidget)`
Compact two-part filter UI. Constructor: `FilterBar(settings=None, parent=None)`.
When `settings` is `None` (file viewer), all state is in-memory only — nothing
is persisted to `AppSettings`. Lives inside the filtered pane's container
(inserted into `pane_with_header`'s layout, between the header label and the
pane — see below) in both `MainWindow` and `FileViewer`, so the controls sit
directly above the content they affect.

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
  toolbar action. `is_input_bar_open()` is backed by an explicit `_input_open`
  flag rather than `_input_row.isVisible()`: since the bar now lives inside
  the filtered pane's container (which itself may be hidden when no rules are
  active), Qt's composed visibility would report `False` even while the row
  is logically open, breaking the open/close toggle.

### `app/ui/serial_panel.py` — `SerialPanel(QWidget)`
Constructor: `SerialPanel(settings=None, parent=None)` (creates its own
`AppSettings` if none given; `MainWindow` passes its instance).
Status dot (● grey idle / green connected / amber reconnecting — set via
`set_status('idle'|'connected'|'reconnecting')`; `set_connected` also updates
it), port `QComboBox` (items show `device — description` from
`serial.tools.list_ports` with the device path as item data — always use
`currentData()`, not `currentText()`, for the port), baud rate selector, a
config summary button (shows e.g. `8-N-1`, full config in tooltip; opens
`SerialConfigDialog`), Refresh button (preserves the current selection when
the port is still present), Connect/Disconnect toggle, Auto-reconnect
checkbox, and a Clear button. Last-used port and baud are persisted on
connect (`AppSettings.last_port`/`last_baud`) and restored on launch when the
port is present. Disables port/baud/config controls while connected. Clear
button and Auto-reconnect checkbox are always enabled regardless of
connection state. Font size moved to the settings sidebar.
Emits `connect_requested(port, baud)`, `disconnect_requested()`,
`clear_requested()`, and `auto_reconnect_changed(bool)`.
`set_auto_reconnect(val)` / `auto_reconnect() -> bool` for external
get/set of the checkbox.

### `app/ui/serial_config_dialog.py` — `SerialConfigDialog(QDialog)`
Modal dialog for advanced serial options: data bits, parity, stop bits, flow
control, and "Assert DTR/RTS on connect" checkboxes (RTS checkbox disabled
when RTS/CTS flow control is selected — driver-managed). Reads current values
from `AppSettings` on open, writes them back on OK. Changes apply on the next
connect. Module also exports `config_summary(settings) -> str` (`"8-N-1"`)
and `config_tooltip(settings) -> str` used by `SerialPanel`'s button.

### `app/ui/send_bar.py` — `SendBar(QWidget)`
Input row for transmitting characters out the serial port, docked below the
display panes in `MainWindow`. `Send:` label, `_HistoryLineEdit` (Enter sends;
Up/Down recall previously sent lines, shell-style, in-memory only, capped at
100 entries), line-ending combo (CRLF/LF/CR/None — persisted via
`AppSettings.tx_line_ending`, default CRLF for Zephyr shell), and a Send
button. Emits `send_requested(text, ending_chars)`. `set_connected(bool)`
enables/disables the input and button (visible but greyed while
disconnected); focuses the input on connect. Sending empty text is allowed
(bare line ending nudges a shell prompt).

### `app/settings.py` — `AppSettings`
Wraps `QSettings` (org: `logulator`, app: `logulator`) with typed
getters/setters and hardcoded defaults. Covers: window geometry, splitter
state, sidebar open/closed, colorization settings (enabled, mode, apply-to,
per-level colors, per-syntax-field colors), buffer cap, minimap
enabled/apply-to, filter state, recent files, auto-reconnect, and app theme.
All future persistent settings go through this class.

Buffer cap: `buffer_cap() -> int` / `set_buffer_cap(val: int)`. Default
100,000, clamped to [1,000, 500,000] on read and write.

Minimap: `minimap_enabled() -> bool` / `set_minimap_enabled(val: bool)` —
stored under `display/minimap_enabled`, default `False`. `minimap_apply_to()
-> str` / `set_minimap_apply_to(val: str)` — `'all'`/`'raw'`/`'filtered'`,
stored under `display/minimap_apply_to`, default `'raw'`.

Filter persistence (main window only — file viewers don't persist):
- `filter_rules() -> list` / `set_filter_rules(rules: list)` — stored as JSON.
- `filter_mode() -> str` / `set_filter_mode(mode: str)` — `'AND'` or `'OR'`.
- `filter_bar_open() -> bool` / `set_filter_bar_open(val: bool)`.

Recent files:
- `recent_files() -> list` — ordered list of path strings, most recent first.
  Stored as JSON under `files/recent`.
- `add_recent_file(path)` — prepends `path`, deduplicates, caps at 10 entries.

Auto-reconnect:
- `auto_reconnect() -> bool` / `set_auto_reconnect(val: bool)` — persisted
  under `serial/auto_reconnect`. Default `False`.

Serial connection options (all validated on read/write, applied on next
connect): `serial_databits()` (5–8, default 8), `serial_parity()`
(`'N'/'E'/'O'/'M'/'S'`, default `'N'`), `serial_stopbits()`
(`'1'/'1.5'/'2'`, default `'1'`), `serial_flow()`
(`'none'/'rtscts'/'xonxoff'`, default `'none'`), `serial_dtr()` /
`serial_rts()` (bool, default `True`) — with matching setters, stored under
`serial/*`.

TX (send): `tx_line_ending()` (`'none'/'lf'/'cr'/'crlf'`, default `'crlf'`,
stored under `tx/line_ending`); `tx_color()` / `set_tx_color()` (default
`#8be9fd`, stored under `color/tx`).

Last-used connection: `last_port()` / `set_last_port()` (str, default `""`),
`last_baud()` / `set_last_baud()` (int, default 115200) — stored under
`serial/last_*`, written by `SerialPanel` on connect, restored on launch.

Font: `font_size()` / `set_font_size()` — validated against the size list
(8–24), default 12, stored under `app/font_size`.

Theme:
- `theme() -> str` / `set_theme(val: str)` — `'dracula'` or `'vscode'`.
  Stored under `app/theme`. Default `'dracula'`.

### `app/colorizer.py` — `Colorizer`, `detect_level`
Reads settings from `AppSettings` and converts a log line string into a list
of `(text, QTextCharFormat)` segments for insertion into `QTextEdit`.

Module-level `detect_level(line) -> Optional[str]` — the level-detection half
of level-mode colorization (explicit `<tag>` search, falling back to a
keyword scan), factored out so it can be reused independent of the active
colorization mode. `Colorizer._level()` calls it; so does each window's
`_minimap_color_for()` helper, so the minimap shows severity bands even when
colorization is set to `syntax` mode or disabled outright.

Two modes:
- `level` — whole line colored by severity. Checks for a Zephyr `<level>` tag
  first; if absent, falls back to keyword scan (`error/fatal/critical`,
  `warning/warn`, `info/notice`, `debug/trace` — case-insensitive,
  word-boundary anchored). Lines with no detectable level are plain grey.
- `syntax` — line parsed into segments, each colored independently. Tries
  three formats in order:
  1. **Zephyr** `[timestamp] <level> module: message` — four segments colored
     as timestamp / level / module / message. The timestamp bracket also
     accepts a full-date variant (e.g. `[2026-07-06 11:21:45.726]`) and the
     space before `<level>` is optional, since some boards emit
     `[...]<inf> module: msg` with no separating space.
  2. **Syslog ISO 8601** `2024-01-02T10:23:45.000+00:00 host proc[pid]: msg`
  3. **Syslog traditional** `Jan  2 10:23:45 host proc[pid]: msg`
  For syslog formats: timestamp → timestamp color, hostname → plain grey,
  `proc[pid]:` → module color, message → message color (or a level color
  if the message text matches a severity keyword).
  Lines matching none of the above are plain grey.

The `Colorizer` instance is owned by the window that created it and reads live
settings on every call so color changes apply immediately on the next line or
rebuild.

Lines starting with `>> ` (the TX echo/log marker) are colored with the
configurable TX color in BOTH modes, checked before any other parsing — so
sent lines stand out live, survive pane rebuilds, and colorize when a saved
session log is opened in the file viewer.

Default colors (Dracula-inspired palette):
- `<err>` → `#ff5555`, `<wrn>` → `#ffb86c`, `<inf>` → `#50fa7b`,
  `<dbg>` → `#888888`
- Timestamp → `#666666`, Module → `#bd93f9`, Message body → `#f8f8f2`
- TX lines (`>> `) → `#8be9fd`

### `app/ui/settings_sidebar.py` — `SettingsSidebar(QWidget)`
Fixed-width (280 px) collapsible panel shown on the right side of
`MainWindow`. Contains:

- **Appearance:** theme dropdown ("Dracula" / "VS Code Dark"). Emits
  `theme_changed(str)` with the internal key (`'dracula'`/`'vscode'`).
  Change takes effect immediately via `apply_palette` — no restart needed.
  Also a font size dropdown (8–24 pt, persisted via `AppSettings.font_size`,
  default 12) emitting `font_size_changed(int)` — both `MainWindow` and
  `FileViewer` (via its settings dialog) connect it to resize pane fonts live.
- **Display / Colorization:** enable checkbox, mode selector (Level/Syntax),
  apply-to selector (All panes / Raw log only / Filtered log only / None),
  and color-picker rows for all eight configurable colors (four levels, three
  syntax fields, TX lines). Each color row shows a live swatch; clicking `…`
  opens `QColorDialog`. Emits `settings_changed()` on any change.
- **Minimap:** "Show minimap" checkbox (`AppSettings.minimap_enabled`,
  default off) and an apply-to combo (Both panes / Raw only / Filtered only —
  `AppSettings.minimap_apply_to`, default Raw only). Both emit
  `settings_changed()`, same as the colorization controls; `MainWindow` and
  `FileViewer` both call `_apply_minimap_settings()` from their
  `_on_settings_changed()` handler to show/hide and backfill the minimap(s).
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

### `app/ui/find_controller.py` — `FindController(QObject)`
Reusable controller binding a `FindBar` to a `LogPane`. Owns all search
state: match cursors, current index, 300 ms debounce timer, highlight
application (amber ExtraSelections capped at 5,000, blue current-match
selection, wrap-around navigation, scroll centering). Used by `FileViewer`
(static file search) and `MainWindow` (live raw-buffer search). Public API:
`research()` — re-run the current search after the document changed (called
by `FileViewer._on_load_complete`). In the main window, matches are computed
on demand and can go stale as lines append/trim — press Enter or retype to
refresh; acceptable for live use.

### `app/ui/find_bar.py` — `FindBar(QWidget)`
Inline find bar UI (widget only — logic lives in `FindController`). Used by
`FileViewer` and `MainWindow`. Hidden by default; toggled with Ctrl+F,
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
`FileViewer` instance, stores it in `_file_viewers`, and connects
`about_to_close` for cleanup. `FileViewer` also manages its own GC via a
class-level `_instances` list — every instance adds itself on init and removes
itself on close, so viewers survive even if no `MainWindow` holds a reference.

**Loading:** `FileLoaderWorker` streams the file in 2,000-line chunks.
`_on_chunk_ready` appends to `_raw_pane` (and to `_filtered_pane` if rules
are active). `_on_load_complete` records `_follow_pos = path.stat().st_size`,
scrolls both panes to the bottom, then triggers a full filtered-pane rebuild
and any pending find-bar search so they cover the complete file.

**Display cap:** `_FILE_PANE_CAP = 2_000_000` — effectively unlimited for
static files. The serial window's `buffer_cap` setting does not apply here.

**Filter bar:** Same `FilterBar` widget with `settings=None` (in-memory, not
persisted), inserted into the filtered pane's container above the pane
(same placement and same visibility rules as `MainWindow` — see its "Filter
bar" section). The toolbar `▽ Filter` action toggles it. `_rebuild_filtered_pane()`
iterates all `_raw_pane` document blocks so it always covers the full loaded file.

**Find bar:** `FindBar` docked at the bottom, hidden until Ctrl+F; search
logic delegated to a `FindController` bound to the raw pane (see its section
for highlight/debounce details). "Filter to matches" calls
`FilterBar.add_rule()` with the current search text as a substring include
rule.

**Follow (tail) mode:** "Follow" checkable toolbar action — enabled
automatically after the initial load completes (tail-by-default; uncheck
per-window to stop).
When enabled, `QFileSystemWatcher` monitors the file for changes. On
`fileChanged`, new bytes are read from `_follow_pos` (byte offset after last
read) into `_tail_buffer` to handle partial lines, then complete lines are
appended to both panes. If the user scrolls up, `_follow_paused` is set and
a "⬇ Resume" toolbar action appears; scrolling back to the bottom or clicking
Resume clears the pause. `_programmatic_scroll` flag prevents spurious pause
detection when the code scrolls to bottom. `QFileSystemWatcher` is cleaned up
in `closeEvent` and the path is re-added if the watcher drops it (some
platforms remove the watch after the first change event).

**Toolbar:** "New Window" (opens a new serial connection window via
`MainWindow.open_new()`), "Open File…" (Ctrl+O, file dialog → `open_file()`),
"⚙ Settings" (opens a modeless `QDialog` wrapping `SettingsSidebar` — created
once, re-raised on subsequent clicks; `buffer_cap_changed` is a no-op here
since file viewers use `_FILE_PANE_CAP`), separator, then "▽ Filter",
"Follow", "⬇ Resume".

**File opening:** `open_file(path)` records in `AppSettings.add_recent_file`,
creates and shows a new `FileViewer` (which self-registers in `_instances`).
Drag-drops on either pane call `open_file` directly — no signal routing
through `MainWindow`.

**Settings:** `_on_settings_changed()` rebuilds both panes (same
`setUpdatesEnabled` pattern as `MainWindow`). `_on_theme_changed()` calls
`apply_palette(QApplication.instance(), theme)`.

**Signals:** `about_to_close` (for `MainWindow` cleanup).

**Colorization:** `_get_segments(line, pane)` follows the same logic as
`MainWindow`, delegating to a `Colorizer` instance that reads live settings.

**Minimap:** raw and filtered `Minimap` instances, capped to `_FILE_PANE_CAP`
so trimming never kicks in for static files, gated by
`AppSettings.minimap_enabled`/`minimap_apply_to` via `_apply_minimap_settings()`
(same shape as `MainWindow`'s, duplicated per-window like `_get_segments`).
Colors are appended incrementally in `_on_chunk_ready` (per line, guarded by
`isVisible()`) rather than computed in one pass after load — a 2,000,000-line
file loaded in 2,000-line chunks would otherwise mean re-walking the whole
pane on every chunk. Follow-mode tail appends (`_on_file_changed`) append
minimap colors the same incremental way. If the minimap is enabled *after*
a file is already loaded, `_apply_minimap_settings()`'s backfill
(`_rebuild_raw_minimap()`/`_rebuild_filtered_minimap()`) walks the full
loaded document once — an acceptable one-time cost since it only happens on
a deliberate settings change, not per line.

### `app/main_window.py` — `MainWindow(QMainWindow)`
Composes all panels. Key behaviors:

**Layout:** Toolbar at top with `New Window` (spawns a new `MainWindow` via
`open_new()`), `▽ Filter` (checkable, toggles `FilterBar` input row), and
`⚙ Settings` (checkable, toggles sidebar). Central widget
uses `QHBoxLayout`: left side holds `SerialPanel`, then the vertical splitter
(stretch=1) — `FilterBar` lives inside the splitter, above the filtered pane
(see Pane headers below) — then `FindBar` (hidden until Ctrl+F), then
`SendBar`; right side is `SettingsSidebar`
(fixed 280 px, hidden when collapsed). Menu bar has a `File` menu with
`New Window` (Ctrl+N), `Open Log File…` (Ctrl+O), a `Recent Files` submenu
(last 10 paths, greyed out if the file no longer exists), and a `Help` menu
with `About Logulator`. Shortcuts: `Ctrl+Shift+F` toggles the filter input
row, `Ctrl+,` toggles the settings sidebar, `Ctrl+F` opens the find bar
(all mapped to Cmd on macOS).
Window geometry and splitter state are saved to `AppSettings` on close and
restored on startup.

**Pane headers:** both panes are wrapped via `pane_with_header` — "Raw" and
"Filtered — N of M lines" (updated on rebuild, clear, and the 1 s status
timer). The filtered **container** (`_filtered_box`) is what gets
shown/hidden, not the pane widget. The raw pane shows a placeholder hint
before first connect; the filtered pane shows "No lines match…". `FilterBar`
is inserted into the filtered container's layout (index 1, between the
header label and the pane) — see "Filter bar" below.

**Find:** `FindBar` + `FindController` over the raw pane (Ctrl+F). "Filter to
matches" adds the search text as a substring include rule on the filter bar.

**Status bar:** the log-filename label is clickable while connected — reveals
the session log in Finder/Explorer (`_reveal_in_file_manager`, platform
branches: `open -R` / `explorer /select,` / `QDesktopServices` folder open).

**Filter bar:** `FilterBar()` (no settings — all state is in-memory, not
persisted). Lives inside the filtered pane's container, above the pane
itself, so the controls sit next to the content they filter. The `▽ Filter`
toolbar action is kept in sync with the bar's visibility (including
Escape-to-close). Because the filtered container is otherwise hidden until a
rule is added, `_update_filtered_visibility()` shows it whenever
`self._rules` is non-empty **or** `self._filter_bar.is_input_bar_open()` —
otherwise there would be no way to reach the input row to add the first
rule. `_ensure_filtered_box_visible()` (also used by `_update_filtered_visibility`)
is called *before* `self._filter_bar.toggle_input_bar()` when opening, so the
input field's `setFocus()` call lands after the container is actually
visible — a hidden ancestor would otherwise swallow the focus request. On
startup, `_on_filters_changed` is called with the empty initial rules
(filtered pane stays hidden).

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
- Both panes: background and selection color inherit from `QPalette.Base` /
  `QPalette.Highlight` (theme-aware — no hardcoded `#000000`), grey default
  text (`#cccccc`), monospace font (Menlo).
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

**Minimap:** `_minimap` and `_filtered_minimap` (`app/ui/minimap.py`), each
placed beside its pane via `pane_with_header`'s `side_widget` param. Optional
and off by default — gated by `AppSettings.minimap_enabled`/`minimap_apply_to`
(Settings sidebar's "Minimap" subsection) via `_apply_minimap_settings()`,
called from `_on_settings_changed()` and once at startup. `_minimap_color_for(line)`
maps a line to severity color (TX color for `>> ` lines, grey for `---`
separators, `AppSettings.level_color()` via `colorizer.detect_level()`
otherwise, or a neutral grey if no level is detected) — independent of
whether colorization itself is on or in level/syntax mode. Colors are
appended incrementally alongside each pane append (`_on_new_line`, `_on_send`,
`_append_separator`), each guarded by `minimap.isVisible()` so no work happens
while hidden. `_rebuild_raw_pane()`/`_rebuild_filtered_pane()` each end with a
guarded call to `_rebuild_raw_minimap()`/`_rebuild_filtered_minimap()` so the
minimap recolors alongside full pane rebuilds (settings change, filter rule
change). Viewport highlight and click-to-scroll are wired per pane
(`_update_minimap_viewport`/`_on_minimap_clicked` and the `_filtered_*`
equivalents) off `verticalScrollBar().valueChanged`/`rangeChanged`, with a
periodic refresh on the 1 Hz status timer as a fallback for resizes that
change `pageStep` without emitting either signal.

**Status bar:**
- Left: current log filename while connected; "Not connected" otherwise.
- Right: session runtime (HH:MM:SS), line count, log file size — updated
  every second via `QTimer`.

**Font size:** `font_size_changed` from `SettingsSidebar` updates point size
on both panes simultaneously; initial size comes from
`AppSettings.font_size()`.

**Clearing the display:** `_on_clear()` clears both panes and resets
`_line_count`. Does not affect the log file.

**Multiple windows:** `_instances` class variable holds all open `MainWindow`
instances (each appends on init, removes on close). `open_new()` classmethod
creates and shows a new instance. The app quits when all top-level windows
(MainWindows and FileViewers) are closed — Qt's default `lastWindowClosed`
behavior.

**File viewers:** `open_file(path)` calls `AppSettings.add_recent_file`,
rebuilds `_recent_menu`, creates a `FileViewer`, stores it in `_file_viewers`,
and connects `about_to_close`. `_on_viewer_closed` removes closed viewers from
the list. `_rebuild_recent_menu()` repopulates `_recent_menu` from
`AppSettings.recent_files()`; also connected to `file_menu.aboutToShow` so
the menu is always fresh when opened.

**Sending (TX):** `SendBar.send_requested(text, ending)` → `_on_send`:
no-op if `_worker is None` (brief gap during auto-reconnect). Otherwise
`worker.send((text + ending).encode())`, writes `>> text\n` to the session
log, and echoes `>> text` into the raw pane (and filtered pane if it matches
the active rules). Echoes are not counted in `_line_count` (RX lines only).
`_serial_options()` builds the worker options dict from `AppSettings`; it is
captured at connect time into `_reconnect_options` so auto-reconnect reuses
the same configuration.

**Lifecycle:** `_on_connect` opens a new log session, resets line count and
connect time, starts the worker and the status timer, enables the send bar. `_on_disconnect(prompt_clear)`
stops the timer, stops the worker, closes the log. When `prompt_clear=True`
(explicit user disconnect), shows a Yes/No dialog offering to clear the
display. `closeEvent` saves geometry/splitter state, then calls
`_on_disconnect(prompt_clear=False)`.

### `app/theme.py` — `apply_palette`
Applies the Fusion Qt style and a named `QPalette` to the `QApplication`.
Two themes are available; both are applied on all platforms.

`apply_palette(app, theme)` — dispatch entry point. `theme` is `'dracula'`
or `'vscode'`; falls back to Dracula for unknown values.

**Dracula** (`'dracula'`): window/panel bg `#282a36`, input bg `#21222c`,
buttons/surfaces `#44475a`, primary text `#f8f8f2`, disabled text `#6272a4`,
selection `#1a5fa8`, links `#8be9fd`.

**VS Code Dark+** (`'vscode'`): window/panel bg `#252526`, input bg
`#1e1e1e`, buttons/surfaces `#3a3d41`, primary text `#d4d4d4`, disabled
text `#858585`, selection `#264f78`, links `#4fc1ff`.

Both themes set disabled-state colors separately via `QPalette.ColorGroup.Disabled`
and configure the Fusion 3-D shading roles (`Light`/`Midlight`/`Mid`/`Dark`/`Shadow`)
for button bevels. Log pane backgrounds and selection colors follow
`QPalette.Base` / `QPalette.Highlight` so they update automatically when the
theme switches — Dracula panes use `#21222c`, VS Code panes use `#1e1e1e`.

### `main.py`
`QApplication` entry point. Run with `.venv/bin/python main.py`. Loads
`icon.png` from the repo root (if present) and sets it as the app icon via
`QIcon`. Reads the persisted theme key directly from `QSettings` (before
`MainWindow` is constructed) and calls `apply_palette(app, theme)` so the
Fusion style and palette are applied before any widgets are created.
`MainWindow` handles live theme switching via `SettingsSidebar.theme_changed`.

## Supported Log Formats

**Zephyr RTOS** (primary target — all filter types and colorization fully supported):
  [00:00:01.234,567] <inf> my_module: Some message here
  [00:00:01.234,567] <err> my_module: Something failed: -5
Level tags: `<dbg>` `<inf>` `<wrn>` `<err>`

A full-date timestamp variant with no space before the level tag is also
recognized by syntax-mode colorization:
  [2026-07-06 11:21:45.726]<inf> telit_modem: comm_state_machine state=0

**Syslog traditional** (colorization in syntax/level modes; filters work on raw text):
  Jun 14 10:23:45 hostname systemd[1]: Started network.target.

**Syslog ISO 8601** (same colorization support as traditional):
  2024-06-14T10:23:45.123456+00:00 hostname kernel: message here

**Generic / unstructured** (level mode uses keyword scan; syntax mode renders plain grey).

## Testing

`pytest` + `pytest-qt`, declared as the `dev` optional-dependency group in
`pyproject.toml`. Install with `.venv/bin/pip install -e ".[dev]"`, run with
`.venv/bin/python -m pytest`.

- `tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen` **before** PySide6 is
  imported, and redirects `QSettings` to a temporary INI tree for the whole
  session. Without that redirect, tests would read and overwrite the
  developer's real logulator preferences. The `settings` fixture hands out a
  cleared `AppSettings` backed by that store.
- Qt widget tests take pytest-qt's `qapp` / `qtbot` fixtures.
- `pythonpath = ["."]` in `[tool.pytest.ini_options]` makes `app` importable
  without installing the package.
- Known bugs that are captured but not yet fixed are marked
  `@pytest.mark.xfail(strict=True)` with the reason. Strict mode means the
  suite fails once the bug is fixed, which is the prompt to delete the marker.

## Current Status
Implementation complete and tested on macOS. All core features working:
- Serial connect/disconnect with per-session timestamped log files
- Live display in raw pane; filtered pane appears when rules are active
- Filter types: substring, regex, level, module prefix; AND/OR mode;
  include/exclude per rule
- Filters retroactively apply to all lines in the raw pane buffer
- Log colorization: level mode (whole-line color) and syntax mode
  (per-field coloring) with Dracula-inspired defaults; all colors
  user-configurable via color pickers in the settings sidebar; supports
  Zephyr, syslog (traditional and ISO 8601), and keyword-based level
  detection for unstructured formats
- Collapsible settings sidebar (⚙ Settings toolbar button); sidebar
  open/closed state persisted across launches
- Persistent settings via QSettings: window geometry, splitter position,
  sidebar state, all colorization preferences
- App icon loaded from icon.png at startup
- Dark terminal-style display with theme-matched pane backgrounds and a
  subtle 1px border (`#555555`) framing each pane; configurable font size
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
  no rules active; filter rules are in-memory only (not persisted); the bar
  sits above the filtered pane (inside its container) rather than at the top
  of the window, so the controls stay next to the content they affect
  (UX round, 2026-07-13)
- Multiple serial connection windows: "New Window" toolbar button in all
  windows spawns an additional independent serial monitor; each has its own
  port, log writer, and display; app quits when all windows close
- File viewer: standalone window opened via File → Open Log File… (Ctrl+O),
  drag-and-drop onto any display pane, or "Open File…" toolbar button (Ctrl+O)
  from within any file viewer; multiple viewers may be open simultaneously;
  closing the serial window does not close viewers
- File viewer uses chunked background loading (2,000 lines/chunk) so large
  files don't block the UI; filter and find operate on the full loaded content
- File viewer filter bar: same compact design as main window; rules are
  in-memory only (not persisted)
- File viewer find bar (Ctrl+F): text search with Enter/Shift+Enter navigation,
  match counter, non-current match highlights (amber ExtraSelections), current
  match highlight (blue selection), "Filter to matches" button
- File viewer settings: "⚙ Settings" toolbar button opens a modeless dialog
  with the full settings sidebar (theme, colorization, buffer cap)
- Versioning: `pyproject.toml` defines version 0.1.0; `app/version.py` exposes
  `__version__` via `importlib.metadata`, falls back to `"dev"` from source
- Recent Files submenu (File menu): last 10 opened files, most-recent-first,
  greyed out if no longer on disk; persisted via `AppSettings`
- Help → About Logulator dialog: icon, version, description, MIT license,
  GitHub link, † Soli Deo Gloria
- File viewer Follow mode: "Follow" toolbar toggle tails live-appended content
  via `QFileSystemWatcher`; scrolling up pauses following with a "⬇ Resume"
  button; scrolling back to bottom resumes automatically
- User-selectable app theme (Dracula / VS Code Dark) in the settings sidebar
  Appearance section; persisted via `AppSettings`; switches live without restart
- UX round (2026-07): last-used port/baud persisted and restored; port
  dropdown shows device descriptions; connection status dot (grey/green/amber);
  keyboard shortcuts (Ctrl+N new window, Ctrl+Shift+F filter, Ctrl+, settings,
  Ctrl+F find) and File → New Window menu item; font size moved to the
  sidebar Appearance section and persisted; pane header labels ("Raw" /
  "Filtered — N of M lines"); empty-state placeholder text in both panes;
  find bar (Ctrl+F) in the main window over the live raw buffer via shared
  `FindController`; clickable status-bar log filename reveals the file in
  Finder/Explorer; file viewers enable Follow (tail) automatically after load
- Serial TX: send bar below the panes (Enter to send, ↑/↓ history, line-ending
  selector CRLF/LF/CR/None, Send button); disabled while disconnected; sent
  lines echoed to the display and recorded in the session log with a `>> `
  marker, colored with a configurable TX color
- Advanced serial configuration: data bits, parity, stop bits, flow control
  (RTS/CTS or XON/XOFF), and DTR/RTS initial line state via a dialog opened
  from the `8-N-1` summary button in the serial panel; persisted; applied on
  next connect; DTR/RTS pre-open assertion for reset-on-DTR boards
- Auto-reconnect checkbox in the serial panel: when enabled, an unexpected
  disconnect (e.g. device reset or flash) triggers a 1-second retry loop
  instead of showing an error dialog; the existing log file and display lines
  are preserved across the gap; faint separator lines ("--- disconnected,
  reconnecting… ---" / "--- reconnected ---") are appended to both display
  panes to mark the event; checkbox state persisted via `AppSettings`; clicking
  Disconnect or unchecking the box while reconnecting cancels and ends the session
- Minimap (colorband-minimap branch, off by default): optional colored-band
  overview strip beside the raw and/or filtered pane, showing per-line
  severity color down-sampled to the widget's pixel height; click/drag to
  jump the pane's scroll position; "Show minimap" checkbox + Both/Raw/Filtered
  apply-to selector in the settings sidebar, persisted via `AppSettings`;
  available in both `MainWindow` and `FileViewer`

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
- The project targets Python 3.9 (`requires-python = ">=3.9"`, and the .venv is
  3.9). Avoid new-style union type hints (`X | Y`) until that floor is raised.
- File viewer Follow mode reads new content in binary mode and tracks a byte
  offset (`_follow_pos`). `QFileSystemWatcher` may drop the watch path after
  the first change event on some platforms — `_on_file_changed` re-adds it.
- `app/version.py` returns `"dev"` unless the package is pip-installed.
  `pyproject.toml` is the single source of truth for the version number.
- Linux desktop integration (GNOME panel icon) requires a `.desktop` file with
  `StartupWMClass=logulator` and `app.setDesktopFileName("logulator")` in
  `main.py`. `install-desktop.sh` handles this for venv-based workflows; it
  writes absolute paths into `~/.local/share/applications/logulator.desktop`
  and copies the icon to the hicolor theme. `pip install --user .` does not
  work inside a venv (pip disables it); use the script instead.
