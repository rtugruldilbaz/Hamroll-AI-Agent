const $ = id => document.getElementById(id);

const language =
    document.body.dataset.language === "en" ? "en" : "tr";

const userRole =
    document.body.dataset.role || "guest";

const csrfToken =
    document.body.dataset.csrfToken || "";

const UI = {
    tr: {
        defaultPlaceholder: "Mesajınızı yazın...",
        thinking: "Agent düşünüyor",
        transcribing: "Ses metne çevriliyor",
        transcriptionDone: "Ses metne çevrildi.",
        transcriptionFailed: "Ses dosyası işlenemedi.",
        microphoneMissing: "Aktif mikrofon bulunamadı.",
        microphoneDenied: "Mikrofon izni alınamadı.",
        recordingCancelled: "Ses kaydı iptal edildi.",
        recordingEmpty: "Ses kaydı alınamadı.",
        documentTooLarge: "Belge en fazla 25 MB olabilir.",
        documentEmpty: "Boş belge yüklenemez.",
        documentTypes: "Desteklenen belge türleri: PDF, DOCX, TXT, MD, CSV, JSON.",
        documentUploading: "Belge yükleniyor ve indexleniyor",
        documentFailed: "Belge yüklenirken bağlantı hatası oluştu.",
        documentReady: (name, chunks) =>
            `${name} hazır. ${chunks} parça indexlendi.`,
        permissionDenied: "Bu aracı kullanmak için gerekli yetkiye sahip değilsiniz.",
        serverUnavailable: "Sunucuya bağlanılamadı.",
        detailsCommand: "ne değişiyor?",
        tools: {
            create: [
                "Dosya · Oluştur",
                "Ne oluşturmak istiyorsunuz?"
            ],
            read: [
                "Dosya · Oku",
                "Okumak istediğiniz dosyayı belirtin..."
            ],
            write: [
                "Dosya · Yaz / Ekle",
                "Dosyayı ve yapılacak değişikliği yazın..."
            ],
            "search-files": [
                "Dosya · Ara",
                "Aramak istediğiniz dosyayı yazın..."
            ],
            list: [
                "Klasör · Listele",
                "Listelemek istediğiniz klasörü belirtin..."
            ],
            open: [
                "Dosya / Klasör · Aç",
                "Açmak istediğiniz dosya veya klasörü yazın..."
            ],
            rename: [
                "Dosya · Yeniden Adlandır",
                "Dosyayı ve yeni adını belirtin..."
            ],
            move: [
                "Dosya · Taşı",
                "Dosyayı ve hedef konumu belirtin..."
            ],
            delete: [
                "Dosya · Sil",
                "Silmek istediğiniz dosyayı belirtin..."
            ],
            "telegram-message": [
                "Telegram · Mesaj Gönder",
                "Göndermek istediğiniz mesajı yazın..."
            ],
            "telegram-file": [
                "Telegram · Dosya Gönder",
                "Göndermek istediğiniz dosyayı belirtin..."
            ],
            rag: [
                "Belgeler · Ara",
                "Belgeler hakkında sorunuzu yazın..."
            ],
            history: [
                "Konuşma · Geçmiş",
                "Görmek istediğiniz geçmişi belirtin..."
            ]
        }
    },
    en: {
        defaultPlaceholder: "Type your message...",
        thinking: "Agent is thinking",
        transcribing: "Transcribing audio",
        transcriptionDone: "Audio transcribed.",
        transcriptionFailed: "The audio file could not be processed.",
        microphoneMissing: "No active microphone was found.",
        microphoneDenied: "Microphone permission could not be obtained.",
        recordingCancelled: "Voice recording cancelled.",
        recordingEmpty: "No audio was recorded.",
        documentTooLarge: "The document can be up to 25 MB.",
        documentEmpty: "An empty document cannot be uploaded.",
        documentTypes: "Supported document types: PDF, DOCX, TXT, MD, CSV, JSON.",
        documentUploading: "Uploading and indexing document",
        documentFailed: "A connection error occurred while uploading the document.",
        documentReady: (name, chunks) =>
            `${name} is ready. ${chunks} chunks indexed.`,
        permissionDenied: "You do not have permission to use this tool.",
        serverUnavailable: "Could not connect to the server.",
        detailsCommand: "what changes?",
        tools: {
            create: [
                "File · Create",
                "Describe the file you want to create..."
            ],
            read: [
                "File · Read",
                "Specify the file you want to read..."
            ],
            write: [
                "File · Write / Append",
                "Describe the file and the change..."
            ],
            "search-files": [
                "File · Search",
                "Enter the file you want to find..."
            ],
            list: [
                "Folder · List",
                "Specify the folder you want to list..."
            ],
            open: [
                "File / Folder · Open",
                "Specify the file or folder you want to open..."
            ],
            rename: [
                "File · Rename",
                "Specify the file and its new name..."
            ],
            move: [
                "File · Move",
                "Specify the file and destination..."
            ],
            delete: [
                "File · Delete",
                "Specify the file you want to delete..."
            ],
            "telegram-message": [
                "Telegram · Send Message",
                "Enter the message you want to send..."
            ],
            "telegram-file": [
                "Telegram · Send File",
                "Specify the file you want to send..."
            ],
            rag: [
                "Documents · Search",
                "Ask a question about your documents..."
            ],
            history: [
                "Conversation · History",
                "Describe the history you want to retrieve..."
            ]
        }
    }
}[language];

