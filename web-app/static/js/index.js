const popupModal = document.getElementById("alarm-modal");
const alarmMessage = document.getElementById("alarm-message");
const statsPanel = document.getElementById("stats-panel");
const dismissStatsButton = document.getElementById("dismiss-stats-button");
const dismissAlarmButton = document.getElementById("dismiss-alarm-button");
const liveTimeStarted = document.getElementById("live-time-started");
const liveCurrentTime = document.getElementById("live-current-time");
const liveTimeActive = document.getElementById("live-time-active");
const liveAlarmCount = document.getElementById("live-alarm-count");
const cameraPreview = document.getElementById("camera-preview");
const alarmAudio = document.getElementById("alarm-audio");
const captureCanvas = document.createElement("canvas");
const justStopped = document.body.dataset.justStopped === "true";

let monitoring = document.body.dataset.monitoring === "true";
let pollTimer = null;
let alarmActive = document.body.dataset.alarmActive === "true";
let sessionStartTimestamp = document.body.dataset.monitoringSince || null;
let lastSeenId = "";
const initialAlarmState = document.body.dataset.alarmState || "unknown";
const initialAlarmTimestamp = Number(document.body.dataset.alarmTimestamp || 0);
let frameTimer = null;
let mediaStream = null;
let liveClockTimer = null;
let monitoringStartedAt = null;
let alarmOccurrences = 0;
let activeElapsedSeconds = 0;
let lastLiveTickMs = null;
const seenAlarmEventIds = new Set();

function parseTimestamp(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }

    if (typeof value === "number") {
        return new Date(value < 1_000_000_000_000 ? value * 1000 : value);
    }

    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
        return new Date(numeric < 1_000_000_000_000 ? numeric * 1000 : numeric);
    }

    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) {
        return new Date(parsed);
    }

    if (typeof value === "string") {
        const normalized = value.trim().replace(" ", "T");
        const normalizedParsed = Date.parse(normalized);
        if (!Number.isNaN(normalizedParsed)) {
            return new Date(normalizedParsed);
        }
    }

    return null;
}

function formatClock(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
        return "--";
    }
    return date.toLocaleTimeString();
}

function formatDuration(seconds) {
    const totalSeconds = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const remainderSeconds = totalSeconds % 60;
    return [hours, minutes, remainderSeconds]
        .map((value) => String(value).padStart(2, "0"))
        .join(":");
}

function updateLiveStatsUi() {
    const now = new Date();
    const nowMs = now.getTime();
    liveCurrentTime.textContent = formatClock(now);

    if (monitoring) {
        if (!monitoringStartedAt) {
            monitoringStartedAt = now;
        }

        if (lastLiveTickMs === null) {
            lastLiveTickMs = nowMs;
        } else {
            activeElapsedSeconds += Math.max(0, (nowMs - lastLiveTickMs) / 1000);
            lastLiveTickMs = nowMs;
        }

        liveTimeStarted.textContent = formatClock(monitoringStartedAt);
        liveTimeActive.textContent = formatDuration(activeElapsedSeconds);
    } else {
        lastLiveTickMs = null;
        liveTimeStarted.textContent = "--";
        liveTimeActive.textContent = "--";
    }

    liveAlarmCount.textContent = String(alarmOccurrences);
}

function initializeLiveStats() {
    monitoringStartedAt = monitoring ? parseTimestamp(sessionStartTimestamp) : null;
    if (monitoring) {
        if (!monitoringStartedAt) {
            monitoringStartedAt = new Date();
        }
        activeElapsedSeconds = Math.max(
            0,
            (Date.now() - monitoringStartedAt.getTime()) / 1000,
        );
        lastLiveTickMs = Date.now();
    } else {
        activeElapsedSeconds = 0;
        lastLiveTickMs = null;
    }
    alarmOccurrences = 0;
    seenAlarmEventIds.clear();
    updateLiveStatsUi();
    if (!liveClockTimer) {
        liveClockTimer = window.setInterval(updateLiveStatsUi, 1000);
    }
}

