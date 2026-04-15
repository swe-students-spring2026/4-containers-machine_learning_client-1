![Lint-free](https://github.com/swe-students-spring2026/4-containers-machine_learning_client-1/actions/workflows/lint.yml/badge.svg)
![ML Client CI](https://github.com/swe-students-spring2026/4-containers-machine_learning_client-1/actions/workflows/ml-client.yml/badge.svg)
![Web App CI](https://github.com/swe-students-spring2026/4-containers-machine_learning_client-1/actions/workflows/web-app.yml/badge.svg)
![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)

# Face Detection Focus App 

A real-time attention monitoring system that uses computer vision to detect when a user is not paying attention and provides audio & visual alerts to help maintain focus during work or study sessions.

## Features

- **Real-time Face Detection**: Uses MediaPipe's face landmark detection to monitor user attention
- **Attention Threshold Monitoring**: Configurable time thresholds for detecting inattentive periods (default is 5 seconds)
- **Audio Alerts**: Plays alarm sounds when attention flags are triggered
- **Session Statistics**: Tracks attention duration, alarm frequency, and session summaries
- **Web Interface**: Simple Flask-based UI for starting/stopping monitoring and viewing stats
- **Containerized Architecture**: Runs on Docker with MongoDB for data persistence

## Team Members 
[Kyle Chen](https://github.com/KyleC55)<br>
[Minho Eune](https://github.com/minhoeune)<br>
[name]()<br>
[name]()<br>
[name]()<br>

## Architecture

The application consists of three main components:

- **Web App**: Flask application serving the user interface and API endpoints
- **Machine Learning Client**: Python service that processes camera frames and detects attention states
- **MongoDB**: Database for storing events, control states, frames, and statistics

## Prerequisites

- Docker and Docker Compose installed on your system (the recent version of Docker Desktop bundles Docker Compose V2 automatically)
- Webcam access for face detection
- A browser to run the web app on

## Configuration

The application uses environment variables for configuration. Copy `.env.example` to `.env` and update the values:

```bash
cp .env.example .env
```

### Key configuration options:

- MONGO_URI: MongoDB connection string
- PROCESS_INTERVAL_SEC: How often to process camera frames
- FLAG_THRESHOLD_SEC: Time threshold for triggering attention flags
- ORIENTATION_THRESHOLD: Face orientation sensitivity

## Running The Software 

### Global Statistics Environment Variables

You can configure default global statistics in `.env` for the web app:

- `GLOBAL_STATS_COLLECTION` (Mongo collection for aggregate stats)
- `GLOBAL_STATS_SESSION_COUNT`
- `GLOBAL_STATS_TOTAL_DURATION_SEC`
- `GLOBAL_STATS_TOTAL_ALARM_DURATION_SEC`
- `GLOBAL_STATS_TOTAL_ATTENTION_DURATION_SEC`
- `GLOBAL_STATS_TOTAL_ATTENTION_RATIO`
- `GLOBAL_STATS_TOTAL_ALERT_COUNT`
- `GLOBAL_AVG_THRESHOLD_SEC`
- `GLOBAL_AVG_ALARM_COUNT`
- `GLOBAL_AVG_DURATION_SEC`

If no global stats document exists in MongoDB, the web app now uses these values as defaults.

### How To Run 

1. Clone The Repository 
```bash 
git clone https://github.com/swe-students-spring2026/4-containers-machine_learning_client-1.git
cd 4-containers-machine_learning_client-1
```

2. Copy and configure environment:
```bash
cp .env.example .env
# Edit .env with your settings
```

3. Build and Start Containers:
```bash 
docker compose up --build
```

4. Open the web app in your web browser:
```bash
http://localhost:8000
```

### Development
For development, you can run individual services:
```bash 
# Run only the web app
cd web-app
pip install -r requirements.txt
flask run

# Run only the ML client
cd machine-learning-client
pip install -r requirements.txt
python client.py
```

## API Endpoints
- `GET /`: Main monitoring interface
- `POST /start`: Start monitoring session
- `POST /stop`: Stop monitoring session
- `GET /status`: Get current monitoring status
- `POST /alarm/dismiss`: Dismiss active alarm
- `GET /events`: Get flagged attention events
- `GET /stats`: Get global statistics
- `POST /frames`: Ingest camera frames for processing

## Project Board

[Project Board](https://github.com/orgs/swe-students-spring2026/projects/91)

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.