const messageInput = $("messageInput");
const sendButton = $("sendButton");
const toolsButton = $("toolsButton");
const toolsMenu = $("toolsMenu");
const voiceButton = $("voiceButton");
const voiceMenu = $("voiceMenu");
const startVoiceRecording = $("startVoiceRecording");
const uploadVoiceFile = $("uploadVoiceFile");
const audioFileInput = $("audioFileInput");
const generalFileInput = $("generalFileInput");
const recordingPanel = $("recordingPanel");
const cancelRecording = $("cancelRecording");
const recordingTime = $("recordingTime");
const voiceWave = $("voiceWave");
const chat = $("chat");
const confirmationButtons = $("confirmationButtons");
const yesButton = $("yesButton");
const noButton = $("noButton");
const detailsButton = $("detailsButton");
const guestRemaining = $("guestRemaining");
const thinking = $("thinking");
const thinkingText = $("thinkingText");
const toast = $("toast");
const activeToolBar = $("activeToolBar");
const activeToolName = $("activeToolName");
const clearActiveToolButton = $("clearActiveTool");
const mainAgentTitle = $("mainAgentTitle");
const floatingAgentTitle = $("floatingAgentTitle");
const scrollTopButton = $("scrollTopButton");
const scrollBottomButton = $("scrollBottomButton");

const MAX_DOCUMENT_BYTES =
    25 * 1024 * 1024;

const ALLOWED_DOCUMENT_EXTENSIONS = [
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".csv",
    ".json"
];

let activeTool = null;
let thinkingInterval = null;
let mediaRecorder = null;
let mediaStream = null;
let audioChunks = [];
let recordingStartedAt = null;
let recordingTimer = null;
let recordingTimeout = null;
let recordingCancelled = false;
let audioContext = null;
let analyser = null;
let waveformData = null;
let waveformFrame = null;
let scrollUiFrame = null;

function addMessage(sender, message) {
    const row =
        document.createElement("div");

    const bubble =
        document.createElement("div");

    const isUser =
        sender === "user";

    row.className =
        `message-row ${isUser ? "user-row" : "agent-row"}`;

    bubble.className =
        `message ${isUser ? "user-message" : "agent-message"}`;

    bubble.textContent =
        String(message ?? "");

    row.appendChild(bubble);
    chat.prepend(row);
}