function hideSessionStats() {
    statsPanel.classList.remove("active");
}

function formatTimestamp(timestamp) {
    if (!timestamp) {
        return "Unknown time";
    }
    return new Date(timestamp * 1000).toLocaleString();
}

function updateAlarmUi(alarm) {
    alarmActive = Boolean(alarm && alarm.active);
    document.body.classList.toggle("alarm-active", alarmActive);
    popupModal.classList.toggle("active", alarmActive);
    dismissAlarmButton.hidden = !alarmActive;

    if (alarmActive && alarm && alarm.event) {
        alarmMessage.textContent = `State: ${alarm.event.state}. Time: ${formatTimestamp(alarm.event.timestamp)}.`;
        alarmAudio.currentTime = 0;
        alarmAudio.play().catch(() => null);
    } else {
        alarmMessage.textContent = "Attention monitoring is active.";
        alarmAudio.pause();
        alarmAudio.currentTime = 0;
    }
}

async function requestCameraAccess() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        return;
    }
    if (mediaStream) {
        return;
    }
    mediaStream = await navigator.mediaDevices.getUserMedia({ video: true });
    cameraPreview.srcObject = mediaStream;
    await cameraPreview.play();
}

function releaseCameraAccess() {
    if (!mediaStream) {
        return;
    }
    for (const track of mediaStream.getTracks()) {
        track.stop();
    }
    cameraPreview.srcObject = null;
    mediaStream = null;
}

async function fetchFlaggedEvents() {
    if (!monitoring || alarmActive) {
        return;
    }

    const params = new URLSearchParams();
    if (sessionStartTimestamp !== null) {
        params.set("after_timestamp", String(sessionStartTimestamp));
    }
    if (lastSeenId) {
        params.set("after_id", lastSeenId);
    }

    const response = await fetch(`/events?${params.toString()}`);
    if (!response.ok) {
        return;
    }

    const payload = await response.json();
}

function startPolling() {
    if (pollTimer) {
        window.clearInterval(pollTimer);
    }
    pollTimer = window.setInterval(() => {
        fetchFlaggedEvents().catch(() => null);
        syncStatus().catch(() => null);
    }, 1000);
}

function stopPolling() {
    if (!pollTimer) {
        return;
    }
    window.clearInterval(pollTimer);
    pollTimer = null;
}

function captureFrameBase64() {
    if (cameraPreview.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
        return "";
    }

    const width = cameraPreview.videoWidth;
    const height = cameraPreview.videoHeight;
    if (!width || !height) {
        return "";
    }

    captureCanvas.width = width;
    captureCanvas.height = height;
    const context = captureCanvas.getContext("2d");
    if (!context) {
        return "";
    }

    context.drawImage(cameraPreview, 0, 0, width, height);
    const dataUrl = captureCanvas.toDataURL("image/jpeg", 0.8);
    const parts = dataUrl.split(",");
    return parts.length === 2 ? parts[1] : "";
}

async function uploadFrame() {
    if (!monitoring || alarmActive || !mediaStream) {
        return;
    }

    const imageBase64 = captureFrameBase64();
    if (!imageBase64) {
        return;
    }

    await fetch("/frames", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_base64: imageBase64 }),
    });
}

function startFrameUploads() {
    if (frameTimer) {
        window.clearInterval(frameTimer);
    }
    frameTimer = window.setInterval(() => {
        uploadFrame().catch(() => null);
    }, 1000);
}

function stopFrameUploads() {
    if (!frameTimer) {
        return;
    }
    window.clearInterval(frameTimer);
    frameTimer = null;
}

