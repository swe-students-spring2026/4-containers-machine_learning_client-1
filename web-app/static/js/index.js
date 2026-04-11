const toggleButton = document.getElementById("toggle-button");
const popupStack = document.getElementById("popup-stack");
const cameraPreview = document.getElementById("camera-preview");

let monitoring = document.body.dataset.monitoring === "true";
let pollTimer = null;
let sessionStartTimestamp = document.body.dataset.monitoringSince || null;
let lastSeenId = "";
let mediaStream = null;

function createPopup(event) {
    const popup = document.createElement("article");
    popup.className = "popup";

    const heading = document.createElement("h2");
    heading.textContent = "Attention Flag";

    const message = document.createElement("p");
    const timestamp = event.timestamp
        ? new Date(event.timestamp * 1000).toLocaleString()
        : "Unknown time";
    message.textContent = `State: ${event.state}. Time: ${timestamp}.`;

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.textContent = "Close";
    closeButton.addEventListener("click", () => popup.remove());

    popup.append(heading, message, closeButton);
    popupStack.prepend(popup);
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
    if (!monitoring) {
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
    for (const event of payload.events) {
        lastSeenId = event.id;
        createPopup(event);
    }
}

function startPolling() {
    if (pollTimer) {
        window.clearInterval(pollTimer);
    }
    pollTimer = window.setInterval(() => {
        fetchFlaggedEvents().catch(() => null);
    }, 2000);
}

function stopPolling() {
    if (!pollTimer) {
        return;
    }
    window.clearInterval(pollTimer);
    pollTimer = null;
}

if (monitoring) {
    requestCameraAccess().catch(() => null);
    startPolling();
} else {
    stopPolling();
    releaseCameraAccess();
}
