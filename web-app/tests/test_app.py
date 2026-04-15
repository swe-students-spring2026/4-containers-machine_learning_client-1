"""Tests for the Flask Web App Routes"""

from unittest.mock import Mock, patch


def test_home_route_status_code(client):
    """Test home route returns to 200"""
    with patch("app.get_monitoring_control", return_value={}):
        response = client.get("/")

    assert response.status_code == 200


def test_status_route_returns_json(client):
    """Test that route returns expected JSON"""
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

    assert response.status_code == 200
    assert response.is_json
    assert response.get_json()["monitoring"] is True
    assert response.get_json()["updated_at"] == 123.45
    assert response.get_json()["alarm"]["active"] is True
    assert response.get_json()["alarm"]["event"]["id"] == "abc123"
    assert response.get_json()["alarm"]["event"]["state"] == "looking_away"
    assert response.get_json()["alarm"]["event"]["timestamp"] == 456.78


def test_start_monitoring_redirects(client):
    """Tests that start monitoring redirects to home page"""
    with patch("app.set_monitoring_status") as mock_set_status:
        response = client.post("/start")

    assert response.status_code == 302
    mock_set_status.assert_called_once_with("running")


def test_stop_monitoring_redirects(client):
    """Test that stop monitoring redirects to home page"""
    with (
        patch("app.set_monitoring_status") as mock_set_status,
        patch("app.save_session_summary") as mock_save,
    ):
        response = client.post("/stop")

    assert response.status_code == 302
    mock_set_status.assert_called_once_with("stopped")
    mock_save.assert_called_once()


def test_dismiss_alarm_clears_alarm_state(client):
    """Test that dismissing the alarm returns an updated status payload."""
    with (
        patch("app.control_collection.update_one") as mock_update,
        patch(
            "app.get_monitoring_control",
            return_value={"status": "running", "updated_at": 123.45},
        ),
    ):
        response = client.post("/alarm/dismiss")

    assert response.status_code == 200
    assert response.is_json
    assert response.get_json()["ok"] is True
    assert response.get_json()["monitoring"] is True
    assert response.get_json()["alarm"]["active"] is False
    mock_update.assert_called_once()


def test_events_invalid_after_id_returns_400(client):
    """Test that invalid after_id returns to 400"""
    response = client.get("/events?after_id=not-a-real-objectid")

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"] == "invalid after_id"


def test_events_returns_flagged_events(client):
    """Test that flagged events are returned as JSON"""
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

    assert response.status_code == 200
    assert response.is_json

    data = response.get_json()
    assert "events" in data
    assert len(data["events"]) == 1
    assert data["events"][0]["timestamp"] == 123.45
    assert data["events"][0]["state"] == "looking_away"
    assert data["events"][0]["flag"] is True


def test_ingest_frame_missing_image_returns_400(client):
    """Test that missing frame payload returns 400."""
    response = client.post("/frames", json={})

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"] == "missing image_base64"


def test_ingest_frame_invalid_base64_returns_400(client):
    """Test that invalid base64 frame payload returns 400."""
    response = client.post("/frames", json={"image_base64": "not-base64!"})

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"] == "invalid image_base64"


def test_ingest_frame_stores_document(client):
    """Test that valid frame payload is stored."""
    with patch("app.frame_collection.insert_one") as mock_insert:
        response = client.post("/frames", json={"image_base64": "aGVsbG8="})

    assert response.status_code == 201
    assert response.is_json
    assert response.get_json()["ok"] is True
    mock_insert.assert_called_once()


def test_stats_no_sessions(client):
    """Test /stats returns sessions_count 0 when collection is empty."""
    with patch("app.session_collection.find", return_value=[]):
        response = client.get("/stats")

    assert response.status_code == 200
    assert response.get_json()["sessions_count"] == 0


def test_stats_includes_last_session(client):
    """Test /stats includes the most recent session data."""
    fake_sessions = [
        {"flag_threshold_sec": 5.0, "alarm_count": 2, "duration_sec": 60.0},
        {"flag_threshold_sec": 5.0, "alarm_count": 4, "duration_sec": 120.0},
    ]
    with (
        patch("app.session_collection.find", return_value=fake_sessions),
        patch("app.session_collection.find_one", return_value=fake_sessions[-1]),
    ):
        response = client.get("/stats")

    data = response.get_json()
    assert "last_session" in data
    assert data["last_session"]["flag_threshold_sec"] == 5.0
    assert data["last_session"]["alarm_count"] == 4
    assert data["last_session"]["duration_sec"] == 120.0


def test_stats_returns_averages(client):
    """Test /stats computes averages across sessions."""
    fake_sessions = [
        {"flag_threshold_sec": 5.0, "alarm_count": 2, "duration_sec": 60.0},
        {"flag_threshold_sec": 5.0, "alarm_count": 4, "duration_sec": 120.0},
    ]
    with patch("app.session_collection.find", return_value=fake_sessions):
        response = client.get("/stats")

    data = response.get_json()
    assert data["sessions_count"] == 2
    assert data["avg_threshold"] == 5.0
    assert data["avg_alarm_count"] == 3.0
    assert data["avg_duration_sec"] == 90.0


def test_average_without_outliers_removes_outlier():
    """Test that values beyond 1 stdev are excluded."""
    from app import average_without_outliers
    # 100 is an outlier relative to 1,2,3
    result = average_without_outliers([1.0, 2.0, 3.0, 100.0])
    assert result < 10.0