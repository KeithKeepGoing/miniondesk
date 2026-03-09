"""Unit tests for scheduler cron matching."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from host.scheduler import _cron_matches


def _dt(year=2026, month=3, day=8, hour=9, minute=0):
    """Helper: Sunday 2026-03-08 09:00 (weekday=6 in Python, but cron=0)"""
    return datetime(year, month, day, hour, minute)


def test_every_minute():
    assert _cron_matches("* * * * *", _dt())


def test_specific_minute():
    assert _cron_matches("0 9 * * *", _dt(minute=0))
    assert not _cron_matches("0 9 * * *", _dt(minute=1))


def test_specific_hour():
    assert _cron_matches("0 9 * * *", _dt(hour=9, minute=0))
    assert not _cron_matches("0 9 * * *", _dt(hour=10, minute=0))


def test_sunday_cron():
    # 2026-03-08 is a Sunday (Python weekday=6, cron=0)
    sunday = datetime(2026, 3, 8, 9, 0)
    assert _cron_matches("0 9 * * 0", sunday), "Sunday (cron=0) should match"


def test_monday_cron():
    # 2026-03-09 is Monday (Python weekday=0, cron=1)
    monday = datetime(2026, 3, 9, 9, 0)
    assert _cron_matches("0 9 * * 1", monday), "Monday (cron=1) should match"
    assert not _cron_matches("0 9 * * 0", monday), "Sunday cron should not match Monday"


def test_comma_list():
    assert _cron_matches("0 9 * * 1,3,5", datetime(2026, 3, 9, 9, 0))  # Monday=1
    assert not _cron_matches("0 9 * * 1,3,5", datetime(2026, 3, 10, 9, 0))  # Tuesday=2


def test_range():
    assert _cron_matches("0 9-17 * * *", _dt(hour=9))
    assert _cron_matches("0 9-17 * * *", _dt(hour=17))
    assert not _cron_matches("0 9-17 * * *", _dt(hour=8))
    assert not _cron_matches("0 9-17 * * *", _dt(hour=18))


def test_step():
    assert _cron_matches("*/15 * * * *", _dt(minute=0))
    assert _cron_matches("*/15 * * * *", _dt(minute=15))
    assert _cron_matches("*/15 * * * *", _dt(minute=30))
    assert _cron_matches("*/15 * * * *", _dt(minute=45))
    assert not _cron_matches("*/15 * * * *", _dt(minute=14))


def test_invalid_cron_returns_false():
    assert not _cron_matches("invalid", _dt())
    assert not _cron_matches("* * *", _dt())