function resizeInput() {
    if (!messageInput) return;

    messageInput.style.height = "auto";
    messageInput.style.height =
        `${Math.min(messageInput.scrollHeight, 180)}px`;
}

function showToast(message) {
    if (!toast) return;

    toast.textContent = message;
    toast.hidden = false;

    clearTimeout(showToast.timeout);

    showToast.timeout =
        setTimeout(() => {
            toast.hidden = true;
        }, 2600);
}

function closeMenus() {
    if (toolsMenu) {
        toolsMenu.hidden = true;
    }

    if (voiceMenu) {
        voiceMenu.hidden = true;
    }

    toolsButton?.classList.remove(
        "active"
    );

    if (
        !mediaRecorder
        || mediaRecorder.state !== "recording"
    ) {
        voiceButton?.classList.remove(
            "active"
        );
    }
}

function toggleMenu(menu, button) {
    if (!menu || !button) return;

    const open = menu.hidden;

    closeMenus();

    menu.hidden = !open;

    button.classList.toggle(
        "active",
        open
    );
}

function clamp(
    value,
    min = 0,
    max = 1
) {
    return Math.min(
        Math.max(value, min),
        max
    );
}

function updateScrollUI() {
    scrollUiFrame = null;

    if (
        mainAgentTitle
        && floatingAgentTitle
    ) {
        const rect =
            mainAgentTitle
                .getBoundingClientRect();

        const progress =
            clamp(
                (90 - rect.bottom) / 90
            );

        mainAgentTitle.style.opacity =
            String(1 - progress);

        mainAgentTitle.style.filter =
            `blur(${(progress * 2).toFixed(2)}px)`;

        floatingAgentTitle.style.opacity =
            String(progress);

        floatingAgentTitle.style.transform =
            `translate(-50%, ${(1 - progress) * 10}px) scale(${.985 + progress * .015})`;

        floatingAgentTitle.style.filter =
            `blur(${((1 - progress) * 3).toFixed(2)}px)`;
    }

    const maxScroll =
        Math.max(
            document.documentElement.scrollHeight
                - window.innerHeight,
            0
        );

    scrollTopButton?.classList.toggle(
        "is-unavailable",
        window.scrollY < 8
    );

    scrollBottomButton?.classList.toggle(
        "is-unavailable",
        maxScroll - window.scrollY < 8
    );
}

function scheduleScrollUI() {
    if (!scrollUiFrame) {
        scrollUiFrame =
            requestAnimationFrame(
                updateScrollUI
            );
    }
}

function applyPermissions() {
    document
        .querySelectorAll(".admin-tool")
        .forEach(item => {
            const allowed =
                userRole === "admin";

            item.classList.toggle(
                "locked-tool",
                !allowed
            );

            item.dataset.locked =
                allowed ? "0" : "1";
        });

    document
        .querySelectorAll(".login-tool")
        .forEach(item => {
            const allowed =
                userRole === "user"
                || userRole === "admin";

            item.classList.toggle(
                "locked-tool",
                !allowed
            );

            item.dataset.locked =
                allowed ? "0" : "1";
        });
}

function updateActiveToolUI() {
    document
        .querySelectorAll("[data-tool]")
        .forEach(item => {
            item.classList.toggle(
                "selected-tool",
                item.dataset.tool === activeTool
            );
        });

    if (
        !activeToolBar
        || !activeToolName
        || !messageInput
    ) {
        return;
    }

    const info =
        UI.tools[activeTool];

    if (!activeTool || !info) {
        activeToolBar.hidden = true;

        messageInput.placeholder =
            UI.defaultPlaceholder;

        return;
    }

    activeToolName.textContent =
        info[0];

    activeToolBar.hidden = false;

    messageInput.placeholder =
        info[1];
}

function setActiveTool(tool) {
    if (!UI.tools[tool]) return;

    activeTool = tool;

    updateActiveToolUI();
    messageInput?.focus();
}

function clearActiveTool() {
    activeTool = null;

    updateActiveToolUI();
    messageInput?.focus();
}

