const screens = document.querySelectorAll('.screen');
let currentIndex = 0;
let countdownInterval = null;
let privacyPollInterval = null;
let reportLoadingTimeout = null;
let typingInterval = null;

let timeLeft = 30;
let isPaused = false;

let captureLoopStarted = false;

let cameraLoadingTimeout = null;

let sittingConfirmed = false;
let preCountdownTimeout = null;

let currentUuid = "";

let collectedMetrics = {
    scores: [],
    turtle: [],
    torso: [],
    shoulder: [],
    pelvis: [],
    legCross: []
};

let finalReportData = {
    score: 0,
    turtle: 0,
    torso: 0,
    shoulder: 0,
    pelvis: 0,
    legCrossSeconds: 0
};

let generatedLLMAdvice = "";

const SUPABASE_URL = "https://orehrskvecfrfqxdhfur.supabase.co";

const backendApi = {
    async toggle_camera(enabled) {
        await fetch('/api/toggle_camera', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        }).catch(() => {});
    },
    async get_supabase_key() {
        const res = await fetch('/api/supabase_key');
        if (!res.ok) throw new Error('supabase key fetch failed');
        const data = await res.json();
        return data.key;
    },
    async generate_llm_advice(metrics) {
        const res = await fetch('/api/generate_llm_advice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(metrics)
        });
        if (!res.ok) throw new Error('advice fetch failed');
        const data = await res.json();
        return data.advice;
    },
    async setup_and_start(payload) {
        await fetch('/api/setup_and_start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).catch(() => {});
    }
};

function createFrameRenderer(imgEl) {
    let busy = false;
    let pendingSrc = null;

    function paint(src) {
        busy = true;
        imgEl.src = src;
    }

    function onSettled() {
        busy = false;
        if (pendingSrc !== null) {
            const next = pendingSrc;
            pendingSrc = null;
            paint(next);
        }
    }

    imgEl.addEventListener('load', onSettled);
    imgEl.addEventListener('error', onSettled);

    return function render(src) {
        if (busy) {
            pendingSrc = src;
            return;
        }
        paint(src);
    };
}

const renderCameraView = createFrameRenderer(document.getElementById('camera-view'));

let latestCameraFrameSrc = null;

let shortsPlayer = null;
let shortsPlayerReady = false;
let pendingShortVideoId = null;

function onYouTubeIframeAPIReady() {
    shortsPlayer = new YT.Player('shorts-player', {
        width: '100%',
        height: '100%',
        playerVars: {
            playsinline: 1,
            controls: 0,
            modestbranding: 1,
            rel: 0
        },
        events: {
            onReady: () => {
                shortsPlayerReady = true;
                if (pendingShortVideoId) {
                    shortsPlayer.loadVideoById(pendingShortVideoId);
                    pendingShortVideoId = null;
                }
            }
        }
    });
}
window.onYouTubeIframeAPIReady = onYouTubeIframeAPIReady;

async function loadNextShort() {
    let videoId = null;
    try {
        const res = await fetch('/api/next_short');
        const data = await res.json();
        videoId = data.videoId;
    } catch (err) {
        return;
    }
    if (!videoId) return;

    if (shortsPlayerReady && shortsPlayer) {
        shortsPlayer.loadVideoById(videoId);
        shortsPlayer.unMute();
    } else {
        pendingShortVideoId = videoId;
    }
}

document.getElementById('btn-next-short').addEventListener('click', () => {
    loadNextShort();
});

(function connectEventStream() {
    const evtSource = new EventSource('/api/events');
    evtSource.onmessage = (e) => {
        let data;
        try {
            data = JSON.parse(e.data);
        } catch (err) {
            return;
        }
        if (data.type === 'frame') {
            window.updateFrame(
                data.image, data.statusText, data.isNormal, data.score,
                data.turtleAng, data.torsoAng, data.shoulderAng, data.pelvisAng,
                data.legCross, data.partScores
            );
        } else if (data.type === 'camera_ready') {
            window.onCameraReady && window.onCameraReady();
        }
    };
    evtSource.onerror = () => {
    };
})();

