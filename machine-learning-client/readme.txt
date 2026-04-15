This directory contains the computer vision service that processes camera frames to detect user attention states.

Files:
- client.py: Main ML client application that monitors camera input and detects attention
- Dockerfile: Container definition for the ML service
- face_landmark.task: MediaPipe face landmark detection model
- requirements.txt: Python dependencies
- tests/: Unit tests for the ML client

The client uses MediaPipe for face detection and orientation analysis to determine if the user is paying attention. It communicates with MongoDB to store events and check control states.