function stopThinking() {
    if (thinkingInterval) {
        clearInterval(
            thinkingInterval
        );

        thinkingInterval = null;
    }

    if (thinking) {
        thinking.hidden = true;
    }
}

function startThinking(
    text = UI.thinking
) {
    stopThinking();

    if (
        !thinking
        || !thinkingText
    ) {
        return;
    }

    let dots = 1;

    thinking.hidden = false;

    thinkingText.textContent =
        `${text}.`;

    thinkingInterval =
        setInterval(() => {
            dots =
                dots >= 3
                    ? 1
                    : dots + 1;

            thinkingText.textContent =
                `${text}${".".repeat(dots)}`;
        }, 500);
}

function updateConfirmationButtons(
    responseText
) {
    if (!confirmationButtons) {
        return;
    }

    const text =
        String(
            responseText || ""
        ).toLowerCase();

    const requiresConfirmation =
        text.includes(
            "onaylıyor musunuz? (y/n)"
        )
        || text.includes(
            "onaylıyor musunuz"
        )
        || text.includes(
            "do you confirm? (y/n)"
        )
        || text.includes(
            "do you confirm"
        )
        || text.includes(
            "confirm this action"
        );

    confirmationButtons.hidden =
        !requiresConfirmation;
}

function updateGuestLimit(data) {
    if (
        !guestRemaining
        || data.guest_messages === undefined
        || data.guest_limit === undefined
    ) {
        return;
    }

    guestRemaining.textContent =
        Math.max(
            data.guest_limit
                - data.guest_messages,
            0
        );
}

async function getJson(response) {
    try {
        return await response.json();
    } catch {
        return {};
    }
}

async function sendToAgent(
    message,
    {
        showUserMessage = true,
        tool = activeTool
    } = {}
) {
    message =
        String(
            message || ""
        ).trim();

    if (!message) return;

    if (showUserMessage) {
        addMessage(
            "user",
            message
        );
    }

    startThinking();

    try {
        const response =
            await fetch(
                "/chat",
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json",
                        "X-CSRF-Token":
                            csrfToken
                    },
                    body: JSON.stringify({
                        message,
                        tool
                    })
                }
            );

        const data =
            await getJson(response);

        if (!response.ok) {
            const message =
                data.response
                || data.error
                || UI.serverUnavailable;

            addMessage(
                "agent",
                message
            );

            updateConfirmationButtons(
                message
            );

            updateGuestLimit(data);
            return;
        }

        const responseText =
            data.response
            || UI.serverUnavailable;

        addMessage(
            "agent",
            responseText
        );

        updateConfirmationButtons(
            responseText
        );

        updateGuestLimit(data);

    } catch {
        addMessage(
            "agent",
            UI.serverUnavailable
        );

        if (confirmationButtons) {
            confirmationButtons.hidden = true;
        }

    } finally {
        stopThinking();
        scheduleScrollUI();
    }
}

async function sendMessage() {
    const message =
        messageInput?.value.trim();

    if (!message) return;

    messageInput.value = "";
    resizeInput();

    await sendToAgent(
        message
    );

    messageInput.focus();
}

async function transcribeAudioFile(file) {
    const formData =
        new FormData();

    formData.append(
        "audio",
        file,
        file.name || "recording.webm"
    );

    startThinking(
        UI.transcribing
    );

    try {
        const response =
            await fetch(
                "/transcribe-audio",
                {
                    method: "POST",
                    headers: {
                        "X-CSRF-Token":
                            csrfToken
                    },
                    body: formData
                }
            );

        const data =
            await getJson(response);

        if (
            !response.ok
            || !data.ok
        ) {
            showToast(
                data.error
                || UI.transcriptionFailed
            );

            return;
        }

        messageInput.value =
            data.text;

        resizeInput();
        messageInput.focus();

        showToast(
            UI.transcriptionDone
        );

    } catch {
        showToast(
            UI.transcriptionFailed
        );

    } finally {
        stopThinking();
    }
}

