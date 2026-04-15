"""
Run the MediaPipe attention monitoring client.
"""

import base64
import os
import sys
import time
import uuid
from datetime import datetime, timezone

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from pymongo import MongoClient
from pymongo.errors import PyMongoError

MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB = os.getenv("MONGO_DB", "mydatabase")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "attention_events")
CONTROL_COLLECTION = os.getenv("CONTROL_COLLECTION", "attention_control")
FRAME_COLLECTION = os.getenv("FRAME_COLLECTION", "attention_frames")
PROCESS_INTERVAL_SEC = float(os.getenv("PROCESS_INTERVAL_SEC", "1"))
FLAG_THRESHOLD_SEC = float(os.getenv("FLAG_THRESHOLD_SEC", "5"))
ORIENTATION_THRESHOLD = float(os.getenv("ORIENTATION_THRESHOLD", "0.15"))
MODEL_PATH = os.getenv(
    "FACE_LANDMARKER_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "face_landmarker.task"),
)

NOSE_TIP_INDEX = 1
LEFT_CHEEK_INDEX = 234
RIGHT_CHEEK_INDEX = 454

current_session_id = None  # pylint: disable=invalid-name
alarm_active = False  # pylint: disable=invalid-name


def is_monitoring_enabled(control_collection):
    """
    Return whether the dashboard has enabled attention monitoring.
    """

    control = control_collection.find_one({"_id": "monitoring"})
    return control is not None and control.get("status") == "running"


def is_alarm_active(control_collection):
    """Return whether an alarm is currently active."""

    control = control_collection.find_one({"_id": "monitoring"})
    return control is not None and control.get("alarm_active") is True


def activate_alarm(control_collection, event_id, event):
    """Persist the current alarm so monitoring pauses until dismissal."""

    control_collection.update_one(
        {"_id": "monitoring"},
        {
            "$set": {
                "alarm_active": True,
                "alarm_event_id": event_id,
                "alarm_state": event.get("state"),
                "alarm_triggered_at": event.get("timestamp"),
            }
        },
        upsert=True,
    )


def create_landmarker():
    """
    Create the MediaPipe Face Landmarker from the configured model file.
    """

    if not os.path.exists(MODEL_PATH):
        print(f"Missing Face Landmarker model: {MODEL_PATH}", file=sys.stderr)
        return None
    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=vision.RunningMode.IMAGE,
        num_faces=1,
    )
    try:
        return vision.FaceLandmarker.create_from_options(options)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Failed to create Face Landmarker: {exc}", file=sys.stderr)
        return None


def classify_attention(detection_result):
    """
    Classify a detection result as attentive, looking away, or absent.
    """

    if not detection_result.face_landmarks:
        return "absent"
    landmarks = detection_result.face_landmarks[0]
    nose_x = landmarks[NOSE_TIP_INDEX].x
    left_cheek_x = landmarks[LEFT_CHEEK_INDEX].x
    right_cheek_x = landmarks[RIGHT_CHEEK_INDEX].x
    face_center_x = (left_cheek_x + right_cheek_x) / 2
    cheek_span = abs(right_cheek_x - left_cheek_x)
    if cheek_span <= 0:
        return "attentive"
    deviation = abs(nose_x - face_center_x) / cheek_span
    if deviation > ORIENTATION_THRESHOLD:
        return "looking_away"
    return "attentive"


def process_frame(frame, landmarker, last_attentive_at):
    """Classify one camera frame and return an event plus timer state."""
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
    detection_result = landmarker.detect(mp_image)

    state = classify_attention(detection_result)
    now = time.monotonic()
    if state == "attentive":
        last_attentive_at = now
    flag = state != "attentive" and now - last_attentive_at > FLAG_THRESHOLD_SEC
    return {"timestamp": time.time(), "state": state, "flag": flag}, last_attentive_at