screens.forEach((screen, idx) => {
    if (idx === 0) screen.removeAttribute('style');
    screen.classList.toggle('active', idx === currentIndex);
});

const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

async function showScreen(index, useFade = true) {
    if (index < 0 || index >= screens.length) return;

    if (currentIndex === 1) {
        clearTimeout(cameraLoadingTimeout);
    }

    if (currentIndex === 4) {
        clearInterval(countdownInterval);
        clearTimeout(preCountdownTimeout);
        preCountdownTimeout = null;
        sittingConfirmed = false;
        backendApi.toggle_camera(false);
        if (shortsPlayerReady && shortsPlayer) shortsPlayer.stopVideo();
    }

    if (currentIndex === 3) clearInterval(privacyPollInterval);
    clearTimeout(reportLoadingTimeout);

    if (currentIndex === 6) {
        document.querySelectorAll('.progress-bar-fill').forEach(bar => bar.style.width = '0%');
        const scoreRing = document.getElementById('score-ring-progress');
        if (scoreRing) scoreRing.style.strokeDashoffset = '314';
        clearInterval(typingInterval);
        const adviceEl = document.getElementById('llm-advice');
        if (adviceEl) adviceEl.innerText = '';
    }

    screens.forEach(screen => screen.classList.toggle('fade-effect', useFade));
    screens[currentIndex].classList.remove('active');
    currentIndex = index;
    screens[currentIndex].classList.add('active');

    if (currentIndex === 1) {
        if (!captureLoopStarted) {
            captureLoopStarted = true;
            startCaptureLoop();
        }

        clearTimeout(cameraLoadingTimeout);
        cameraLoadingTimeout = setTimeout(() => {
            if (currentIndex === 1) showScreen(2, true);
        }, 20000);
    }

    if (currentIndex === 3) {
        currentUuid = (typeof crypto !== 'undefined' && crypto.randomUUID)
            ? crypto.randomUUID()
            : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                const r = Math.random() * 16 | 0;
                const v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });

        const qrUrl = `https://focus-fit-ai.vercel.app/#${currentUuid}`;

        try {
            const qrContainer = document.getElementById("qrcode-privacy");
            qrContainer.innerHTML = "";
            new QRCode(qrContainer, { text: qrUrl, width: 260, height: 260 });
        } catch (qrErr) { }

        const targetUrl = `${SUPABASE_URL}/rest/v1/main?uuid=eq.${currentUuid}&select=*`;
        clearInterval(privacyPollInterval);

        privacyPollInterval = setInterval(() => {
            {
                backendApi.get_supabase_key().then(anonKey => {
                    fetch(targetUrl, {
                        method: 'GET',
                        headers: {
                            'apikey': anonKey,
                            'Authorization': `Bearer ${anonKey}`,
                            'Accept': 'application/json'
                        }
                    })
                    .then(res => res.ok ? res.json() : Promise.reject())
                    .then(data => {
                        if (Array.isArray(data) && data.length >= 1) {
                            clearInterval(privacyPollInterval);
                            showScreen(4, true);
                        }
                    })
                    .catch(() => {});
                }).catch(() => {});
            }
        }, 1000);
    }

    if (currentIndex === 4) {
        backendApi.toggle_camera(true);
        setViewMode('shorts');
        loadNextShort();

        collectedMetrics = { scores: [], turtle: [], torso: [], shoulder: [], pelvis: [], legCross: [] };

        timeLeft = 30;
        isPaused = true;
        sittingConfirmed = false;
        hidePreCountdown();

        const timerEl = document.getElementById('timer');
        timerEl.innerText = "30";

        clearInterval(countdownInterval);
        countdownInterval = setInterval(() => {
            if (isPaused) return;

            timeLeft--;
            timerEl.innerText = String(timeLeft).padStart(2, '0');

            if (timeLeft <= 0) {
                clearInterval(countdownInterval);

                const calcAvg = arr => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
                const legCrossRatio = calcAvg(collectedMetrics.legCross);
                finalReportData = {
                    score: Math.round(calcAvg(collectedMetrics.scores)),
                    turtle: parseFloat(calcAvg(collectedMetrics.turtle).toFixed(1)),
                    torso: parseFloat(calcAvg(collectedMetrics.torso).toFixed(1)),
                    shoulder: parseFloat(calcAvg(collectedMetrics.shoulder).toFixed(1)),
                    pelvis: parseFloat(calcAvg(collectedMetrics.pelvis).toFixed(1)),
                    legCrossSeconds: parseFloat((legCrossRatio * 30).toFixed(1))
                };

                showScreen(5, true);
            }
        }, 1000);
    }

    if (currentIndex === 5) {
        const helptext = document.getElementById('report-loading-helptext');

        (async () => {
            helptext.innerText = "리포트를 생성하는 중...";
            try {
                generatedLLMAdvice = await backendApi.generate_llm_advice(finalReportData);
            } catch (e) {
                generatedLLMAdvice = "AI 피드백을 생성하는 중 오류가 발생했습니다.";
            }
            showScreen(6, true);
        })();
    }

    if (currentIndex === 6) {
        const reportDateEl = document.getElementById('report-date');
        if (reportDateEl) {
            reportDateEl.innerText = new Date().toLocaleString('ko-KR', {
                year: 'numeric', month: 'long', day: 'numeric',
                hour: '2-digit', minute: '2-digit'
            });
        }

        document.querySelectorAll('.progress-bar-fill').forEach(bar => bar.style.width = '0%');
        const scoreRing = document.getElementById('score-ring-progress');
        if (scoreRing) scoreRing.style.strokeDashoffset = '314';
        clearInterval(typingInterval);
        const adviceEl = document.getElementById('llm-advice');
        if (adviceEl) adviceEl.innerText = '';

        const scoreNumEl = document.getElementById('report-score');
        if (scoreNumEl) {
            scoreNumEl.innerText = finalReportData.score;
        }

        const setMetricUI = (valId, barId, value, goodText, warnText) => {
            const valEl = document.getElementById(valId);
            const barEl = document.getElementById(barId);
            const numeric = Math.max(0, Math.min(100, Number(value) || 0));
            const isGood = numeric >= 90;
            if (valEl) {
                valEl.innerText = `${Math.round(numeric)}점 · ${isGood ? goodText : warnText}`;
                valEl.className = `metric-value ${isGood ? 'status-good' : 'status-warning'}`;
            }
            if (barEl) {
                barEl.className = `progress-bar-fill ${isGood ? 'fill-good' : 'fill-warning'}`;
                return { el: barEl, width: numeric + '%' };
            }
            return null;
        };

        const barTargets = [
            setMetricUI('val-turtle', 'bar-turtle', finalReportData.turtle, '양호', '주의'),
            setMetricUI('val-torso', 'bar-torso', finalReportData.torso, '안정', '주의'),
            setMetricUI('val-shoulder', 'bar-shoulder', finalReportData.shoulder, '정상', '주의'),
            setMetricUI('val-pelvis', 'bar-pelvis', finalReportData.pelvis, '정상', '주의')
        ];

        const fadeDelay = useFade ? 800 : 50;
        setTimeout(() => {
            barTargets.forEach(item => {
                if (item && item.el) item.el.style.width = item.width;
            });

            if (scoreRing) {
                const targetScore = finalReportData.score;
                const circumference = 314;
                const offset = circumference * (1 - targetScore / 100);
                scoreRing.style.strokeDashoffset = offset;
            }

            const Advice = generatedLLMAdvice;
            const container = document.getElementById('llm-advice');
            if (container) {
                container.innerText = '';
                clearInterval(typingInterval);
                let index = 0;
                typingInterval = setInterval(() => {
                    if (index < Advice.length) {
                        container.innerText += Advice.charAt(index);
                        index++;
                        container.scrollTop = container.scrollHeight;
                    } else {
                        clearInterval(typingInterval);
                    }
                }, 0);
            }
        }, fadeDelay);
    }
}

