"""Manages the file-backed log. Opens a new timestamped .log file under logs/
at the start of each connection session. Append-only. Flushes after every
write so the log survives a crash."""
