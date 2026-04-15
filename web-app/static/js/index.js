const popupModal = document.getElementById("alarm-modal");
const alarmMessage = document.getElementById("alarm-message");
const dismissAlarmButton = document.getElementById("dismiss-alarm-button");
const cameraPreview = document.getElementById("camera-preview");
const alarmAudio = document.getElementById("alarm-audio");
const captureCanvas = document.createElement("canvas");

let monitoring = document.body.dataset.monitoring === "true";
let pollTimer = null;
let alarmActive = document.body.dataset.alarmActive === "true";
let sessionStartTimestamp = document.body.dataset.monitoringSince || null;
let lastSeenId = "";
const initialAlarmState = document.body.dataset.alarmState || "unknown";
const initialAlarmTimestamp = Number(document.body.dataset.alarmTimestamp || 0);
let frameTimer = null;
let mediaStream = null;

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

async function syncStatus() {
    const response = await fetch("/status");
    if (!response.ok) {
        return;
    }

    const payload = await response.json();
    monitoring = Boolean(payload.monitoring);
    sessionStartTimestamp = payload.updated_at || sessionStartTimestamp;
    updateAlarmUi(payload.alarm);

    if (!monitoring) {
        stopPolling();
        stopFrameUploads();
        releaseCameraAccess();
        return;
    }

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
}