function buildWaveform() {
    if (!voiceWave) return;

    voiceWave.replaceChildren();

    for (
        let index = 0;
        index < 34;
        index++
    ) {
        voiceWave.appendChild(
            document.createElement(
                "span"
            )
        );
    }
}

function updateWaveform() {
    if (
        !analyser
        || !waveformData
        || !voiceWave
    ) {
        return;
    }

    analyser.getByteTimeDomainData(
        waveformData
    );

    let total = 0;

    for (const value of waveformData) {
        const sample =
            (value - 128) / 128;

        total +=
            sample * sample;
    }

    const rms =
        Math.sqrt(
            total
            / waveformData.length
        );

    const strength =
        Math.min(
            rms * 18,
            1
        );

    const bars =
        voiceWave.querySelectorAll(
            "span"
        );

    bars.forEach(
        (bar, index) => {
            const position =
                index
                / Math.max(
                    bars.length - 1,
                    1
                );

            const centerWeight =
                1
                - Math.abs(
                    position * 2 - 1
                );

            const sampleIndex =
                Math.floor(
                    index
                    / bars.length
                    * waveformData.length
                );

            const sampleStrength =
                Math.abs(
                    (
                        waveformData[
                            sampleIndex
                        ] - 128
                    ) / 128
                );

            const dynamicLevel =
                Math.min(
                    strength * .75
                    + sampleStrength * 1.8,
                    1
                );

            const height =
                16
                + dynamicLevel
                * (
                    20
                    + centerWeight * 18
                );

            bar.style.height =
                `${Math.round(height)}px`;
        }
    );

    waveformFrame =
        requestAnimationFrame(
            updateWaveform
        );
}

function updateRecordingTime() {
    if (
        !recordingStartedAt
        || !recordingTime
    ) {
        return;
    }

    const elapsed =
        Math.min(
            Math.floor(
                (
                    Date.now()
                    - recordingStartedAt
                ) / 1000
            ),
            30
        );

    recordingTime.textContent =
        `00:${String(elapsed).padStart(2, "0")}`;
}

function setRecordingUI(active) {
    if (recordingPanel) {
        recordingPanel.hidden =
            !active;
    }

    if (messageInput) {
        messageInput.hidden =
            active;
    }

    if (toolsButton) {
        toolsButton.hidden =
            active;
    }

    if (sendButton) {
        sendButton.hidden =
            active;
    }

    if (activeToolBar) {
        activeToolBar.style.display =
            active ? "none" : "";
    }

    voiceButton?.classList.toggle(
        "recording",
        active
    );

    voiceButton?.classList.toggle(
        "active",
        active
    );
}

async function cleanupRecording() {
    clearInterval(
        recordingTimer
    );

    clearTimeout(
        recordingTimeout
    );

    recordingTimer = null;
    recordingTimeout = null;

    if (waveformFrame) {
        cancelAnimationFrame(
            waveformFrame
        );

        waveformFrame = null;
    }

    if (
        audioContext
        && audioContext.state !== "closed"
    ) {
        try {
            await audioContext.close();
        } catch {
        }
    }

    mediaStream
        ?.getTracks()
        .forEach(track => {
            track.stop();
        });

    audioContext = null;
    analyser = null;
    waveformData = null;
    mediaStream = null;
    mediaRecorder = null;
    recordingStartedAt = null;

    setRecordingUI(false);
}

