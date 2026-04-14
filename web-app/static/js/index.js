const toggleButton = document.getElementById("toggle-button");
const popupStack = document.getElementById("popup-stack");
const cameraPreview = document.getElementById("camera-preview");
const captureCanvas = document.createElement("canvas");

let monitoring = document.body.dataset.monitoring === "true";
let pollTimer = null;
let frameTimer = null;
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
    if (!monitoring || !mediaStream) {
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

if (monitoring) {
    requestCameraAccess().catch(() => null);
    startPolling();
    startFrameUploads();
} else {
    stopPolling();
    stopFrameUploads();
    releaseCameraAccess();
}

function stopFrameUploads() {
    if (!frameTimer) {
        return;
    }
    window.clearInterval(frameTimer);
    frameTimer = null;
}
