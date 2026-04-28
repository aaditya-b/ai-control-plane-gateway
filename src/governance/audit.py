"""Immutable JSON-lines audit logger with daily file rotation."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any


@dataclass
class AuditEntry:
    """Single immutable audit record."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    request_id: str = ""
    user_id: str = ""
    team_id: str = ""
    action: str = ""
    model: str = ""
    provider: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    latency: float = 0.0
    cache_hit: bool = False
    pii_detected: bool = False
    guardrail_violations: list[str] = field(default_factory=list)
    policy_decision: str = ""
    status: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditFilter:
    """Filter criteria for querying audit entries."""

    start_time: str | None = None
    end_time: str | None = None
    user_id: str | None = None
    team_id: str | None = None
    model: str | None = None
    status: str | None = None


class AuditLogger:
    """Append-only JSON-lines audit logger with daily file rotation.

    Each day's entries are written to ``audit_YYYY-MM-DD.jsonl`` inside
    *storage_dir*.  The logger keeps a single file handle open and rotates
    automatically when the date changes.
    """

    def __init__(self, storage_dir: str | Path) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._current_date: str = ""
        self._file: IO[str] | None = None

    # ── Public API ──────────────────────────────────────────────────

    def log(self, entry: AuditEntry) -> None:
        """Append *entry* as a JSON line to today's audit file."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._current_date:
            self._rotate(today)
        assert self._file is not None
        line = json.dumps(asdict(entry), default=str)
        self._file.write(line + "\n")
        self._file.flush()

    def query(self, audit_filter: AuditFilter) -> list[AuditEntry]:
        """Read and filter audit entries from date-range files.

        This is a simple scan implementation suitable for moderate log
        volumes.  For production workloads consider an indexed store.
        """
        files = self._files_in_range(audit_filter.start_time, audit_filter.end_time)
        results: list[AuditEntry] = []
        for path in files:
            with open(path, "r", encoding="utf-8") as fh:
                for raw_line in fh:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    data = json.loads(raw_line)
                    entry = AuditEntry(**{
                        k: v for k, v in data.items()
                        if k in AuditEntry.__dataclass_fields__
                    })
                    if self._matches(entry, audit_filter):
                        results.append(entry)
        return results

    def close(self) -> None:
        """Flush and close the current audit file."""
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None
            self._current_date = ""

    # ── Internal helpers ────────────────────────────────────────────

    def _rotate(self, date_str: str) -> None:
        """Close current file (if any) and open a new one for *date_str*."""
        self.close()
        path = self._storage_dir / f"audit_{date_str}.jsonl"
        self._file = open(path, "a", encoding="utf-8")
        self._current_date = date_str

    def _files_in_range(
        self, start_time: str | None, end_time: str | None
    ) -> list[Path]:
        """Return sorted list of audit files whose dates overlap the range."""
        all_files = sorted(self._storage_dir.glob("audit_*.jsonl"))
        if not start_time and not end_time:
            return all_files

        start_date = start_time[:10] if start_time else "0000-00-00"
        end_date = end_time[:10] if end_time else "9999-99-99"

        result: list[Path] = []
        for path in all_files:
            # Extract date from filename: audit_YYYY-MM-DD.jsonl
            stem = path.stem  # audit_YYYY-MM-DD
            file_date = stem.replace("audit_", "")
            if start_date <= file_date <= end_date:
                result.append(path)
        return result

    @staticmethod
    def _matches(entry: AuditEntry, f: AuditFilter) -> bool:
        """Return True if *entry* passes all filter criteria."""
        if f.start_time and entry.timestamp < f.start_time:
            return False
        if f.end_time and entry.timestamp > f.end_time:
            return False
        if f.user_id and entry.user_id != f.user_id:
            return False
        if f.team_id and entry.team_id != f.team_id:
            return False
        if f.model and entry.model != f.model:
            return False
        if f.status and entry.status != f.status:
            return False
        return True
