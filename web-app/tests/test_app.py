"""Test Cases For Web App"""

from datetime import datetime, timezone
from unittest.mock import patch

import app


def test_to_seconds_with_datetime():
    """Test to_seconds converts datetime to float seconds."""
    ts = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    result = app.to_seconds(ts)

    assert isinstance(result, float)
    assert result == ts.timestamp()


def test_to_seconds_with_float():
    """Test to_seconds returns float unchanged."""
    result = app.to_seconds(123.45)

    assert result == 123.45


def test_compute_session_attention_returns_none_for_empty_events():
    """Test compute_session_attention returns None for no events."""
    assert app.compute_session_attention([]) is None


def test_compute_session_attention_returns_none_without_end():
    """Test compute_session_attention returns None when end is missing."""
    events = [
        {
            "label": "start",
            "timestamp": datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc),
        }
    ]

    assert app.compute_session_attention(events) is None


def test_compute_session_attention_no_alarm():
    """Test compute_session_attention for simple start/end session."""
    events = [
        {
            "label": "start",
            "timestamp": datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc),
        },
        {
            "label": "end",
            "timestamp": datetime(2026, 4, 15, 12, 1, 0, tzinfo=timezone.utc),
        },
    ]

    result = app.compute_session_attention(events)

    assert result["duration_sec"] == 60.0
    assert result["alarm_duration_sec"] == 0.0
    assert result["attention_duration_sec"] == 60.0
    assert result["attention_ratio"] == 1.0
    assert result["alert_count"] == 0


def test_compute_session_attention_with_alarm():
    """Test compute_session_attention with one alarm interval."""
    events = [
        {
            "label": "start",
            "timestamp": datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc),
        },
        {
            "label": "alarm-start",
            "timestamp": datetime(2026, 4, 15, 12, 0, 10, tzinfo=timezone.utc),
        },
        {
            "label": "alarm-end",
            "timestamp": datetime(2026, 4, 15, 12, 0, 20, tzinfo=timezone.utc),
        },
        {
            "label": "end",
            "timestamp": datetime(2026, 4, 15, 12, 1, 0, tzinfo=timezone.utc),
        },
    ]

    result = app.compute_session_attention(events)

    assert result["duration_sec"] == 60.0
    assert result["alarm_duration_sec"] == 10.0
    assert result["attention_duration_sec"] == 50.0
    assert result["attention_ratio"] == 50.0 / 60.0
    assert result["alert_count"] == 1


def test_compute_session_attention_closes_open_alarm_at_end():
    """Test compute_session_attention treats end as alarm-end when needed."""
    events = [
        {
            "label": "start",
            "timestamp": datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc),
        },
        {
            "label": "alarm-start",
            "timestamp": datetime(2026, 4, 15, 12, 0, 30, tzinfo=timezone.utc),
        },
        {
            "label": "end",
            "timestamp": datetime(2026, 4, 15, 12, 1, 0, tzinfo=timezone.utc),
        },
    ]

    result = app.compute_session_attention(events)

    assert result["duration_sec"] == 60.0
    assert result["alarm_duration_sec"] == 30.0
    assert result["attention_duration_sec"] == 30.0
    assert result["alert_count"] == 1


def test_update_global_stats_creates_new_global_doc():
    """Test update_global_stats creates a new aggregate document."""
    session_stats = {
        "duration_sec": 60.0,
        "alarm_duration_sec": 10.0,
        "attention_duration_sec": 50.0,
        "attention_ratio": 50.0 / 60.0,
        "alert_count": 1,
    }

    with (
        patch("app.global_stats_collection.find_one", return_value=None),
        patch("app.global_stats_collection.replace_one") as mock_replace,
    ):
        result = app.update_global_stats(session_stats)

    assert result["session_count"] == 1
    assert result["total_duration_sec"] == 60.0
    assert result["total_alarm_duration_sec"] == 10.0
    assert result["total_attention_duration_sec"] == 50.0
    assert result["total_alert_count"] == 1
    mock_replace.assert_called_once()


