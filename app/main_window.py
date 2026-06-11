"""Top-level QMainWindow. Composes SerialPanel, FilterBar, and the display
QPlainTextEdit. Wires SerialWorker signals through FilterEngine before
appending lines to the display. Enforces the 10,000-line display cap."""
