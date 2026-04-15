"""Tests for the machine learning client."""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from pymongo.errors import PyMongoError

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


def test_is_alarm_active_true():
    """Return True when an alarm is active."""
    control_collection = Mock()
    control_collection.find_one.return_value = {
        "_id": "monitoring",
        "alarm_active": True,
    }

    assert client.is_alarm_active(control_collection) is True


def test_is_alarm_active_false_when_missing():
    """Return False when no alarm is active."""
    control_collection = Mock()
    control_collection.find_one.return_value = None

    assert client.is_alarm_active(control_collection) is False


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


@patch("client.os.path.exists", return_value=True)
@patch(
    "client.vision.FaceLandmarker.create_from_options",
    side_effect=OSError("libGLESv2.so.2: cannot open shared object file"),
)
def test_create_landmarker_returns_none_when_native_library_missing(
    _mock_create,
    _mock_exists,
):
    """Return None when MediaPipe native dependencies cannot be loaded."""
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


def test_activate_alarm_updates_control_document():
    """Persist the alarm metadata in the monitoring control document."""
    control_collection = Mock()
    event = {
        "state": "looking_away",
        "timestamp": 1234567890.0,
    }

    client.activate_alarm(control_collection, "event-id", event)

    control_collection.update_one.assert_called_once_with(
        {"_id": "monitoring"},
        {
            "$set": {
                "alarm_active": True,
                "alarm_event_id": "event-id",
                "alarm_state": "looking_away",
                "alarm_triggered_at": 1234567890.0,
            }
        },
        upsert=True,
    )


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


@patch("client.cv2.imdecode", return_value="decoded_frame")
@patch("client.np.frombuffer", return_value="np_buffer")
def test_decode_frame_valid_base64(_mock_frombuffer, _mock_imdecode):
    """decode_frame returns an image for valid base64 payload."""
    frame_document = {"image_base64": "aGVsbG8="}

    decoded = client.decode_frame(frame_document)

    assert decoded == "decoded_frame"


def test_decode_frame_invalid_base64_returns_none():
    """decode_frame returns None when base64 is invalid."""
    frame_document = {"image_base64": "not-base64!!!"}

    decoded = client.decode_frame(frame_document)

    assert decoded is None


@patch("client.process_frame", return_value=({"state": "attentive"}, 10.0))
@patch("client.decode_frame", return_value="frame")
@patch("client.is_monitoring_enabled", side_effect=[True, False])
@patch("client.create_landmarker")
def test_run_monitoring_inserts_event(
    mock_create_landmarker,
    _mock_enabled,
    _mock_decode_frame,
    _mock_process_frame,
):
    """run_monitoring processes one frame and inserts one event."""
    landmarker = Mock()
    mock_create_landmarker.return_value = landmarker

    collection = Mock()
    control_collection = Mock()
    frame_collection = Mock()
    frame_collection.find_one.side_effect = [
        None,
        {"_id": "frame1", "image_base64": "aGVsbG8="},
    ]

    client.run_monitoring(collection, control_collection, frame_collection)

    collection.insert_one.assert_any_call({"state": "attentive"})
    landmarker.close.assert_called_once()


@patch("client.time.sleep", side_effect=KeyboardInterrupt)
@patch("client.is_monitoring_enabled", return_value=False)
@patch("client.MongoClient")
def test_main_stops_cleanly_on_keyboard_interrupt(
    mock_mongo_client,
    _mock_enabled,
    _mock_sleep,
):
    """main returns 0 and closes mongo client on interruption."""
    mongo_instance = MagicMock()
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=Mock())
    mongo_instance.__getitem__.return_value = db
    mock_mongo_client.return_value = mongo_instance

    result = client.main()

    assert result == 0
    mongo_instance.close.assert_called_once()


@patch("client.time.sleep", side_effect=KeyboardInterrupt)
@patch("client.run_monitoring")
@patch("client.is_monitoring_enabled", return_value=True)
@patch("client.MongoClient")
def test_main_calls_run_monitoring_when_enabled(
    mock_mongo_client,
    _mock_enabled,
    mock_run_monitoring,
    _mock_sleep,
):
    """main calls run_monitoring when monitoring is enabled."""
    mongo_instance = MagicMock()
    db = MagicMock()
    event_collection = Mock()
    control_collection = Mock()
    frame_collection = Mock()
    db.__getitem__.side_effect = [
        event_collection,
        control_collection,
        frame_collection,
    ]
    mongo_instance.__getitem__.return_value = db
    mock_mongo_client.return_value = mongo_instance

    client.main()

    mock_run_monitoring.assert_called_once_with(
        event_collection,
        control_collection,
        frame_collection,
    )


@patch("client.decode_frame", return_value="frame")
@patch("client.process_frame", return_value=({"state": "attentive"}, 10.0))
@patch("client.is_monitoring_enabled", side_effect=[True, False])
@patch("client.create_landmarker")
def test_run_monitoring_handles_insert_error(
    mock_create_landmarker,
    _mock_enabled,
    _mock_process_frame,
    _mock_decode,
):
    """run_monitoring handles insert exceptions and still closes resources."""
    landmarker = Mock()
    mock_create_landmarker.return_value = landmarker

    collection = Mock()
    collection.insert_one.side_effect = PyMongoError("write failed")
    frame_collection = Mock()
    frame_collection.find_one.side_effect = [
        {"_id": "frame1", "image_base64": "aGVsbG8="},
        None,
    ]

    client.run_monitoring(collection, Mock(), frame_collection)

    landmarker.close.assert_called_once()


@patch("client.time.sleep")
@patch("client.is_alarm_active", side_effect=[True, False])
@patch("client.is_monitoring_enabled", side_effect=[True, False])
@patch("client.create_landmarker")
def test_run_monitoring_waits_while_alarm_active(
    mock_create_landmarker,
    _mock_monitoring_enabled,
    _mock_alarm_active,
    mock_sleep,
):
    """run_monitoring pauses frame processing until the alarm is dismissed."""
    landmarker = Mock()
    mock_create_landmarker.return_value = landmarker
    frame_collection = Mock()

    client.run_monitoring(Mock(), Mock(), frame_collection)

    frame_collection.find_one.assert_not_called()
    mock_sleep.assert_called()
    landmarker.close.assert_called_once()


@patch("client.activate_alarm")
@patch("client.decode_frame", return_value="frame")
@patch("client.is_alarm_active", return_value=False)
@patch(
    "client.process_frame", return_value=({"state": "looking_away", "flag": True}, 10.0)
)
@patch("client.is_monitoring_enabled", side_effect=[True, False])
@patch("client.create_landmarker")
def test_run_monitoring_activates_alarm_for_first_flag(
    mock_create_landmarker,
    _mock_enabled,
    _mock_process_frame,
    _mock_alarm_active,
    _mock_decode,
    mock_activate_alarm,
):
    """run_monitoring records a flagged event and raises one persistent alarm."""
    landmarker = Mock()
    mock_create_landmarker.return_value = landmarker

    inserted_result = Mock(inserted_id="event-id")
    collection = Mock()
    collection.insert_one.return_value = inserted_result
    control_collection = Mock()
    frame_collection = Mock()
    frame_collection.find_one.side_effect = [
        None,
        {"_id": "frame1", "image_base64": "aGVsbG8="},
    ]

    client.run_monitoring(collection, control_collection, frame_collection)

    collection.insert_one.assert_any_call(
        {"state": "looking_away", "flag": True}
    )
    mock_activate_alarm.assert_called_once_with(
        control_collection,
        "event-id",
        {"state": "looking_away", "flag": True},
    )
    landmarker.close.assert_called_once()
