"""QThread subclass that reads bytes from the serial port, emits new_line(str)
for each complete line, and appends raw bytes to LogWriter. Never applies
filters."""
