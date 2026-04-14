"""Tests for the machine learning client."""

import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ["MONGO_URI"] = "mongodb://localhost:27017"

import client  # pylint: disable=wrong-import-position


def make_detection_result(face_landmarks):
    """Build a fake MediaPipe detection result."""
    return SimpleNamespace(face_landmarks=face_landmarks)


def make_landmarks(nose_x, left_cheek_x, right_cheek_x, size=500):
    """Build a landmark list large enough for the indices used."""
    landmarks = [SimpleNamespace(x=0.0) for _ in range(size)]
    landmarks[client.NOSE_TIP_INDEX] = SimpleNamespace(x=nose_x)
    landmarks[client.LEFT_CHEEK_INDEX] = SimpleNamespace(x=left_cheek_x)
    landmarks[client.RIGHT_CHEEK_INDEX] = SimpleNamespace(x=right_cheek_x)
    return landmarks


def test_is_monitoring_enabled_true():
    """Return True when monitoring status is running."""
    control_collection = Mock()
    control_collection.find_one.return_value = {
        "_id": "monitoring",
        "status": "running",
    }

    assert client.is_monitoring_enabled(control_collection) is True


def test_is_monitoring_enabled_false_when_missing():
    """Return False when no monitoring control document exists."""
    control_collection = Mock()
    control_collection.find_one.return_value = None

    assert client.is_monitoring_enabled(control_collection) is False


def test_is_monitoring_enabled_false_when_not_running():
    """Return False when monitoring status is not running."""
    control_collection = Mock()
    control_collection.find_one.return_value = {
        "_id": "monitoring",
        "status": "stopped",
    }

    assert client.is_monitoring_enabled(control_collection) is False


def test_classify_attention_absent():
    """Return absent when no face landmarks are detected."""
    detection_result = make_detection_result([])

    assert client.classify_attention(detection_result) == "absent"


def test_classify_attention_attentive():
    """Return attentive when the nose is near the face center."""
    landmarks = make_landmarks(
        nose_x=0.50,
        left_cheek_x=0.40,
        right_cheek_x=0.60,
    )
    detection_result = make_detection_result([landmarks])

    assert client.classify_attention(detection_result) == "attentive"


def test_classify_attention_looking_away():
    """Return looking_away when the nose deviates too much."""
    landmarks = make_landmarks(
        nose_x=0.80,
        left_cheek_x=0.40,
        right_cheek_x=0.60,
    )
    detection_result = make_detection_result([landmarks])

    assert client.classify_attention(detection_result) == "looking_away"


def test_classify_attention_zero_cheek_span_returns_attentive():
    """Return attentive when cheek span is zero."""
    landmarks = make_landmarks(
        nose_x=0.50,
        left_cheek_x=0.40,
        right_cheek_x=0.40,
    )
    detection_result = make_detection_result([landmarks])

    assert client.classify_attention(detection_result) == "attentive"


@patch("client.os.path.exists", return_value=False)
def test_create_landmarker_returns_none_when_model_missing(_mock_exists):
    """Return None when the model file is missing."""
    assert client.create_landmarker() is None


@patch("client.cv2.cvtColor", return_value="rgb_frame")
@patch("client.mp.Image")
@patch("client.classify_attention", return_value="attentive")
@patch("client.time.time", return_value=1234567890.0)
@patch("client.time.monotonic", side_effect=[100.0, 100.0])
def test_process_frame_attentive_updates_timer(
    _mock_monotonic,
    _mock_time,
    _mock_classify,
    _mock_image,
    _mock_cvtcolor,
):
    """Update the attentive timer and avoid flagging when attentive."""
    landmarker = Mock()
    landmarker.detect.return_value = make_detection_result([])

    event, last_attentive_at = client.process_frame(
        frame="frame",
        landmarker=landmarker,
        last_attentive_at=90.0,
    )

    assert event["timestamp"] == 1234567890.0
    assert event["state"] == "attentive"
    assert event["flag"] is False
    assert last_attentive_at == 100.0


@patch("client.cv2.cvtColor", return_value="rgb_frame")
@patch("client.mp.Image")
@patch("client.classify_attention", return_value="looking_away")
@patch("client.time.time", return_value=1234567890.0)
@patch("client.time.monotonic", side_effect=[200.0, 200.0])
def test_process_frame_flags_when_over_threshold(
    _mock_monotonic,
    _mock_time,
    _mock_classify,
    _mock_image,
    _mock_cvtcolor,
):
    """Flag the event when inattention exceeds the threshold."""
    landmarker = Mock()
    landmarker.detect.return_value = make_detection_result([])

    event, last_attentive_at = client.process_frame(
        frame="frame",
        landmarker=landmarker,
        last_attentive_at=190.0,
    )

    assert event["timestamp"] == 1234567890.0
    assert event["state"] == "looking_away"
    assert event["flag"] is True
    assert last_attentive_at == 190.0


@patch("client.create_landmarker", return_value=None)
def test_run_monitoring_exits_when_no_landmarker(_mock_landmarker):
    """run_monitoring exits early if landmarker is None."""
    collection = Mock()
    control_collection = Mock()
    frame_collection = Mock()

    client.run_monitoring(collection, control_collection, frame_collection)


@patch("client.time.sleep")
@patch("client.create_landmarker")
@patch("client.is_monitoring_enabled", side_effect=[True, False])
def test_run_monitoring_no_frames(
    _mock_monitoring_enabled,
    mock_create_landmarker,
    _mock_sleep,
):
    """run_monitoring exits cleanly when no frames are available."""
    landmarker = Mock()
    mock_create_landmarker.return_value = landmarker

    frame_collection = Mock()
    frame_collection.find_one.side_effect = [None, None]

    client.run_monitoring(Mock(), Mock(), frame_collection)

    assert frame_collection.find_one.call_count >= 2
    landmarker.close.assert_called_once()