async function beginRecording() {
    closeMenus();

    try {
        if (
            !navigator.mediaDevices
            || !navigator.mediaDevices
                .getUserMedia
        ) {
            throw new Error(
                UI.microphoneMissing
            );
        }

        mediaStream =
            await navigator.mediaDevices
                .getUserMedia({
                    audio: {
                        echoCancellation: true,
                        noiseSuppression: true,
                        autoGainControl: true
                    }
                });

        const audioTrack =
            mediaStream
                .getAudioTracks()[0];

        if (
            !audioTrack
            || audioTrack.readyState
                !== "live"
        ) {
            throw new Error(
                UI.microphoneMissing
            );
        }

        audioChunks = [];
        recordingCancelled = false;

        mediaRecorder =
            new MediaRecorder(
                mediaStream
            );

        mediaRecorder.addEventListener(
            "dataavailable",
            event => {
                if (
                    event.data?.size > 0
                ) {
                    audioChunks.push(
                        event.data
                    );
                }
            }
        );

        mediaRecorder.addEventListener(
            "stop",
            async () => {
                const cancelled =
                    recordingCancelled;

                const mimeType =
                    mediaRecorder?.mimeType
                    || "audio/webm";

                const blob =
                    new Blob(
                        audioChunks,
                        {
                            type: mimeType
                        }
                    );

                await cleanupRecording();

                if (cancelled) {
                    showToast(
                        UI.recordingCancelled
                    );

                    return;
                }

                if (!blob.size) {
                    showToast(
                        UI.recordingEmpty
                    );

                    return;
                }

                await transcribeAudioFile(
                    new File(
                        [blob],
                        "recording.webm",
                        {
                            type: blob.type
                        }
                    )
                );
            }
        );

        buildWaveform();

        const AudioContextClass =
            window.AudioContext
            || window.webkitAudioContext;

        audioContext =
            new AudioContextClass();

        if (
            audioContext.state
            === "suspended"
        ) {
            await audioContext.resume();
        }

        const source =
            audioContext
                .createMediaStreamSource(
                    mediaStream
                );

        analyser =
            audioContext
                .createAnalyser();

        analyser.fftSize = 256;

        waveformData =
            new Uint8Array(
                analyser.fftSize
            );

        source.connect(
            analyser
        );

        mediaRecorder.start(250);

        recordingStartedAt =
            Date.now();

        if (recordingTime) {
            recordingTime.textContent =
                "00:00";
        }

        setRecordingUI(true);
        updateWaveform();

        recordingTimer =
            setInterval(
                updateRecordingTime,
                250
            );

        recordingTimeout =
            setTimeout(
                stopRecording,
                30000
            );

    } catch {
        await cleanupRecording();

        showToast(
            UI.microphoneDenied
        );
    }
}

function stopRecording() {
    if (
        mediaRecorder
        && mediaRecorder.state
            !== "inactive"
    ) {
        mediaRecorder.stop();
    }
}

function cancelVoiceRecording() {
    if (
        !mediaRecorder
        || mediaRecorder.state
            === "inactive"
    ) {
        return;
    }

    recordingCancelled = true;

    mediaRecorder.stop();
}

function getFileExtension(
    filename
) {
    const index =
        filename.lastIndexOf(".");

    return index === -1
        ? ""
        : filename
            .slice(index)
            .toLowerCase();
}

async function uploadDocument(file) {
    if (
        file.size
        > MAX_DOCUMENT_BYTES
    ) {
        showToast(
            UI.documentTooLarge
        );

        return;
    }

    if (!file.size) {
        showToast(
            UI.documentEmpty
        );

        return;
    }

    if (
        !ALLOWED_DOCUMENT_EXTENSIONS
            .includes(
                getFileExtension(
                    file.name
                )
            )
    ) {
        showToast(
            UI.documentTypes
        );

        return;
    }

    const formData =
        new FormData();

    formData.append(
        "document",
        file,
        file.name
    );

    startThinking(
        UI.documentUploading
    );

    try {
        const response =
            await fetch(
                "/upload-document",
                {
                    method: "POST",
                    headers: {
                        "X-CSRF-Token":
                            csrfToken
                    },
                    body: formData
                }
            );

        const data =
            await getJson(response);

        if (
            !response.ok
            || !data.ok
        ) {
            showToast(
                data.error
                || UI.documentFailed
            );

            return;
        }

        showToast(
            UI.documentReady(
                data.filename,
                data.chunks
            )
        );

        setActiveTool(
            "rag"
        );

    } catch {
        showToast(
            UI.documentFailed
        );

    } finally {
        stopThinking();
    }
}

