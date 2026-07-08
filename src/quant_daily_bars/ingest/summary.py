"""Job summary data for bar ingestion runs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IngestSummary:
    """Tracks counts and status for a bar ingestion run."""

    mode: str = "backfill"
    status: str = "ok"
    symbols_requested: int = 0
    symbols_succeeded: int = 0
    symbols_failed: int = 0
    bars_upserted: int = 0
    missing_bars_recorded: int = 0
    errors: int = 0
    error_message: str | None = None
    duration_seconds: float | None = None
    run_id: int | None = None
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def format_line(self) -> str:
        parts = [
            f"status={self.status}",
            f"mode={self.mode}",
            f"symbols_requested={self.symbols_requested}",
            f"symbols_succeeded={self.symbols_succeeded}",
            f"symbols_failed={self.symbols_failed}",
            f"bars_upserted={self.bars_upserted}",
            f"missing_bars={self.missing_bars_recorded}",
            f"errors={self.errors}",
        ]
        if self.duration_seconds is not None:
            parts.append(f"duration={self.duration_seconds:.1f}s")
        if self.error_message:
            parts.append(f"error={self.error_message}")
        return "ingest_summary  " + "  ".join(parts)
