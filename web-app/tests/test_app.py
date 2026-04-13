from unittest.mock import Mock, patch


def test_home_route_status_code(client):
    with patch("app.get_monitoring_control", return_value={}):
        response = client.get("/")

    assert response.status_code == 200


def test_status_route_returns_json(client):
    with patch(
        "app.get_monitoring_control",
        return_value={"status": "running", "updated_at": 123.45},
    ):
        response = client.get("/status")

    assert response.status_code == 200
    assert response.is_json
    assert response.get_json()["monitoring"] is True
    assert response.get_json()["updated_at"] == 123.45


def test_start_monitoring_redirects(client):
    with patch("app.set_monitoring_status") as mock_set_status:
        response = client.post("/start")

    assert response.status_code == 302
    mock_set_status.assert_called_once_with("running")


def test_stop_monitoring_redirects(client):
    with patch("app.set_monitoring_status") as mock_set_status:
        response = client.post("/stop")

    assert response.status_code == 302
    mock_set_status.assert_called_once_with("stopped")


def test_events_invalid_after_id_returns_400(client):
    response = client.get("/events?after_id=not-a-real-objectid")

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"] == "invalid after_id"


def test_events_returns_flagged_events(client):
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

