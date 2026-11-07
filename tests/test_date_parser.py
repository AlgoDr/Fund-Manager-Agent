"""Unit tests for services.date_parser.resolve_date_phrase."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from services.date_parser import resolve_date_phrase

IST = ZoneInfo("Asia/Kolkata")
TODAY = datetime.now(IST).date()


class TestRelativeDates:
    """Tests for relative date phrases."""

    def test_today(self):
        assert resolve_date_phrase("today") == TODAY.isoformat()

    def test_this_morning(self):
        assert resolve_date_phrase("this morning") == TODAY.isoformat()

    def test_tonight(self):
        assert resolve_date_phrase("tonight") == TODAY.isoformat()

    def test_yesterday(self):
        expected = (TODAY - timedelta(days=1)).isoformat()
        assert resolve_date_phrase("yesterday") == expected

    def test_tomorrow(self):
        expected = (TODAY + timedelta(days=1)).isoformat()
        assert resolve_date_phrase("tomorrow") == expected

    def test_day_before_yesterday(self):
        expected = (TODAY - timedelta(days=2)).isoformat()
        assert resolve_date_phrase("day before yesterday") == expected

    def test_custom_now(self):
        fixed = datetime(2026, 11, 4, 10, 0, 0, tzinfo=IST)
        assert resolve_date_phrase("today", now=fixed) == "2026-11-04"
        assert resolve_date_phrase("yesterday", now=fixed) == "2026-11-03"
        assert resolve_date_phrase("tomorrow", now=fixed) == "2026-11-05"


class TestAbsoluteDates:
    """Tests for explicit date formats."""

    def test_iso_format(self):
        assert resolve_date_phrase("2026-11-04") == "2026-11-04"

    def test_dd_mm_yyyy_dash(self):
        assert resolve_date_phrase("04-11-2026") == "2026-11-04"

    def test_dd_mm_yyyy_slash(self):
        assert resolve_date_phrase("04/11/2026") == "2026-11-04"


class TestEdgeCases:
    """Tests for None, empty, and unparseable inputs."""

    def test_none(self):
        assert resolve_date_phrase(None) is None

    def test_empty_string(self):
        assert resolve_date_phrase("") is None

    def test_whitespace_only(self):
        assert resolve_date_phrase("   ") is None

    def test_unknown_phrase(self):
        assert resolve_date_phrase("someday") is None

    def test_random_text(self):
        assert resolve_date_phrase("next week") is None