function syncCameraFieldsVisibility() {
    const sourceEl = document.getElementById('cfg-camera-source');
    const isAstra = sourceEl ? sourceEl.value === 'astra' : false;

    const camGroup = document.getElementById('cfg-cam-group');
    const debugCamGroup = document.getElementById('cfg-debug-cam-group');

    if (camGroup) camGroup.style.display = isAstra ? 'none' : '';
    if (debugCamGroup) debugCamGroup.style.display = isAstra ? '' : 'none';
}

document.getElementById('cfg-camera-source').addEventListener('change', syncCameraFieldsVisibility);
syncCameraFieldsVisibility();

function startCaptureLoop() {
    const cameraSource = document.getElementById('cfg-camera-source').value;

    backendApi.setup_and_start({
        camera_idx: cameraSource === 'astra' ? "" : document.getElementById('cfg-cam').value,
        camera_source: cameraSource,
        debug_cam_idx: document.getElementById('cfg-debug-cam').value,
        mirror_camera: document.getElementById('cfg-mirror').checked
    });
}

document.getElementById('btn-save').addEventListener('click', () => {
    showScreen(1, false);
});

document.getElementById('btn-start').addEventListener('click', () => showScreen(3, true));
document.getElementById('btn-restart').addEventListener('click', () => showScreen(2, true));
document.getElementById('btn-print').addEventListener('click', () => window.print());

