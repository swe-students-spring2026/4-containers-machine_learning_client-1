"""
Minimal Flask frontend for controlling the attention monitoring client.
"""

import base64
import binascii
import os
import time
from datetime import datetime, timezone

from bson import ObjectId
from flask import Flask, jsonify, redirect, render_template, request, url_for
from pymongo import MongoClient

app = Flask(__name__)
client = MongoClient(os.environ["MONGO_URI"])
db = client[os.getenv("MONGO_DB", "mydatabase")]
event_collection = db[os.getenv("MONGO_COLLECTION", "attention_events")]
control_collection = db[os.getenv("CONTROL_COLLECTION", "attention_control")]
frame_collection = db[os.getenv("FRAME_COLLECTION", "attention_frames")]
global_stats_collection = db[os.getenv("GLOBAL_STATS_COLLECTION", "global_stats")]


def get_env_float(name, default):
    """Read a float from the environment with a safe default."""

    raw_value = os.getenv(name)
    if raw_value is None:
        return float(default)
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return float(default)


def get_env_int(name, default):
    """Read an int from the environment with a safe default."""

    raw_value = os.getenv(name)
    if raw_value is None:
        return int(default)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return int(default)


def build_global_stats_defaults():
    """Return default global stats seeded from environment values."""

    return {
        "_id": "global",
        "session_count": max(0, get_env_int("GLOBAL_STATS_SESSION_COUNT", 0)),
        "total_duration_sec": max(
            0.0, get_env_float("GLOBAL_STATS_TOTAL_DURATION_SEC", 0.0)
        ),
        "total_alarm_duration_sec": max(
            0.0, get_env_float("GLOBAL_STATS_TOTAL_ALARM_DURATION_SEC", 0.0)
        ),
        "total_attention_duration_sec": max(
            0.0, get_env_float("GLOBAL_STATS_TOTAL_ATTENTION_DURATION_SEC", 0.0)
        ),
        "total_attention_ratio": max(
            0.0, get_env_float("GLOBAL_STATS_TOTAL_ATTENTION_RATIO", 0.0)
        ),
        "total_alert_count": max(0, get_env_int("GLOBAL_STATS_TOTAL_ALERT_COUNT", 0)),
    }


def build_stats_response(stats):
    """Return a unified stats payload for API consumers."""

    default_last_session = {
        "flag_threshold_sec": get_env_float(
            "FLAG_THRESHOLD_SEC",
            0.0,
        ),
        "focused_duration_sec": 0.0,
        "alarm_count": 0,
        "duration_sec": 0.0,
    }

    if not stats:
        return {
            "session_count": 0,
            "sessions_count": 0,
            "avg_attention_duration_sec": 0.0,
            "avg_attention_ratio": 0.0,
            "avg_alert_count": 0.0,
            "avg_threshold": get_env_float(
                "GLOBAL_AVG_THRESHOLD_SEC",
                get_env_float("FLAG_THRESHOLD_SEC", 0.0),
            ),
            "avg_alarm_count": get_env_float("GLOBAL_AVG_ALARM_COUNT", 0.0),
            "avg_duration_sec": get_env_float("GLOBAL_AVG_DURATION_SEC", 0.0),
            "last_session": default_last_session,
        }

    session_count = int(stats.get("session_count", 0) or 0)
    avg_attention_duration_sec = float(
        stats.get("avg_attention_duration_sec", 0.0) or 0.0
    )
    avg_attention_ratio = float(stats.get("avg_attention_ratio", 0.0) or 0.0)
    avg_alert_count = float(stats.get("avg_alert_count", 0.0) or 0.0)
    last_session = stats.get("last_session") or default_last_session

    avg_duration_sec = (
        float(stats.get("total_duration_sec", 0.0) or 0.0) / session_count
        if session_count > 0
        else 0.0
    )

    return {
        "session_count": session_count,
        "sessions_count": session_count,
        "avg_attention_duration_sec": avg_attention_duration_sec,
        "avg_attention_ratio": avg_attention_ratio,
        "avg_alert_count": avg_alert_count,
        "avg_threshold": get_env_float(
            "GLOBAL_AVG_THRESHOLD_SEC",
            get_env_float("FLAG_THRESHOLD_SEC", 0.0),
        ),
        "avg_alarm_count": avg_alert_count,
        "avg_duration_sec": avg_duration_sec,
        "last_session": {
            "flag_threshold_sec": float(
                last_session.get(
                    "flag_threshold_sec",
                    default_last_session["flag_threshold_sec"],
                )
            ),
            "focused_duration_sec": float(
                last_session.get(
                    "focused_duration_sec",
                    default_last_session["focused_duration_sec"],
                )
            ),
            "alarm_count": int(last_session.get("alarm_count", 0) or 0),
            "duration_sec": float(last_session.get("duration_sec", 0.0) or 0.0),
        },
    }


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
    session_start_at = control.get("session_start_at")
    monitoring_since = session_start_at.timestamp() if session_start_at else ""
    return render_template(
        "index.html",
        monitoring=monitoring,
        monitoring_since=monitoring_since,
        alarm=build_alarm_payload(control),
    )