def test_update_global_stats_updates_existing_doc():
    """Test update_global_stats updates an existing aggregate document."""
    existing = {
        "_id": "global",
        "session_count": 1,
        "total_duration_sec": 60.0,
        "total_alarm_duration_sec": 10.0,
        "total_attention_duration_sec": 50.0,
        "total_attention_ratio": 0.8,
        "total_alert_count": 1,
    }
    session_stats = {
        "duration_sec": 40.0,
        "alarm_duration_sec": 5.0,
        "attention_duration_sec": 35.0,
        "attention_ratio": 0.875,
        "alert_count": 2,
    }

    with (
        patch("app.global_stats_collection.find_one", return_value=existing),
        patch("app.global_stats_collection.replace_one") as mock_replace,
    ):
        result = app.update_global_stats(session_stats)

    assert result["session_count"] == 2
    assert result["total_duration_sec"] == 100.0
    assert result["total_alarm_duration_sec"] == 15.0
    assert result["total_attention_duration_sec"] == 85.0
    assert result["total_alert_count"] == 3
    mock_replace.assert_called_once()


def test_stop_monitoring_updates_global_stats(client):
    """Test stop_monitoring computes stats and updates globals."""
    fake_control = {
        "session_start_at": datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    }
    fake_events = [
        {
            "label": "start",
            "session_id": "abc",
            "timestamp": datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc),
        },
        {
            "label": "end",
            "session_id": "abc",
            "timestamp": datetime(2026, 4, 15, 12, 1, 0, tzinfo=timezone.utc),
        },
    ]
    fake_stats = {
        "duration_sec": 60.0,
        "alarm_duration_sec": 0.0,
        "attention_duration_sec": 60.0,
        "attention_ratio": 1.0,
        "alert_count": 0,
    }

    with (
        patch("app.get_monitoring_control", return_value=fake_control),
        patch("app.set_monitoring_status") as mock_set_status,
        patch("app.event_collection.find", return_value=fake_events),
        patch("app.compute_session_attention", return_value=fake_stats),
        patch("app.update_global_stats") as mock_update,
    ):
        response = client.post("/stop")

    assert response.status_code == 302
    mock_set_status.assert_called_once_with("stopped")
    mock_update.assert_called_once_with(fake_stats)


def test_stop_monitoring_skips_update_when_no_session_start(client):
    """Test stop_monitoring skips stats update when no session_start_at exists."""
    with (
        patch("app.get_monitoring_control", return_value={}),
        patch("app.set_monitoring_status") as mock_set_status,
        patch("app.update_global_stats") as mock_update,
    ):
        response = client.post("/stop")

    assert response.status_code == 302
    mock_set_status.assert_called_once_with("stopped")
    mock_update.assert_not_called()


def test_compute_session_attention_returns_none_without_end():
    """Test compute_session_attention returns None when end is missing."""
    events = [
        {
            "label": "start",
            "timestamp": 100.0,
        }
    ]

    result = app.compute_session_attention(events)

    assert result is None


def test_stop_monitoring_skips_update_when_session_stats_none(client):
    """Test stop_monitoring does not update globals when session stats are None."""
    fake_control = {
        "session_start_at": 100.0,
    }
    fake_events = [
        {
            "label": "start",
            "session_id": "abc",
            "timestamp": 100.0,
        }
    ]

    with (
        patch("app.get_monitoring_control", return_value=fake_control),
        patch("app.set_monitoring_status") as mock_set_status,
        patch("app.event_collection.find", return_value=fake_events),
        patch("app.compute_session_attention", return_value=None),
        patch("app.update_global_stats") as mock_update,
    ):
        response = client.post("/stop")

    assert response.status_code == 302
    mock_set_status.assert_called_once_with("stopped")
    mock_update.assert_not_called()


def test_compute_session_attention_closes_open_alarm_at_end():
    """Test compute_session_attention closes an open alarm at end."""
    events = [
        {"label": "start", "timestamp": 100.0},
        {"label": "alarm-start", "timestamp": 110.0},
        {"label": "end", "timestamp": 130.0},
    ]

    result = app.compute_session_attention(events)

    assert result["duration_sec"] == 30.0
    assert result["alarm_duration_sec"] == 20.0
    assert result["attention_duration_sec"] == 10.0
    assert result["alert_count"] == 1
