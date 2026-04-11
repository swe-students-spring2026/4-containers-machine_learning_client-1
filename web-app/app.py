"""
Minimal Flask frontend for controlling the attention monitoring client.
"""

import os
import time

from bson import ObjectId
from flask import Flask, jsonify, redirect, render_template, request, url_for
from pymongo import MongoClient

app = Flask(__name__)
client = MongoClient(os.environ["MONGO_URI"])
db = client[os.getenv("MONGO_DB", "mydatabase")]
event_collection = db[os.getenv("MONGO_COLLECTION", "attention_events")]
control_collection = db[os.getenv("CONTROL_COLLECTION", "attention_control")]


def is_monitoring_enabled():
    """Return whether monitoring is currently enabled."""

    control = control_collection.find_one({"_id": "monitoring"})
    return control is not None and control.get("status") == "running"


def get_monitoring_control():
    """Return the current monitoring control document."""

    return control_collection.find_one({"_id": "monitoring"}) or {}


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
    )


def set_monitoring_status(status):
    """Persist the current monitoring status."""

    updated_at = time.time()
    control_collection.update_one(
        {"_id": "monitoring"},
        {"$set": {"status": status, "updated_at": updated_at}},
        upsert=True,
    )
    return updated_at


@app.post("/start")
def start_monitoring():
    """Set the monitoring status to running and return to the home page."""

    set_monitoring_status("running")
    return redirect(url_for("home"))


@app.post("/stop")
def stop_monitoring():
    """Set the monitoring status to stopped and return to the home page."""

    set_monitoring_status("stopped")
    return redirect(url_for("home"))


@app.get("/status")
def get_status():
    """Return the current monitoring status."""

    control = get_monitoring_control()
    return jsonify(
        {
            "monitoring": control.get("status") == "running",
            "updated_at": control.get("updated_at"),
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