window.onCameraReady = function () {
    if (currentIndex === 1) {
        clearTimeout(cameraLoadingTimeout);
        showScreen(2, true);
    }
};

function hidePreCountdown() {
    clearTimeout(preCountdownTimeout);
    preCountdownTimeout = null;
    const overlay = document.getElementById('precountdown-overlay');
    if (overlay) overlay.classList.remove('active');
}

function restartPreCountdownAnimation(numberEl) {
    numberEl.style.animation = 'none';
    void numberEl.offsetWidth;
    numberEl.style.animation = '';
}

function startPreCountdown() {
    const overlay = document.getElementById('precountdown-overlay');
    const numberEl = document.getElementById('precountdown-number');
    if (!overlay || !numberEl) {
        sittingConfirmed = true;
        isPaused = false;
        return;
    }

    clearTimeout(preCountdownTimeout);
    let count = 3;
    overlay.classList.add('active');
    numberEl.textContent = String(count);
    restartPreCountdownAnimation(numberEl);

    const tick = () => {
        count -= 1;
        if (count <= 0) {
            overlay.classList.remove('active');
            preCountdownTimeout = null;
            sittingConfirmed = true;
            isPaused = false;
            return;
        }
        numberEl.textContent = String(count);
        restartPreCountdownAnimation(numberEl);
        preCountdownTimeout = setTimeout(tick, 1000);
    };
    preCountdownTimeout = setTimeout(tick, 1000);
}

