"""
Flask app that connects MongoDB to the web app
"""

from flask import Flask, render_template
from pymongo import MongoClient

app = Flask(__name__)
client = MongoClient("mongodb://admin:secret@mongo:27017/?authSource=admin")
db = client["mydatabase"]
collection = db["records"]


@app.route("/")
def home():
    """
    Fetches records from the DB and renders them to the web app
    """
    records = list(collection.find())
    print(records)
    return render_template("index.html", records=records)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
