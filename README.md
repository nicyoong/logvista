# LogVista

A high-performance desktop GUI application for analyzing large log files (hundreds of MB to multiple GB) with real-time filtering, timeline visualization, error clustering, and report export.

This project demonstrates advanced PySide6 usage, efficient file processing, and production-minded GUI architecture.

---

## 🚀 Features

- **Efficient large-file handling**
  - Memory-mapped file access (no full file loading)
  - Streaming index construction
  - Constant-memory random access to log lines

- **Interactive filtering**
  - Regex-based filtering (Python `re`)
  - Log level filtering (INFO, WARN, ERROR, etc.)
  - Time-bucket filtering via timeline interaction

- **Timeline visualization**
  - Histogram of log activity by minute
  - Click-to-drill-down into specific time ranges

- **Error clustering**
  - Normalizes log messages to group similar errors
  - Highlights recurring issues and patterns
  - One-click drill-down into cluster samples

- **Export & reporting**
  - CSV (spreadsheet-friendly)
  - JSON Lines (machine-readable, streaming-friendly)
  - HTML report (shareable summary + preview)

- **Robust GUI design**
  - Threaded workers for indexing, filtering, clustering, exporting
  - GUI updates restricted to the main thread
  - Custom `QAbstractTableModel` with lazy loading and LRU caching

---

## 🧠 Architecture Overview

The application is intentionally modularized for maintainability and clarity:

.
├── main.py # GUI, orchestration, signal wiring
├── log_file.py # File validation, memory-mapped access
├── indexing.py # Index construction and parsing logic
├── filtering.py # Filtering and error clustering workers
├── models.py # Qt table models (lazy data access)
├── export.py # CSV / JSONL / HTML export workers
└── README.md


### Design principles
- **Separation of concerns** (UI vs. I/O vs. processing)
- **Thread safety** (workers emit signals, GUI updates via slots)
- **Scalable performance** (memory usage independent of file size)

---

## 🖥️ Requirements

- Python 3.10+
- PySide6

Install dependencies:
```bash
pip install pyside6
```

## Running the Application

```python main.py```
1. Open a .log file

2. Apply filters (regex, log level, timeline)

3. Inspect clustered errors

4. Export results as needed

## Export formats explained
### CSV

- For spreadsheets and analysts

- One row per log entry

- Columns: timestamp, level, message

### JSON Lines (JSONL)

- For automated pipelines and scripts

- One JSON object per line

- Stream-friendly (no full-file loading)

### HTML Report

- Human-readable, shareable report

- Includes summary statistics and a preview table

- Designed to remain responsive even for large datasets

## File safety & validation

- Only plain-text .log files are accepted

- Binary files are rejected via content inspection

- Symlinks are refused for safety

- Permanent delete utilities are guarded and extension-restricted

## Key technical highlights

- Memory-mapped file access (mmap)

- Offset-based indexing (byte-accurate line access)

- Custom Qt table model with lazy loading

- Thread-safe signal/slot architecture

- Defensive programming against invalid input

- Explicit painter lifecycle management

## Future enhancements

- Sparse or hierarchical indexing for very large logs

- JSON log format auto-detection

- Saved filter presets

- Bookmarks and annotations