def set_monitoring_status(status):
    """Persist the current monitoring status."""

    updated_at = datetime.now(timezone.utc)
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


def to_seconds(ts):
    """Convert timestamp to float seconds"""
    return ts.timestamp() if hasattr(ts, "timestamp") else float(ts)


def compute_session_attention(events):
    """Compute session stats from labeled events from start-time to end-time"""
    if not events:
        return None

    events = sorted(events, key=lambda e: to_seconds(e["timestamp"]))

    start_time = None
    end_time = None
    current_alarm_start = None
    total_alarm_duration = 0.0
    alert_count = 0

    for event in events:
        label = event.get("label")
        ts = to_seconds(event["timestamp"])

        if label == "start" and start_time is None:
            start_time = ts
        elif label == "alarm-start" and current_alarm_start is None:
            current_alarm_start = ts
            alert_count += 1
        elif label == "alarm-end" and current_alarm_start is not None:
            total_alarm_duration += ts - current_alarm_start
            current_alarm_start = None
        elif label == "end":
            end_time = ts

    if start_time is None or end_time is None:
        return None

    if current_alarm_start is not None:
        total_alarm_duration += end_time - current_alarm_start

    total_duration = max(0.0, end_time - start_time)
    total_alarm_duration = max(0.0, min(total_alarm_duration, total_duration))
    attention_duration = total_duration - total_alarm_duration
    attention_ratio = attention_duration / total_duration if total_duration > 0 else 0.0

    return {
        "duration_sec": total_duration,
        "alarm_duration_sec": total_alarm_duration,
        "attention_duration_sec": attention_duration,
        "attention_ratio": attention_ratio,
        "alert_count": alert_count,
    }


def build_fallback_session_stats(session_start_at):
    """Build minimal session stats when labeled events are not yet available."""

    start_ts = to_seconds(session_start_at)
    end_ts = to_seconds(datetime.now(timezone.utc))
    duration_sec = max(0.0, end_ts - start_ts)
    return {
        "duration_sec": duration_sec,
        "alarm_duration_sec": 0.0,
        "attention_duration_sec": duration_sec,
        "attention_ratio": 1.0 if duration_sec > 0 else 0.0,
        "alert_count": 0,
    }


def update_global_stats(session_stats):
    """Update the global aggregate stats document."""
    global_stats = (
        global_stats_collection.find_one({"_id": "global"})
        or build_global_stats_defaults()
    )

    global_stats["session_count"] += 1
    global_stats["total_duration_sec"] += session_stats["duration_sec"]
    global_stats["total_alarm_duration_sec"] += session_stats["alarm_duration_sec"]
    global_stats["total_attention_duration_sec"] += session_stats[
        "attention_duration_sec"
    ]
    global_stats["total_attention_ratio"] += session_stats["attention_ratio"]
    global_stats["total_alert_count"] += session_stats["alert_count"]

    count = global_stats["session_count"]
    global_stats["avg_attention_duration_sec"] = (
        global_stats["total_attention_duration_sec"] / count
    )
    global_stats["avg_attention_ratio"] = global_stats["total_attention_ratio"] / count
    global_stats["avg_alert_count"] = global_stats["total_alert_count"] / count
    global_stats["last_session"] = {
        "flag_threshold_sec": get_env_float("FLAG_THRESHOLD_SEC", 0.0),
        "focused_duration_sec": float(
            session_stats.get("attention_duration_sec", 0.0) or 0.0
        ),
        "alarm_count": int(session_stats.get("alert_count", 0) or 0),
        "duration_sec": float(session_stats.get("duration_sec", 0.0) or 0.0),
    }

    global_stats_collection.replace_one(
        {"_id": "global"},
        global_stats,
        upsert=True,
    )
    return global_stats


@app.post("/start")
def start_monitoring():
    """Set the monitoring status to running and return to the home page."""

    set_monitoring_status("running")
    return redirect(url_for("home"))


@app.post("/stop")
def stop_monitoring():
    """Set the monitoring status to stopped and return to the home page."""

    control = get_monitoring_control()
    session_start_at = control.get("session_start_at")

    set_monitoring_status("stopped")

    if session_start_at is not None:
        events = []
        for _ in range(30):
            events = list(
                event_collection.find(
                    {
                        "session_id": {"$exists": True},
                        "label": {"$exists": True},
                        "timestamp": {"$gte": session_start_at},
                    }
                )
            )
            labels = {event.get("label") for event in events}
            if "start" in labels and "end" in labels:
                break
            time.sleep(0.2)

        session_stats = compute_session_attention(events)
        if session_stats is None:
            session_stats = build_fallback_session_stats(session_start_at)
        if session_stats is not None:
            update_global_stats(session_stats)

    return redirect(url_for("home") + "?stopped=1")


@app.get("/status")
def get_status():
    """Return the current monitoring status."""

    control = get_monitoring_control()
    session_start_at = control.get("session_start_at")
    return jsonify(
        {
            "monitoring": control.get("status") == "running",
            "started_at": session_start_at.timestamp() if session_start_at else None,
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
    """Return global stats."""
    stats = global_stats_collection.find_one({"_id": "global"})
    return jsonify(build_stats_response(stats))


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
