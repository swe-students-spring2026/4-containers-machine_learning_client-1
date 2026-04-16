"""Tests for the Flask Web App."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import app


def test_home_route_status_code(client):
    """Test home route returns 200."""
    with patch("app.get_monitoring_control", return_value={}):
        response = client.get("/")

    assert response.status_code == 200


def test_status_route_returns_json(client):
    """Test that status route returns expected JSON."""
    with patch(
        "app.get_monitoring_control",
        return_value={
            "status": "running",
            "updated_at": 123.45,
            "alarm_active": True,
            "alarm_event_id": "abc123",
            "alarm_state": "looking_away",
            "alarm_triggered_at": 456.78,
        },
    ):
        response = client.get("/status")

    data = response.get_json()
    assert response.status_code == 200
    assert response.is_json
    assert data["monitoring"] is True
    assert data["updated_at"] == 123.45
    assert data["alarm"]["active"] is True
    assert data["alarm"]["event"]["id"] == "abc123"
    assert data["alarm"]["event"]["state"] == "looking_away"
    assert data["alarm"]["event"]["timestamp"] == 456.78


def test_start_monitoring_redirects(client):
    """Test start monitoring redirects to home page."""
    with patch("app.set_monitoring_status") as mock_set_status:
        response = client.post("/start")

    assert response.status_code == 302
    mock_set_status.assert_called_once_with("running")


def test_stop_monitoring_redirects(client):
    """Test stop monitoring redirects to home page."""
    with (
        patch("app.get_monitoring_control", return_value={}),
        patch("app.set_monitoring_status") as mock_set_status,
    ):
        response = client.post("/stop")

    assert response.status_code == 302
    mock_set_status.assert_called_once_with("stopped")


def test_dismiss_alarm_clears_alarm_state(client):
    """Test dismissing alarm returns updated status payload."""
    with (
        patch("app.control_collection.update_one") as mock_update,
        patch(
            "app.get_monitoring_control",
            return_value={"status": "running", "updated_at": 123.45},
        ),
    ):
        response = client.post("/alarm/dismiss")

    data = response.get_json()
    assert response.status_code == 200
    assert response.is_json
    assert data["ok"] is True
    assert data["monitoring"] is True
    assert data["alarm"]["active"] is False
    mock_update.assert_called_once()


def test_events_invalid_after_id_returns_400(client):
    """Test invalid after_id returns 400."""
    response = client.get("/events?after_id=not-a-real-objectid")

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"] == "invalid after_id"


def test_events_returns_flagged_events(client):
    """Test flagged events are returned as JSON."""
    fake_record = {
        "_id": "abc123",
        "timestamp": 123.45,
        "state": "looking_away",
        "flag": True,
    }

    fake_cursor = Mock()
    fake_cursor.sort.return_value = [fake_record]

    with patch("app.event_collection.find", return_value=fake_cursor):
        response = client.get("/events")

    data = response.get_json()
    assert response.status_code == 200
    assert response.is_json
    assert "events" in data
    assert len(data["events"]) == 1
    assert data["events"][0]["timestamp"] == 123.45
    assert data["events"][0]["state"] == "looking_away"
    assert data["events"][0]["flag"] is True


def test_ingest_frame_missing_image_returns_400(client):
    """Test missing frame payload returns 400."""
    response = client.post("/frames", json={})

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"] == "missing image_base64"


def test_ingest_frame_invalid_base64_returns_400(client):
    """Test invalid base64 frame payload returns 400."""
    response = client.post("/frames", json={"image_base64": "not-base64!"})

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"] == "invalid image_base64"


def test_ingest_frame_stores_document(client):
    """Test valid frame payload is stored."""
    with patch("app.frame_collection.insert_one") as mock_insert:
        response = client.post("/frames", json={"image_base64": "aGVsbG8="})

    assert response.status_code == 201
    assert response.is_json
    assert response.get_json()["ok"] is True
    mock_insert.assert_called_once()


def test_stats_no_sessions(client):
    """Test /stats returns session_count 0 when global stats doc is missing."""
    with patch("app.global_stats_collection.find_one", return_value=None):
        response = client.get("/stats")

    assert response.status_code == 200
    data = response.get_json()
    assert data["session_count"] == 0
    assert data["sessions_count"] == 0
    assert data["avg_threshold"] == app.get_env_float("FLAG_THRESHOLD_SEC", 0.0)
    assert data["avg_alarm_count"] == 0.0
    assert data["avg_duration_sec"] == 0.0
    assert data["last_session"]["flag_threshold_sec"] == app.get_env_float(
        "FLAG_THRESHOLD_SEC", 0.0
    )
    assert data["last_session"]["focused_duration_sec"] == 0.0
    assert data["last_session"]["alarm_count"] == 0
    assert data["last_session"]["duration_sec"] == 0.0


def test_stats_returns_global_values(client):
    """Test /stats returns stored aggregate values."""
    fake_global_stats = {
        "_id": "global",
        "session_count": 2,
        "total_duration_sec": 200.0,
        "avg_attention_duration_sec": 90.0,
        "avg_attention_ratio": 0.75,
        "avg_alert_count": 3.0,
        "last_session": {
            "flag_threshold_sec": 5.0,
            "focused_duration_sec": 77.0,
            "alarm_count": 4,
            "duration_sec": 88.0,
        },
    }

    with (
        patch("app.global_stats_collection.find_one", return_value=fake_global_stats),
        patch.dict(
            "os.environ",
            {
                "GLOBAL_AVG_ALARM_COUNT": "",
                "GLOBAL_AVG_DURATION_SEC": "",
            },
            clear=False,
        ),
    ):
        response = client.get("/stats")

    data = response.get_json()
    assert data["session_count"] == 2
    assert data["sessions_count"] == 2
    assert data["avg_attention_duration_sec"] == 90.0
    assert data["avg_attention_ratio"] == 0.75
    assert data["avg_alert_count"] == 3.0
    assert data["avg_alarm_count"] == 3.0
    assert data["avg_duration_sec"] == 100.0
    assert data["last_session"]["flag_threshold_sec"] == 5.0
    assert data["last_session"]["focused_duration_sec"] == 77.0
    assert data["last_session"]["alarm_count"] == 4
    assert data["last_session"]["duration_sec"] == 88.0


def test_stats_no_sessions_uses_env_defaults(client):
    """Test /stats uses env defaults when aggregate document is missing."""
    with (
        patch("app.global_stats_collection.find_one", return_value=None),
        patch.dict(
            "os.environ",
            {
                "GLOBAL_AVG_THRESHOLD_SEC": "7.5",
                "GLOBAL_AVG_ALARM_COUNT": "1.25",
                "GLOBAL_AVG_DURATION_SEC": "42",
            },
            clear=False,
        ),
    ):
        response = client.get("/stats")

    data = response.get_json()
    assert data["session_count"] == 0
    assert data["sessions_count"] == 0
    assert data["avg_threshold"] == 7.5
    assert data["avg_alarm_count"] == 1.25
    assert data["avg_duration_sec"] == 42.0
    assert data["last_session"]["flag_threshold_sec"] == app.get_env_float(
        "FLAG_THRESHOLD_SEC", 0.0
    )
    assert data["last_session"]["focused_duration_sec"] == 0.0
    assert data["last_session"]["alarm_count"] == 0
    assert data["last_session"]["duration_sec"] == 0.0


def test_update_global_stats_uses_env_seed_defaults():
    """Test update_global_stats starts from env seed values when no DB doc exists."""
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
        patch.dict(
            "os.environ",
            {
                "GLOBAL_STATS_SESSION_COUNT": "2",
                "GLOBAL_STATS_TOTAL_DURATION_SEC": "80",
                "GLOBAL_STATS_TOTAL_ALARM_DURATION_SEC": "8",
                "GLOBAL_STATS_TOTAL_ATTENTION_DURATION_SEC": "72",
                "GLOBAL_STATS_TOTAL_ATTENTION_RATIO": "1.5",
                "GLOBAL_STATS_TOTAL_ALERT_COUNT": "4",
            },
            clear=False,
        ),
    ):
        result = app.update_global_stats(session_stats)

    assert result["session_count"] == 3
    assert result["total_duration_sec"] == 140.0
    assert result["total_alarm_duration_sec"] == 18.0
    assert result["total_attention_duration_sec"] == 122.0
    assert result["total_alert_count"] == 5
    assert result["avg_attention_duration_sec"] == 122.0 / 3.0
    assert result["avg_alert_count"] == 5.0 / 3.0
    assert result["last_session"]["flag_threshold_sec"] == app.get_env_float(
        "FLAG_THRESHOLD_SEC", 0.0
    )
    assert result["last_session"]["focused_duration_sec"] == 50.0
    assert result["last_session"]["alarm_count"] == 1
    assert result["last_session"]["duration_sec"] == 60.0
    mock_replace.assert_called_once()


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


def test_build_alarm_payload_inactive():
    """Test build_alarm_payload for inactive alarm."""
    result = app.build_alarm_payload({})

    assert result["active"] is False
    assert result["event"] is None


def test_build_alarm_payload_active():
    """Test build_alarm_payload for active alarm."""
    control = {
        "alarm_active": True,
        "alarm_event_id": "abc123",
        "alarm_triggered_at": 456.78,
        "alarm_state": "looking_away",
    }

    result = app.build_alarm_payload(control)

    assert result["active"] is True
    assert result["event"]["id"] == "abc123"
    assert result["event"]["timestamp"] == 456.78
    assert result["event"]["state"] == "looking_away"


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


def test_compute_session_attention_returns_none_without_start():
    """Test compute_session_attention returns None when start is missing."""
    events = [
        {
            "label": "end",
            "timestamp": datetime(2026, 4, 15, 12, 1, 0, tzinfo=timezone.utc),
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


def test_compute_session_attention_sorts_events():
    """Test compute_session_attention sorts events by timestamp."""
    events = [
        {"label": "end", "timestamp": 160.0},
        {"label": "start", "timestamp": 100.0},
    ]

    result = app.compute_session_attention(events)

    assert result["duration_sec"] == 60.0
    assert result["attention_duration_sec"] == 60.0


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


def test_compute_session_attention_ignores_duplicate_alarm_start():
    """Test duplicate alarm-start does not double count alerts."""
    events = [
        {"label": "start", "timestamp": 100.0},
        {"label": "alarm-start", "timestamp": 110.0},
        {"label": "alarm-start", "timestamp": 115.0},
        {"label": "alarm-end", "timestamp": 120.0},
        {"label": "end", "timestamp": 130.0},
    ]

    result = app.compute_session_attention(events)

    assert result["alarm_duration_sec"] == 10.0
    assert result["alert_count"] == 1


def test_compute_session_attention_ignores_alarm_end_without_start():
    """Test alarm-end without an open alarm is ignored."""
    events = [
        {"label": "start", "timestamp": 100.0},
        {"label": "alarm-end", "timestamp": 105.0},
        {"label": "end", "timestamp": 130.0},
    ]

    result = app.compute_session_attention(events)

    assert result["alarm_duration_sec"] == 0.0
    assert result["attention_duration_sec"] == 30.0
    assert result["alert_count"] == 0


def test_compute_session_attention_closes_open_alarm_at_end_datetime():
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


def test_compute_session_attention_closes_open_alarm_at_end_float():
    """Test compute_session_attention closes open alarm at end with float timestamps."""
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
    assert result["avg_attention_duration_sec"] == 50.0
    assert result["avg_alert_count"] == 1.0
    assert result["last_session"]["flag_threshold_sec"] == app.get_env_float(
        "FLAG_THRESHOLD_SEC", 0.0
    )
    assert result["last_session"]["focused_duration_sec"] == 50.0
    assert result["last_session"]["alarm_count"] == 1
    assert result["last_session"]["duration_sec"] == 60.0
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
    assert result["avg_attention_duration_sec"] == 42.5
    assert result["avg_alert_count"] == 1.5
    assert result["last_session"]["flag_threshold_sec"] == app.get_env_float(
        "FLAG_THRESHOLD_SEC", 0.0
    )
    assert result["last_session"]["focused_duration_sec"] == 35.0
    assert result["last_session"]["alarm_count"] == 2
    assert result["last_session"]["duration_sec"] == 40.0
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


def test_stop_monitoring_uses_fallback_when_session_stats_none(client):
    """Test stop_monitoring uses fallback stats when computed stats are missing."""
    fake_control = {
        "session_start_at": datetime.now(timezone.utc) - timedelta(seconds=3),
    }
    fake_events = [
        {
            "label": "start",
            "session_id": "abc",
            "timestamp": fake_control["session_start_at"],
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
    mock_update.assert_called_once()
    fallback_stats = mock_update.call_args[0][0]
    assert fallback_stats["duration_sec"] >= 0.0
    assert fallback_stats["alarm_duration_sec"] == 0.0
    assert fallback_stats["attention_duration_sec"] == fallback_stats["duration_sec"]
    if fallback_stats["duration_sec"] > 0:
        assert fallback_stats["attention_ratio"] == 1.0
    else:
        assert fallback_stats["attention_ratio"] == 0.0
    assert fallback_stats["alert_count"] == 0


def test_status_started_at_with_float_timestamp(client):
    """Test /status handles float session_start_at without AttributeError."""
    with patch(
        "app.get_monitoring_control",
        return_value={
            "status": "running",
            "session_start_at": 1713200000.0,
            "updated_at": 1713200000.0,
        },
    ):
        response = client.get("/status")

    assert response.status_code == 200
    data = response.get_json()
    assert data["started_at"] == 1713200000.0


def test_stop_monitoring_queries_events_with_float_timestamp(client):
    """Test stop_monitoring converts session_start_at to float for event query."""

    fake_control = {
        "session_start_at": datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    }
    expected_ts = fake_control["session_start_at"].timestamp()

    with (
        patch("app.get_monitoring_control", return_value=fake_control),
        patch("app.set_monitoring_status"),
        patch("app.event_collection.find", return_value=[]) as mock_find,
        patch("app.update_global_stats"),
        patch("time.sleep"),
    ):
        client.post("/stop")

    call_query = mock_find.call_args[0][0]
    assert call_query["timestamp"]["$gte"] == expected_ts