def decode_frame(frame_document):
    """Decode a base64 JPEG frame from MongoDB into an OpenCV image."""
    image_base64 = frame_document.get("image_base64", "")
    if not image_base64:
        return None

    try:
        image_bytes = base64.b64decode(image_base64)
    except (ValueError, TypeError):
        return None

    np_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)


def save_event(collection, label):
    """Save a session event to MongoDB"""
    global current_session_id

    if current_session_id is None:
        return

    event_document = {
        "session_id": current_session_id,
        "timestamp": datetime.now(timezone.utc),
        "label": label,
    }

    try:
        collection.insert_one(event_document)
    except PyMongoError as exc:
        print(f"MongoDB insert failed: {exc}", file=sys.stderr)
        print(event_document)


def run_monitoring(collection, control_collection, frame_collection):
    """Process frontend-uploaded frames and write events while enabled."""
    global current_session_id, alarm_active

    landmarker = create_landmarker()
    if landmarker is None:
        return

    current_session_id = str(uuid.uuid4())
    alarm_active = False
    save_event(collection, "start")

    last_attentive_at = time.monotonic()
    last_frame_id = None
    alarm_paused = False

    try:
        while is_monitoring_enabled(control_collection):
            loop_started_at = time.monotonic()
            if is_alarm_active(control_collection):
                alarm_paused = True
                elapsed = time.monotonic() - loop_started_at
                time.sleep(max(0, PROCESS_INTERVAL_SEC - elapsed))
                continue
            if alarm_paused:
                if alarm_active:
                    save_event(collection, "alarm-end")
                    alarm_active = False
                last_attentive_at = time.monotonic()
                alarm_paused = False
            if last_frame_id is None:
                latest_existing_frame = frame_collection.find_one(sort=[("_id", -1)])
                if latest_existing_frame is not None:
                    last_frame_id = latest_existing_frame.get("_id")

            frame_query = {}
            if last_frame_id is not None:
                frame_query["_id"] = {"$gt": last_frame_id}

            frame_document = frame_collection.find_one(frame_query, sort=[("_id", 1)])
            if frame_document is None:
                elapsed = time.monotonic() - loop_started_at
                time.sleep(max(0, PROCESS_INTERVAL_SEC - elapsed))
                continue

            frame = decode_frame(frame_document)
            last_frame_id = frame_document.get("_id", last_frame_id)
            if frame is None:
                elapsed = time.monotonic() - loop_started_at
                time.sleep(max(0, PROCESS_INTERVAL_SEC - elapsed))
                continue

            event, last_attentive_at = process_frame(
                frame, landmarker, last_attentive_at
            )
            try:
                inserted_event = collection.insert_one(event)
                if event.get("flag") and not alarm_active:
                    save_event(collection, "alarm-start")
                    activate_alarm(
                        control_collection, inserted_event.inserted_id, event
                    )
                    alarm_active = True
                if not event.get("flag") and alarm_active:
                    save_event(collection, "alarm-end")
                    alarm_active = False

            except PyMongoError as exc:
                print(f"MongoDB insert failed: {exc}", file=sys.stderr)
                print(event)

            elapsed = time.monotonic() - loop_started_at
            time.sleep(max(0, PROCESS_INTERVAL_SEC - elapsed))

    except KeyboardInterrupt:
        print("Stopping client")
    finally:
        if alarm_active:
            save_event(collection, "alarm-end")
            alarm_active = False

        save_event(collection, "end")
        current_session_id = None
        landmarker.close()


def main():
    """
    Wait for the start signal, then run attention monitoring.
    """
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[MONGO_DB]
    event_collection = db[MONGO_COLLECTION]
    control_collection = db[CONTROL_COLLECTION]
    frame_collection = db[FRAME_COLLECTION]

    try:
        while True:
            if is_monitoring_enabled(control_collection):
                print("Attention monitoring started")
                run_monitoring(event_collection, control_collection, frame_collection)
                print("Attention monitoring stopped")
            time.sleep(PROCESS_INTERVAL_SEC)
    except KeyboardInterrupt:
        print("Stopping client")
    finally:
        mongo_client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
