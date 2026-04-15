"""
Minimal Flask frontend for controlling the attention monitoring client.
"""

import base64
import binascii
import os
import time
import statistics

from bson import ObjectId
from flask import Flask, jsonify, redirect, render_template, request, url_for
from pymongo import MongoClient

app = Flask(__name__)
client = MongoClient(os.environ["MONGO_URI"])
db = client[os.getenv("MONGO_DB", "mydatabase")]
event_collection = db[os.getenv("MONGO_COLLECTION", "attention_events")]
control_collection = db[os.getenv("CONTROL_COLLECTION", "attention_control")]
frame_collection = db[os.getenv("FRAME_COLLECTION", "attention_frames")]
session_collection = db[os.getenv("SESSION_COLLECTION", "attention_sessions")]
FLAG_THRESHOLD_SEC = float(os.getenv("FLAG_THRESHOLD_SEC", "5"))
ORIENTATION_THRESHOLD = float(os.getenv("ORIENTATION_THRESHOLD", "0.15"))


def is_monitoring_enabled():
    """Return whether monitoring is currently enabled."""

    control = control_collection.find_one({"_id": "monitoring"})
    return control is not None and control.get("status") == "running"


def get_monitoring_control():
    """Return the current monitoring control document."""

    return control_collection.find_one({"_id": "monitoring"}) or {}


def build_alarm_payload(control):
    """Return the serialized alarm state for API responses."""

    return {
        "active": bool(control.get("alarm_active")),
        "event": (
            {
                "id": str(control["alarm_event_id"]),
                "timestamp": control.get("alarm_triggered_at"),
                "state": control.get("alarm_state", "unknown"),
            }
            if control.get("alarm_active") and control.get("alarm_event_id") is not None
            else None
        ),
    }


@app.route("/")
def home():
    """Render the minimal control interface."""

    control = get_monitoring_control()
    monitoring = control.get("status") == "running"
    monitoring_since = control.get("updated_at", "")
    return render_template(
        "index.html",
        monitoring=monitoring,
        monitoring_since=monitoring_since,
        alarm=build_alarm_payload(control),
    )


def set_monitoring_status(status):
    """Persist the current monitoring status."""

    updated_at = time.time()
    fields = {
        "status": status,
        "updated_at": updated_at,
        "alarm_active": False,
        "alarm_event_id": None,
        "alarm_state": None,
        "alarm_triggered_at": None,
    }
    
    if status == "running":
        fields["session_start_at"] = updated_at
    
    control_collection.update_one(
        {"_id": "monitoring"},
        {"$set": fields},
        upsert=True,
    )
    return updated_at

def save_session_summary():
    control = get_monitoring_control()
    start_time = control.get("session_start_at")
    if start_time is None:
        return
    end_time = time.time()
    alarm_count = event_collection.count_documents(
        {"flag": True, "timestamp": {"$gte": start_time}}
    )
    session_collection.insert_one({
        "start_time": start_time,
        "end_time": end_time,
        "duration_sec": end_time - start_time,
        "alarm_count": alarm_count,
        "flag_threshold_sec": FLAG_THRESHOLD_SEC,
        "orientation_threshold": ORIENTATION_THRESHOLD,
    })

@app.post("/start")
def start_monitoring():
    """Set the monitoring status to running and return to the home page."""

    set_monitoring_status("running")
    return redirect(url_for("home"))


@app.post("/stop")
def stop_monitoring():
    """Set the monitoring status to stopped and return to the home page."""

    save_session_summary()
    set_monitoring_status("stopped")
    return redirect(url_for("home") + "?stopped=1")


@app.get("/status")
def get_status():
    """Return the current monitoring status."""

    control = get_monitoring_control()
    return jsonify(
        {
            "monitoring": control.get("status") == "running",
            "updated_at": control.get("updated_at"),
            "alarm": build_alarm_payload(control),
        }
    )


@app.post("/alarm/dismiss")
def dismiss_alarm():
    """Clear the active alarm and allow monitoring to resume."""

    updated_at = time.time()
    control_collection.update_one(
        {"_id": "monitoring"},
        {
            "$set": {
                "alarm_active": False,
                "alarm_event_id": None,
                "alarm_state": None,
                "alarm_triggered_at": None,
                "updated_at": updated_at,
            }
        },
        upsert=True,
    )
    control = get_monitoring_control()
    return jsonify(
        {
            "ok": True,
            "monitoring": control.get("status") == "running",
            "updated_at": control.get("updated_at"),
            "alarm": build_alarm_payload(control),
        }
    )


@app.get("/events")
def flagged_events():
    """Return flagged events after the provided timestamp or object id."""

    after_timestamp = request.args.get("after_timestamp", type=float)
    after_id = request.args.get("after_id", default="", type=str)

    query = {"flag": True}
    if after_timestamp is not None:
        query["timestamp"] = {"$gte": after_timestamp}
    if after_id:
        try:
            query["_id"] = {"$gt": ObjectId(after_id)}
        except Exception:  # pylint: disable=broad-exception-caught
            return jsonify({"error": "invalid after_id"}), 400

    records = event_collection.find(query).sort([("_id", 1)])
    events = [
        {
            "id": str(record["_id"]),
            "timestamp": record.get("timestamp"),
            "state": record.get("state", "unknown"),
            "flag": bool(record.get("flag")),
        }
        for record in records
    ]
    return jsonify({"events": events})


@app.get("/stats")
def get_stats():
    sessions = list(session_collection.find())
    if not sessions:
        return jsonify({"sessions_count": 0})
    
    last_session = session_collection.find_one(sort=[("_id", -1)])
    
    return jsonify({
        "sessions_count": len(sessions),
        "avg_threshold": average_without_outliers([s["flag_threshold_sec"] for s in sessions]),
        "avg_alarm_count": average_without_outliers([s["alarm_count"] for s in sessions]),
        "avg_duration_sec": average_without_outliers([s["duration_sec"] for s in sessions]),
        "last_session": {
            "flag_threshold_sec": last_session["flag_threshold_sec"],
            "alarm_count": last_session["alarm_count"],
            "duration_sec": last_session["duration_sec"],
        }
    })


@app.post("/frames")
def ingest_frame():
    """Store one frontend-captured camera frame for backend processing."""

    payload = request.get_json(silent=True) or {}
    image_base64 = payload.get("image_base64", "")
    if not isinstance(image_base64, str) or not image_base64:
        return jsonify({"error": "missing image_base64"}), 400

    try:
        base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError):
        return jsonify({"error": "invalid image_base64"}), 400

    frame_collection.insert_one(
        {"timestamp": time.time(), "image_base64": image_base64}
    )
    return jsonify({"ok": True}), 201


def average_without_outliers(values):
    """Helper function to filter outliers and compute the average"""
    if len(values) < 2:
        return values[0] if values else None
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    filtered = [v for v in values if abs(v - mean) <= stdev]
    return statistics.mean(filtered) if filtered else mean


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