sendButton?.addEventListener(
    "click",
    sendMessage
);

messageInput?.addEventListener(
    "input",
    resizeInput
);

messageInput?.addEventListener(
    "keydown",
    event => {
        if (
            event.key === "Enter"
            && !event.shiftKey
        ) {
            event.preventDefault();
            sendMessage();
        }
    }
);

toolsButton?.addEventListener(
    "click",
    event => {
        event.stopPropagation();

        toggleMenu(
            toolsMenu,
            toolsButton
        );
    }
);

voiceButton?.addEventListener(
    "click",
    event => {
        event.stopPropagation();

        if (
            mediaRecorder?.state
            === "recording"
        ) {
            stopRecording();
            return;
        }

        toggleMenu(
            voiceMenu,
            voiceButton
        );
    }
);

startVoiceRecording
    ?.addEventListener(
        "click",
        beginRecording
    );

uploadVoiceFile
    ?.addEventListener(
        "click",
        () => {
            closeMenus();

            audioFileInput?.click();
        }
    );

audioFileInput
    ?.addEventListener(
        "change",
        async () => {
            const file =
                audioFileInput
                    .files?.[0];

            audioFileInput.value = "";

            if (file) {
                await transcribeAudioFile(
                    file
                );
            }
        }
    );

cancelRecording
    ?.addEventListener(
        "click",
        cancelVoiceRecording
    );

generalFileInput
    ?.addEventListener(
        "change",
        async () => {
            const file =
                generalFileInput
                    .files?.[0];

            generalFileInput.value = "";

            if (file) {
                await uploadDocument(
                    file
                );
            }
        }
    );

document
    .querySelectorAll(
        "[data-tool]"
    )
    .forEach(item => {
        item.addEventListener(
            "click",
            () => {
                if (
                    item.dataset.locked
                    === "1"
                ) {
                    showToast(
                        UI.permissionDenied
                    );

                    return;
                }

                const tool =
                    item.dataset.tool;

                closeMenus();

                if (
                    tool === "upload"
                ) {
                    generalFileInput
                        ?.click();

                    return;
                }

                setActiveTool(
                    tool
                );
            }
        );
    });

clearActiveToolButton
    ?.addEventListener(
        "click",
        clearActiveTool
    );

document.addEventListener(
    "click",
    event => {
        if (
            !event.target.closest(
                ".tools-anchor"
            )
            && !event.target.closest(
                ".voice-anchor"
            )
        ) {
            closeMenus();
        }
    }
);

yesButton?.addEventListener(
    "click",
    async () => {
        confirmationButtons.hidden =
            true;

        await sendToAgent(
            "y",
            {
                showUserMessage: false,
                tool: null
            }
        );
    }
);

noButton?.addEventListener(
    "click",
    async () => {
        confirmationButtons.hidden =
            true;

        await sendToAgent(
            "n",
            {
                showUserMessage: false,
                tool: null
            }
        );
    }
);

detailsButton?.addEventListener(
    "click",
    async () => {
        await sendToAgent(
            UI.detailsCommand,
            {
                showUserMessage: false,
                tool: null
            }
        );
    }
);

scrollTopButton?.addEventListener(
    "click",
    () => {
        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });
    }
);

scrollBottomButton
    ?.addEventListener(
        "click",
        () => {
            window.scrollTo({
                top:
                    document
                        .documentElement
                        .scrollHeight,
                behavior: "smooth"
            });
        }
    );

window.addEventListener(
    "scroll",
    scheduleScrollUI,
    {
        passive: true
    }
);

window.addEventListener(
    "resize",
    scheduleScrollUI
);

applyPermissions();
updateActiveToolUI();
resizeInput();
updateScrollUI();