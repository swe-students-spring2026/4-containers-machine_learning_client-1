This directory contains the Flask web application that provides the user interface and API for the attention monitoring system.

Files:

- app.py: Main Flask application with routes for monitoring control and statistics
- Dockerfile: Container definition for the web service
- requirements.txt: Python dependencies
- static/: CSS, JS, and audio files for the frontend
- templates/: Jinja2 HTML templates
- tests/: Unit tests for the web application

The web app serves a simple interface for starting/stopping monitoring sessions, displays real-time camera feed, and shows session statistics. It uses polling for real-time updates and communicates with MongoDB for data persistence.