window.updateFrame = function(base64Image, statusText, isNormal, score, turtleAng, torsoAng, shoulderAng, pelvisAng, legCross, partScores) {
    if (currentIndex !== 4) return;

    if (base64Image) {
        latestCameraFrameSrc = 'data:image/jpeg;base64,' + base64Image;
        if (viewMode === 'camera') {
            renderCameraView(latestCameraFrameSrc);
        }
    }

    const statusBox = document.getElementById('status-box');

    if (typeof score !== 'undefined' && isNormal !== 2) {
        statusBox.innerText = `${statusText} (점수: ${score}점)`;
    } else {
        statusBox.innerText = statusText;
    }

    statusBox.className = "status-overlay";

    if (isNormal === 1 || isNormal === 0) {
        statusBox.classList.add(isNormal === 1 ? "status-normal" : "status-warning");

        if (!sittingConfirmed && preCountdownTimeout === null) {
            isPaused = true;
            startPreCountdown();
        }

        if (sittingConfirmed) {
            isPaused = false;
            if (typeof score === 'number') {
                collectedMetrics.scores.push(score);
                const scores = partScores || {};
                collectedMetrics.turtle.push(typeof scores.neck === "number" ? scores.neck : (turtleAng || 0));
                collectedMetrics.torso.push(typeof scores.torso === "number" ? scores.torso : (torsoAng || 0));
                collectedMetrics.shoulder.push(typeof scores.shoulder === "number" ? scores.shoulder : (shoulderAng || 0));
                collectedMetrics.pelvis.push(typeof scores.pelvis === "number" ? scores.pelvis : (pelvisAng || 0));
                collectedMetrics.legCross.push(legCross ? 1 : 0);
            }
        }
    } else {
        statusBox.classList.add("status-unknown");
        isPaused = true;
        sittingConfirmed = false;
        hidePreCountdown();
    }
};

function resetToInitialSetup() {
    clearTimeout(cameraLoadingTimeout);
    cameraLoadingTimeout = null;

    clearInterval(countdownInterval);
    countdownInterval = null;

    clearInterval(privacyPollInterval);
    privacyPollInterval = null;

    clearTimeout(reportLoadingTimeout);
    reportLoadingTimeout = null;

    clearInterval(typingInterval);
    typingInterval = null;

    hidePreCountdown();

    timeLeft = 30;
    isPaused = true;
    sittingConfirmed = false;
    captureLoopStarted = false;
    currentUuid = "";

    collectedMetrics = { scores: [], turtle: [], torso: [], shoulder: [], pelvis: [], legCross: [] };
    finalReportData = { score: 0, turtle: 0, torso: 0, shoulder: 0, pelvis: 0, legCrossSeconds: 0 };
    generatedLLMAdvice = "";

    backendApi.toggle_camera(false);

    showScreen(0, false);
}

window.addEventListener('keydown', (e) => {
    if (e.ctrlKey) {
        if (e.key === 'ArrowRight') {
            e.preventDefault();
            showScreen(currentIndex + 1, false);
        } else if (e.key === 'ArrowLeft') {
            e.preventDefault();
            showScreen(currentIndex - 1, false);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            resetToInitialSetup();
        }
    }
    if (e.key === 'F11') {
        e.preventDefault();
        if (document.fullscreenElement) {
            document.exitFullscreen().catch(() => {});
        } else {
            document.documentElement.requestFullscreen().catch(() => {});
        }
    }
});

let viewMode = 'shorts';

function setViewMode(mode) {
    viewMode = mode;

    const wrapper = document.getElementById('viewfinder-wrapper');
    const toggleBtn = document.getElementById('btn-toggle-view');
    if (wrapper) wrapper.classList.toggle('mode-camera', mode === 'camera');
    if (toggleBtn) toggleBtn.innerText = mode === 'camera' ? '쇼츠 화면 보기' : '카메라 화면 보기';

    if (mode === 'camera') {
        const cameraViewEl = document.getElementById('camera-view');
        const mirrorCheckbox = document.getElementById('cfg-mirror');
        if (cameraViewEl) cameraViewEl.classList.toggle('mirrored', !!(mirrorCheckbox && mirrorCheckbox.checked));
        if (latestCameraFrameSrc) renderCameraView(latestCameraFrameSrc);
    }
}

document.getElementById('btn-toggle-view').addEventListener('click', () => {
    setViewMode(viewMode === 'shorts' ? 'camera' : 'shorts');
});
