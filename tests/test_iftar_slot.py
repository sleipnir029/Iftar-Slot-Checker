"""
Tests for the Iftar Slot Checker.
Simulate the IZA site with fixture HTML and verify parsing, notifications, and cooldown.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.html import BASE_URL, calendar_page, detail_page


@pytest.fixture
def fixed_date():
    """Fixed 'now' before 19:45 so target date is today (25.02.2026)."""
    return datetime(2026, 2, 25, 12, 0, 0)


@pytest.fixture
def target_date_str():
    return "25.02.2026"


def _make_fake_datetime(fixed_date):
    """Build a fake datetime for the module: now() and strptime() work."""
    real_dt = __import__("datetime").datetime
    fake = MagicMock()
    fake.now.return_value = fixed_date
    fake.strptime.side_effect = lambda s, fmt: real_dt.strptime(s, fmt)
    return fake


@pytest.fixture
def mock_get(iftar_module, target_date_str):
    """Mock _get_with_retries to return calendar then detail page HTML."""

    def _make_response(text: str, url: str = ""):
        r = MagicMock()
        r.text = text
        r.status_code = 200
        r.raise_for_status = MagicMock()
        r.url = url
        return r

    calendar_html = calendar_page(target_date_str, detail_path="/127/", status="wenige verfügbar")

    def fake_get(url: str):
        if "127" in url or url.rstrip("/").endswith("/127"):
            return _make_response(
                detail_page(brother_available=True, sister_available=True, language="de"),
                url,
            )
        if "dailyiftar.imsuaachen.de" in url and not url.strip("/").endswith("127"):
            return _make_response(calendar_html, url)
        return None

    with patch.object(iftar_module, "_get_with_retries", side_effect=fake_get):
        yield fake_get


@pytest.fixture
def mock_datetime_now(iftar_module, fixed_date):
    """Fix datetime.now() so target date is deterministic. Patch module's datetime (immutable type can't be patched on the class)."""
    fake_dt = _make_fake_datetime(fixed_date)
    with patch.object(iftar_module, "datetime", fake_dt):
        yield fixed_date


@pytest.fixture
def mock_telegram(iftar_module):
    """Capture send_telegram_message calls."""
    with patch.object(iftar_module, "send_telegram_message") as m:
        yield m


@pytest.fixture
def mock_save_state(iftar_module):
    """Avoid writing state.json during tests."""
    with patch.object(iftar_module, "save_state"):
        yield


def test_calendar_and_detail_fetch_success(
    iftar_module,
    mock_get,
    mock_datetime_now,
    mock_telegram,
    mock_save_state,
    target_date_str,
):
    """First run syncs state (no notifications); second run sends two Telegram notifications."""
    iftar_module.check_today_slots()  # first run after load: sync only
    assert mock_telegram.call_count == 0
    assert iftar_module.last_states.get(("bruder", target_date_str)) is True
    assert iftar_module.last_states.get(("schwester", target_date_str)) is True
    iftar_module.check_today_slots()  # second run: cooldown active, no new msgs
    assert mock_telegram.call_count == 0
    # Advance time past cooldown and run again: should send reminders
    real_dt = __import__("datetime").datetime
    fake_dt = MagicMock()
    t_later = datetime(2026, 2, 25, 12, 30, 0)  # 30 min later
    fake_dt.now.return_value = t_later
    fake_dt.strptime.side_effect = real_dt.strptime
    with patch.object(iftar_module, "datetime", fake_dt):
        iftar_module.check_today_slots()
    assert mock_telegram.call_count == 2
    texts = [c[0][0] for c in mock_telegram.call_args_list]
    assert any("Bruder" in t and "available" in t for t in texts)
    assert any("Schwester" in t and "available" in t for t in texts)


def test_cooldown_prevents_duplicate_notifications(
    iftar_module,
    mock_get,
    mock_telegram,
    mock_save_state,
    target_date_str,
):
    """Second run within cooldown: no new notifications."""
    iftar_module._first_run_after_load = False  # expect notifications on first check
    real_dt = __import__("datetime").datetime
    fake_dt = MagicMock()
    t1 = datetime(2026, 2, 25, 12, 0, 0)
    t2 = datetime(2026, 2, 25, 12, 1, 0)
    fake_dt.now.side_effect = [t1] * 5 + [t2] * 5  # first run all t1, second run all t2
    fake_dt.strptime.side_effect = real_dt.strptime
    with patch.object(iftar_module, "datetime", fake_dt):
        iftar_module.check_today_slots()
    assert mock_telegram.call_count == 2
    with patch.object(iftar_module, "datetime", fake_dt):
        iftar_module.check_today_slots()
    assert mock_telegram.call_count == 2


def test_english_site_detection(
    iftar_module,
    mock_datetime_now,
    mock_telegram,
    mock_save_state,
    target_date_str,
):
    """Simulated site in English: Brotherticket, Sisterticket, SOLD OUT still parsed."""
    iftar_module._first_run_after_load = False  # expect notification for sister
    def english_get(url: str):
        from unittest.mock import MagicMock
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status = MagicMock()
        if "127" in url or url.rstrip("/").endswith("/127"):
            r.text = detail_page(
                brother_available=False,
                sister_available=True,
                language="en",
            )
        else:
            r.text = calendar_page(target_date_str, "/127/", "few tickets left")
        return r

    with patch.object(iftar_module, "_get_with_retries", side_effect=english_get):
        iftar_module.check_today_slots()

    # Only sister available; one notification
    assert mock_telegram.call_count == 1
    assert "Schwester" in mock_telegram.call_args[0][0]
    assert iftar_module.last_states.get(("bruder", target_date_str)) is False
    assert iftar_module.last_states.get(("schwester", target_date_str)) is True


def test_sold_out_no_notification(
    iftar_module,
    mock_datetime_now,
    mock_telegram,
    mock_save_state,
    target_date_str,
):
    """Both tickets sold out: no Telegram notification."""
    def sold_out_get(url: str):
        from unittest.mock import MagicMock
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status = MagicMock()
        if "127" in url or url.rstrip("/").endswith("/127"):
            r.text = detail_page(
                brother_available=False,
                sister_available=False,
                language="de",
            )
        else:
            r.text = calendar_page(target_date_str, "/127/", "ausgebucht")
        return r

    with patch.object(iftar_module, "_get_with_retries", side_effect=sold_out_get):
        iftar_module.check_today_slots()

    assert mock_telegram.call_count == 0
    assert iftar_module.last_states.get(("bruder", target_date_str)) is False
    assert iftar_module.last_states.get(("schwester", target_date_str)) is False


def test_reserved_ticket_no_notification(
    iftar_module,
    mock_datetime_now,
    mock_telegram,
    mock_save_state,
    target_date_str,
):
    """Brother ticket Reserviert / Sister SOLD OUT: no 'available' notification (reserved is not bookable)."""
    def reserved_get(url: str):
        from unittest.mock import MagicMock
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status = MagicMock()
        if "127" in url or url.rstrip("/").endswith("/127"):
            r.text = detail_page(
                brother_available=False,
                sister_available=False,
                brother_reserved=True,
                sister_reserved=False,
                language="de",
            )
        else:
            r.text = calendar_page(target_date_str, "/127/", "reserviert")
        return r

    with patch.object(iftar_module, "_get_with_retries", side_effect=reserved_get):
        iftar_module.check_today_slots()

    assert mock_telegram.call_count == 0
    assert iftar_module.last_states.get(("bruder", target_date_str)) is False
    assert iftar_module.last_states.get(("schwester", target_date_str)) is False


def test_fetch_failure_returns_early(
    iftar_module,
    mock_datetime_now,
    mock_telegram,
    mock_save_state,
):
    """When _get_with_retries returns None, no notifications and no crash."""
    with patch.object(iftar_module, "_get_with_retries", return_value=None):
        iftar_module.check_today_slots()
    assert mock_telegram.call_count == 0
    assert iftar_module.consecutive_fetch_failures == 1


def test_no_day_cell_returns_early(
    iftar_module,
    mock_datetime_now,
    mock_telegram,
    mock_save_state,
    target_date_str,
):
    """Calendar with no matching date cell: no detail fetch, no notification."""
    wrong_date = "01.01.2030"
    cal_html = calendar_page(wrong_date, "/999/")

    def only_calendar(url: str):
        from unittest.mock import MagicMock
        r = MagicMock()
        r.text = cal_html
        r.status_code = 200
        r.raise_for_status = MagicMock()
        return r

    with patch.object(iftar_module, "_get_with_retries", side_effect=only_calendar):
        iftar_module.check_today_slots()

    # Script looks for data-date="25.02.2026"; our calendar has 01.01.2030 so no match
    assert mock_telegram.call_count == 0


def test_state_key_roundtrip(iftar_module):
    """State serialization key round-trip."""
    key = ("bruder", "25.02.2026")
    s = iftar_module._state_key(key)
    assert s == "bruder|25.02.2026"
    assert iftar_module._parse_state_key(s) == key