async function showSessionStats(sessionStart) {
    const response = await fetch("/stats");
    if (!response.ok) return;
    const data = await response.json();
    if (data.sessions_count === 0) return;

    const last = data.last_session;

    document.getElementById("stat-your-focused").textContent =
        last.focused_duration_sec?.toFixed(0) ?? "--";
    document.getElementById("stat-avg-focused").textContent =
        data.avg_attention_duration_sec?.toFixed(0) ?? "--";
    document.getElementById("stat-your-alarms").textContent = last.alarm_count ?? "--";
    document.getElementById("stat-avg-alarms").textContent = data.avg_alarm_count?.toFixed(1) ?? "--";
    document.getElementById("stat-your-duration").textContent = last.duration_sec?.toFixed(0) ?? "--";
    document.getElementById("stat-avg-duration").textContent = data.avg_duration_sec?.toFixed(0) ?? "--";

    statsPanel.classList.add("active");
}

async function syncStatus() {
    const response = await fetch("/status");
    if (!response.ok) {
        return;
    }

    const payload = await response.json();
    const wasMonitoring = monitoring;
    const wasAlarmActive = alarmActive;
    monitoring = Boolean(payload.monitoring);

    if (monitoring && !wasMonitoring) {
        sessionStartTimestamp = payload.started_at || sessionStartTimestamp;
        monitoringStartedAt = parseTimestamp(sessionStartTimestamp) || new Date();
        activeElapsedSeconds = Math.max(
            0,
            (Date.now() - monitoringStartedAt.getTime()) / 1000,
        );
        lastLiveTickMs = Date.now();
        alarmOccurrences = 0;
        seenAlarmEventIds.clear();
    } else if (monitoring && !monitoringStartedAt) {
        monitoringStartedAt = parseTimestamp(sessionStartTimestamp) || new Date();
        activeElapsedSeconds = Math.max(
            0,
            (Date.now() - monitoringStartedAt.getTime()) / 1000,
        );
        lastLiveTickMs = Date.now();
    } else if (!monitoring) {
        monitoringStartedAt = null;
        activeElapsedSeconds = 0;
        lastLiveTickMs = null;
    }

    if (monitoring && payload.alarm?.active) {
        const alarmEventId = payload.alarm.event?.id || "";
        if (alarmEventId) {
            if (!seenAlarmEventIds.has(alarmEventId)) {
                seenAlarmEventIds.add(alarmEventId);
                alarmOccurrences += 1;
            }
        } else if (!wasAlarmActive) {
            alarmOccurrences += 1;
        }
    }

    updateAlarmUi(payload.alarm);
    updateLiveStatsUi();

    if (!monitoring) {
        const capturedStart = sessionStartTimestamp;
        stopPolling();
        stopFrameUploads();
        releaseCameraAccess();
        showSessionStats(capturedStart).catch(() => null);
        return;
    }

    hideSessionStats();
    await requestCameraAccess();
    if (alarmActive) {
        stopPolling();
        stopFrameUploads();
        return;
    }
    startPolling();
    startFrameUploads();
}

async function dismissAlarm() {
    dismissAlarmButton.disabled = true;
    try {
        const response = await fetch("/alarm/dismiss", { method: "POST" });
        if (!response.ok) {
            return;
        }
        const payload = await response.json();
        monitoring = Boolean(payload.monitoring);
        updateAlarmUi(payload.alarm);
        if (monitoring) {
            await requestCameraAccess();
            startPolling();
            startFrameUploads();
        }
    } finally {
        dismissAlarmButton.disabled = false;
    }
}

dismissAlarmButton.addEventListener("click", () => {
    dismissAlarm().catch(() => null);
});

dismissStatsButton.addEventListener("click", () => {
    hideSessionStats();
});

updateAlarmUi({
    active: alarmActive,
    event: alarmActive
        ? {
            state: initialAlarmState,
            timestamp: Number.isFinite(initialAlarmTimestamp) && initialAlarmTimestamp > 0
                ? initialAlarmTimestamp
                : null,
        }
        : null,
});

if (monitoring) {
    hideSessionStats();
    requestCameraAccess()
        .then(() => {
            if (!alarmActive) {
                startPolling();
                startFrameUploads();
            }
        })
        .catch(() => null);
} else {
    stopPolling();
    stopFrameUploads();
    releaseCameraAccess();
    if (justStopped) {
        showSessionStats(sessionStartTimestamp).catch(() => null);
    }
}

initializeLiveStats();
