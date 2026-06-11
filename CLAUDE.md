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
- Python 3.11+
- PySide6 (Qt6 bindings) for GUI — Qt Widgets, not QML
- pyserial for serial port access
- No other dependencies without asking first

## Architecture
- `serial_worker.py`: QThread subclass. Reads serial port bytes, emits a
  signal with new data, and appends raw bytes to the current log file via
  log_writer. Never applies filters.
- `log_writer.py`: Manages the file-backed log. Opens a new timestamped file
  per connection session under logs/. Append-only writes.
- `filter_engine.py`: Stateless functions that take a line and a list of
  filter rules and return bool. Rules: substring, regex, Zephyr log level
  (<inf> <wrn> <err> <dbg>), module prefix.
- `filter_bar.py`: UI for entering and managing active filter rules.
- `serial_panel.py`: Port enumeration, baud rate selector, connect/disconnect.
- `main_window.py`: Composes panels. Owns the QPlainTextEdit display.
  Subscribes to serial_worker signals and passes lines through filter_engine
  before appending to display.

## Zephyr Log Format
Zephyr RTT/UART log lines typically look like:
  [00:00:01.234,567] <inf> my_module: Some message here
  [00:00:01.234,567] <err> my_module: Something failed: -5
Level tags: <dbg> <inf> <wrn> <err>

## Current Status
Initial scaffold created. No implementation yet.

## Known Constraints
- Serial port device paths: /dev/tty.usbmodem* or /dev/tty.usbserial* on
  macOS, /dev/ttyACM* or /dev/ttyUSB* on Linux, COM* on Windows
- Log files must survive a GUI crash — flush after every write
- QPlainTextEdit must not grow unboundedly — cap display buffer at 10,000
  lines, oldest dropped first. Log file is the source of truth, not the
  display.
