"""
Run the MediaPipe attention monitoring client.
"""

import os
import sys
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from pymongo import MongoClient
from pymongo.errors import PyMongoError

MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB = os.getenv("MONGO_DB", "mydatabase")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "attention_events")
CONTROL_COLLECTION = os.getenv("CONTROL_COLLECTION", "attention_control")
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
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


def is_monitoring_enabled(control_collection):
    """
    Return whether the dashboard has enabled attention monitoring.
    """

    control = control_collection.find_one({"_id": "monitoring"})
    return control is not None and control.get("status") == "running"


def create_landmarker():
    """
    Create the MediaPipe Face Landmarker from the configured model file.
    """

    if not os.path.exists(MODEL_PATH):
        print(f"Missing Face Landmarker model: {MODEL_PATH}", file=sys.stderr)
        return None
    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
    )
    return vision.FaceLandmarker.create_from_options(options)


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
    timestamp_ms = int(time.monotonic() * 1000)
    detection_result = landmarker.detect_for_video(mp_image, timestamp_ms)

    state = classify_attention(detection_result)
    now = time.monotonic()
    if state == "attentive":
        last_attentive_at = now
    flag = state != "attentive" and now - last_attentive_at > FLAG_THRESHOLD_SEC
    return {"timestamp": time.time(), "state": state, "flag": flag}, last_attentive_at


def run_monitoring(collection, control_collection):
    """Capture frames, classify attention, and write events while enabled."""
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"Unable to open camera index {CAMERA_INDEX}", file=sys.stderr)
        return

    landmarker = create_landmarker()
    if landmarker is None:
        cap.release()
        return

    last_attentive_at = time.monotonic()

    try:
        while is_monitoring_enabled(control_collection):
            loop_started_at = time.monotonic()
            ok, frame = cap.read()
            if not ok:
                print("Camera frame read failed", file=sys.stderr)
                break

            event, last_attentive_at = process_frame(
                frame, landmarker, last_attentive_at
            )
            try:
                collection.insert_one(event)
            except PyMongoError as exc:
                print(f"MongoDB insert failed: {exc}", file=sys.stderr)
            print(event)

            elapsed = time.monotonic() - loop_started_at
            time.sleep(max(0, PROCESS_INTERVAL_SEC - elapsed))
    except KeyboardInterrupt:
        print("Stopping client")
    finally:
        landmarker.close()
        cap.release()


def main():
    """
    Wait for the start signal, then run attention monitoring.
    """
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[MONGO_DB]
    event_collection = db[MONGO_COLLECTION]
    control_collection = db[CONTROL_COLLECTION]

    try:
        while True:
            if is_monitoring_enabled(control_collection):
                print("Attention monitoring started")
                run_monitoring(event_collection, control_collection)
                print("Attention monitoring stopped")
            time.sleep(PROCESS_INTERVAL_SEC)
    except KeyboardInterrupt:
        print("Stopping client")
    finally:
        mongo_client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
