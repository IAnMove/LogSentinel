"""Batch file reader for scanning historical logs or log files."""

from __future__ import annotations
from pathlib import Path
from typing import List
from logsentinel.core.models import LogEntry
from logsentinel.collectors.file_tailer import FileTailerCollector


class FileReader:
    """Reads entire log files for one-off batch scanning."""

    @staticmethod
    def read_file(file_path: Path | str, max_lines: int = 1000) -> List[LogEntry]:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Log file not found: {file_path}")

        entries = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f):
                if idx >= max_lines:
                    break
                line_str = line.strip()
                if line_str:
                    entry = FileTailerCollector.parse_log_line(line_str, source_path=str(path))
                    entries.append(entry)
        return entries
