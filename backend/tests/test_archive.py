from datetime import date

import pytest

from app.services import archive


def test_safe_ticker_rejects_traversal():
    with pytest.raises(ValueError):
        archive._safe_ticker("../etc")


def test_append_and_daily_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_root", lambda: tmp_path)
    day = date(2026, 7, 14)
    archive.append_raw_news("NVDA", day, [{"title": "t1"}])
    archive.append_raw_news("NVDA", day, [{"title": "t2"}])
    raw = (tmp_path / "NVDA" / "news" / "2026-07-14" / "raw.jsonl").read_text()
    assert raw.count("\n") == 2

    path = archive.write_daily_archive("NVDA", day, "# 定档", {"model": "luna"})
    assert (tmp_path / "NVDA" / "news" / "2026-07-14" / "daily.md").read_text() == "# 定档"
    assert path.endswith("daily.md")


def test_write_weekly_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_root", lambda: tmp_path)
    path = archive.write_weekly_archive("NVDA", 2026, 29, "# 周汇总", {"model": "luna"})
    week_dir = tmp_path / "NVDA" / "news_weekly" / "2026-W29"
    assert (week_dir / "weekly.md").read_text() == "# 周汇总"
    assert (week_dir / "manifest.json").exists()
    assert path.endswith("weekly.md")


def test_prune_keeps_only_listed_quarters(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_root", lambda: tmp_path)
    for label in ("2026-Q2", "2026-Q1", "2025-Q4", "2025-Q3", "2025-Q2"):
        archive.write_quarter("NVDA", label, {"label": label})
    archive.prune_quarters("NVDA", ["2026-Q2", "2026-Q1", "2025-Q4", "2025-Q3"])
    files = {p.stem for p in (tmp_path / "NVDA" / "earnings").glob("*.json")}
    assert "2025-Q2" not in files
    assert "index" in files
