const screens = document.querySelectorAll('.screen');
let currentIndex = 0;
let countdownInterval = null;
let privacyPollInterval = null;
let reportLoadingTimeout = null;
let typingInterval = null;

let timeLeft = 40;
let isPaused = false;

let preCountdownActive = false;
let preCountdownInterval = null;
let preCountdownValue = 5;
const PRE_COUNTDOWN_START = 5;

let captureLoopStarted = false;

let cameraLoadingTimeout = null;

let sittingConfirmed = false;

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

let worstScoreValue = null;
let worstScorePhotoSrc = null;

const SUPABASE_URL = "https://orehrskvecfrfqxdhfur.supabase.co";

const backendApi = {
    async toggle_camera(enabled) {
        await fetch('/api/toggle_camera', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        }).catch(() => {});
    },
    async stop_capture() {
        await fetch('/api/stop_capture', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
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

let shortsHistory = [];
let shortsHistoryIndex = -1;
let shortsFetchInFlight = false;
let lastShortsDirection = 'next';

const SHORTS_PLAYER_ID = 'shorts-player';
const SHORTS_INTRO_COVER_MS = 1500;
let shortsIntroCoverTimeout = null;

function getShortsIntroCover() {
    let cover = document.getElementById('shorts-intro-cover');
    if (!cover) {
        const wrap = document.getElementById('shorts-video-wrap');
        if (!wrap) return null;
        cover = document.createElement('div');
        cover.id = 'shorts-intro-cover';
        wrap.appendChild(cover);
    }
    return cover;
}

function showShortsIntroCover() {
    const cover = getShortsIntroCover();
    if (!cover) return;
    if (shortsIntroCoverTimeout) clearTimeout(shortsIntroCoverTimeout);
    cover.classList.remove('hidden');
}

function hideShortsIntroCoverSoon(delay) {
    const cover = getShortsIntroCover();
    if (!cover) return;
    if (shortsIntroCoverTimeout) clearTimeout(shortsIntroCoverTimeout);
    shortsIntroCoverTimeout = setTimeout(() => {
        cover.classList.add('hidden');
    }, delay);
}

function recreateShortsPlayerElement() {
    const oldEl = document.getElementById(SHORTS_PLAYER_ID);
    const wrap = document.getElementById('shorts-video-wrap') || (oldEl && oldEl.parentElement);
    const freshEl = document.createElement('div');
    freshEl.id = SHORTS_PLAYER_ID;

    if (oldEl && oldEl.parentElement) {
        oldEl.parentElement.replaceChild(freshEl, oldEl);
    } else if (wrap) {
        wrap.insertBefore(freshEl, wrap.firstChild);
    }
    return freshEl;
}

function createShortsPlayer() {
    shortsPlayerReady = false;
    recreateShortsPlayerElement();

    shortsPlayer = new YT.Player(SHORTS_PLAYER_ID, {
        width: '100%',
        height: '100%',
        playerVars: {
            playsinline: 1,
            controls: 0,
            autohide: 1,
            modestbranding: 1,
            rel: 0,
            cc_load_policy: 0,
            iv_load_policy: 3,
            disablekb: 1
        },
        events: {
            onReady: () => {
                shortsPlayerReady = true;
                try { shortsPlayer.unloadModule('captions'); } catch (e) {}
                if (pendingShortVideoId) {
                    const videoId = pendingShortVideoId;
                    pendingShortVideoId = null;
                    showShortsIntroCover();
                    shortsPlayer.loadVideoById(videoId);
                    if (viewMode !== 'camera') { try { shortsPlayer.unMute(); } catch (e) {} }
                    hideShortsIntroCoverSoon(SHORTS_INTRO_COVER_MS);
                }
            },
            onStateChange: (event) => {
                if (event.data === YT.PlayerState.PLAYING) {
                    try { shortsPlayer.unloadModule('captions'); } catch (e) {}
                }
                if (event.data === YT.PlayerState.ENDED) {
                    shortsPlayer.seekTo(0, true);
                    shortsPlayer.playVideo();
                }
                if (event.data === YT.PlayerState.CUED && viewMode !== 'camera' && !preCountdownActive) {
                    shortsPlayer.playVideo();
                }
                if (event.data === YT.PlayerState.PLAYING && preCountdownActive) {
                    try { shortsPlayer.pauseVideo(); } catch (e) {}
                }
                if (currentIndex !== 4) {
                    try { shortsPlayer.pauseVideo(); } catch (e) {}
                }
            },
            onError: (event) => {
                console.warn('[Shorts] 재생 불가(code=' + event.data + '), 건너뜀 (방향: ' + lastShortsDirection + ')');
                if (currentIndex === 4) {
                    skipBrokenShort();
                }
            }
        }
    });
}

function recreateShortsPlayer(videoId) {
    showShortsIntroCover();
    if (shortsPlayer) {
        try { shortsPlayer.destroy(); } catch (e) {}
    }
    shortsPlayer = null;
    shortsPlayerReady = false;
    if (videoId) pendingShortVideoId = videoId;
    createShortsPlayer();
}
window.recreateShortsPlayer = recreateShortsPlayer;

function onYouTubeIframeAPIReady() {
    createShortsPlayer();
}
window.onYouTubeIframeAPIReady = onYouTubeIframeAPIReady;

async function fetchNextShortVideoId() {
    try {
        const res = await fetch('/api/next_short');
        const data = await res.json();
        return data.videoId || null;
    } catch (err) {
        return null;
    }
}

function updateShortsNavButtons() {
    const prevBtn = document.getElementById('btn-prev-short');
    if (prevBtn) prevBtn.disabled = shortsHistoryIndex <= 0;
}

function resetShortsHistory() {
    shortsHistory = [];
    shortsHistoryIndex = -1;
    updateShortsNavButtons();
}

function animateShortsTransition(direction) {
    const playerEl = document.getElementById('shorts-player');
    if (!playerEl) return;
    playerEl.classList.remove('shorts-anim-next', 'shorts-anim-prev');
    void playerEl.offsetWidth;
    playerEl.classList.add(direction === 'prev' ? 'shorts-anim-prev' : 'shorts-anim-next');
}

(function setupShortsAnimReset() {
    const wrap = document.getElementById('shorts-video-wrap');
    if (!wrap) return;
    wrap.addEventListener('animationend', (e) => {
        if (e.target && e.target.id === 'shorts-player') {
            e.target.classList.remove('shorts-anim-next', 'shorts-anim-prev');
        }
    });
})();

function playShortVideo(videoId, direction) {
    if (!videoId) return;
    lastShortsDirection = direction === 'prev' ? 'prev' : 'next';
    recreateShortsPlayer(videoId);
    animateShortsTransition(direction);
}

function goToShortAt(index, direction) {
    const videoId = shortsHistory[index];
    if (!videoId) return;
    shortsHistoryIndex = index;
    updateShortsNavButtons();
    playShortVideo(videoId, direction);
}

async function goToNextShort() {
    if (shortsHistoryIndex < shortsHistory.length - 1) {
        goToShortAt(shortsHistoryIndex + 1, 'next');
        return;
    }
    if (shortsFetchInFlight) return;
    shortsFetchInFlight = true;
    const videoId = await fetchNextShortVideoId();
    shortsFetchInFlight = false;
    if (!videoId) return;
    shortsHistory.push(videoId);
    goToShortAt(shortsHistory.length - 1, 'next');
}

function goToPrevShort() {
    if (shortsHistoryIndex <= 0) return;
    goToShortAt(shortsHistoryIndex - 1, 'prev');
}

function skipBrokenShort() {
    if (lastShortsDirection === 'prev' && shortsHistoryIndex > 0) {
        goToPrevShort();
    } else {
        goToNextShort();
    }
}

document.getElementById('btn-next-short').addEventListener('click', () => {
    goToNextShort();
});

document.getElementById('btn-prev-short').addEventListener('click', () => {
    goToPrevShort();
});

(function setupShortsWheelNav() {
    let wheelLocked = false;

    function handleShortsWheel(e) {
        if (currentIndex !== 4) return;
        if (viewMode === 'camera') return;
        if (preCountdownActive) return;
        if (Math.abs(e.deltaY) < 8) return;
        e.preventDefault();
        if (wheelLocked) return;
        wheelLocked = true;
        if (e.deltaY > 0) {
            goToNextShort();
        } else {
            goToPrevShort();
        }
        setTimeout(() => { wheelLocked = false; }, 450);
    }

    document.addEventListener('wheel', handleShortsWheel, { passive: false });

    const shield = document.getElementById('shorts-scroll-shield');
    if (shield) {
        shield.addEventListener('wheel', handleShortsWheel, { passive: false });
    }
})();

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
        clearInterval(preCountdownInterval);
        preCountdownInterval = null;
        preCountdownActive = false;
        hidePreCountdownOverlay();
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

    if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
    }

    if (currentIndex === 1) {
        if (!captureLoopStarted) {
            captureLoopStarted = true;
            startCaptureLoop();
        }

        clearTimeout(cameraLoadingTimeout);
        cameraLoadingTimeout = setTimeout(() => {
            if (currentIndex === 1) showScreen(isDebugMode() ? 4 : 2, true);
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
        resetShortsHistory();
        goToNextShort();

        collectedMetrics = { scores: [], turtle: [], torso: [], shoulder: [], pelvis: [], legCross: [] };
        worstScoreValue = null;
        worstScorePhotoSrc = null;

        timeLeft = 40;
        isPaused = true;
        sittingConfirmed = false;

        const timerEl = document.getElementById('timer');

        const statusBox = document.getElementById('status-box');
        if (statusBox) statusBox.style.display = isDebugMode() ? '' : 'none';

        clearInterval(countdownInterval);
        clearInterval(preCountdownInterval);

        const startMeasurementCountdown = () => {
            preCountdownActive = false;
            hidePreCountdownOverlay();
            timerEl.innerText = "40";

            if (shortsPlayerReady && shortsPlayer && viewMode !== 'camera') {
                try { shortsPlayer.playVideo(); } catch (e) {}
            }

            countdownInterval = setInterval(() => {
                if (isPaused || isDebugMode()) return;

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
                        legCrossSeconds: parseFloat((legCrossRatio * 40).toFixed(1))
                    };

                    showScreen(5, true);
                }
            }, 1000);
        };

        if (isDebugMode()) {
            timerEl.innerText = "40";
            startMeasurementCountdown();
        } else {
            preCountdownActive = true;
            preCountdownValue = PRE_COUNTDOWN_START;
            timerEl.innerText = "40";
            showPreCountdownOverlay(preCountdownValue);

            preCountdownInterval = setInterval(() => {
                preCountdownValue--;
                if (preCountdownValue <= 0) {
                    clearInterval(preCountdownInterval);
                    preCountdownInterval = null;
                    startMeasurementCountdown();
                } else {
                    showPreCountdownOverlay(preCountdownValue);
                }
            }, 1000);
        }
    }

    if (currentIndex === 5) {
        (async () => {
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

        const photoCardEl = document.getElementById('worst-photo-card');
        const photoImgEl = document.getElementById('report-worst-photo');
        const photoCaptionEl = document.getElementById('report-worst-photo-caption');
        if (photoCardEl && photoImgEl) {
            if (worstScorePhotoSrc) {
                photoImgEl.src = worstScorePhotoSrc;
                if (photoCaptionEl) {
                    photoCaptionEl.innerText = `측정 중 가장 낮았던 점수: ${worstScoreValue}점`;
                }
                photoCardEl.style.display = '';
            } else {
                photoCardEl.style.display = 'none';
            }
        }

        const SCORE_TIER_NORMAL_MIN = 85;
        const SCORE_TIER_CAUTION_MIN = 60;

        const tierFor = (numeric) => {
            if (numeric >= SCORE_TIER_NORMAL_MIN) return { key: 'normal', label: '정상' };
            if (numeric >= SCORE_TIER_CAUTION_MIN) return { key: 'caution', label: '주의' };
            return { key: 'danger', label: '위험' };
        };

        const setMetricUI = (valId, barId, value) => {
            const valEl = document.getElementById(valId);
            const barEl = document.getElementById(barId);
            const numeric = Math.max(0, Math.min(100, Number(value) || 0));
            const tier = tierFor(numeric);
            if (valEl) {
                valEl.innerText = `${Math.round(numeric)}점 · ${tier.label}`;
                valEl.className = `metric-value metric-status-${tier.key}`;
            }
            if (barEl) {
                barEl.className = `progress-bar-fill fill-${tier.key}`;
                return { el: barEl, width: numeric + '%' };
            }
            return null;
        };

        const barTargets = [
            setMetricUI('val-turtle', 'bar-turtle', finalReportData.turtle),
            setMetricUI('val-torso', 'bar-torso', finalReportData.torso),
            setMetricUI('val-shoulder', 'bar-shoulder', finalReportData.shoulder),
            setMetricUI('val-pelvis', 'bar-pelvis', finalReportData.pelvis)
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
                container.innerHTML = '';
                clearInterval(typingInterval);
                let index = 0;
                let rawText = '';
                typingInterval = setInterval(() => {
                    if (index < Advice.length) {
                        rawText += Advice.charAt(index);
                        index++;
                        container.innerHTML = renderBoldOnlyMarkdown(rawText);
                        container.scrollTop = container.scrollHeight;
                    } else {
                        clearInterval(typingInterval);
                    }
                }, 0);
            }
        }, fadeDelay);
    }
}

function isDebugMode() {
    const el = document.getElementById('cfg-debug-mode');
    return el ? el.checked : false;
}

function renderBoldOnlyMarkdown(text) {
    const escaped = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    return escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
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
        showScreen(isDebugMode() ? 4 : 2, true);
    }
};

window.updateFrame = function(base64Image, statusText, isNormal, score, turtleAng, torsoAng, shoulderAng, pelvisAng, legCross, partScores) {
    if (currentIndex !== 4) return;

    if (base64Image) {
        latestCameraFrameSrc = 'data:image/jpeg;base64,' + base64Image;
        if (viewMode === 'camera') {
            renderCameraView(latestCameraFrameSrc);
        }
    }

    if (preCountdownActive) return;

    const statusBox = document.getElementById('status-box');

    if (typeof score !== 'undefined' && isNormal !== 2) {
        statusBox.innerText = `${statusText} (점수: ${score}점)`;
    } else {
        statusBox.innerText = statusText;
    }

    statusBox.className = "status-overlay";

    if (isNormal === 1 || isNormal === 0 || isNormal === -1) {
        let statusClass = "status-normal";
        if (isNormal === 0) statusClass = "status-warning";
        if (isNormal === -1) statusClass = "status-danger";
        statusBox.classList.add(statusClass);

        if (!sittingConfirmed) {
            sittingConfirmed = true;
            isPaused = false;
        }

        if (sittingConfirmed) {
            isPaused = false;
            if (typeof score === 'number') {
                collectedMetrics.scores.push(score);
                if (worstScoreValue === null || score < worstScoreValue) {
                    worstScoreValue = score;
                    worstScorePhotoSrc = latestCameraFrameSrc;
                }
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
    }
};

function resetToInitialSetup() {
    clearTimeout(cameraLoadingTimeout);
    cameraLoadingTimeout = null;

    clearInterval(countdownInterval);
    countdownInterval = null;

    clearInterval(preCountdownInterval);
    preCountdownInterval = null;
    preCountdownActive = false;
    hidePreCountdownOverlay();

    clearInterval(privacyPollInterval);
    privacyPollInterval = null;

    clearTimeout(reportLoadingTimeout);
    reportLoadingTimeout = null;

    clearInterval(typingInterval);
    typingInterval = null;

    timeLeft = 40;
    isPaused = true;
    sittingConfirmed = false;
    captureLoopStarted = false;
    currentUuid = "";

    collectedMetrics = { scores: [], turtle: [], torso: [], shoulder: [], pelvis: [], legCross: [] };
    finalReportData = { score: 0, turtle: 0, torso: 0, shoulder: 0, pelvis: 0, legCrossSeconds: 0 };
    worstScoreValue = null;
    worstScorePhotoSrc = null;
    generatedLLMAdvice = "";

    backendApi.stop_capture();

    showScreen(0, false);
}

window.addEventListener('keydown', (e) => {
    if (e.ctrlKey) {
        if (e.key === 'ArrowRight') {
            e.preventDefault();
            let nextIndex = currentIndex + 1;
            while ([0, 1, 5].includes(nextIndex)) nextIndex++;
            showScreen(nextIndex, false);
        } else if (e.key === 'ArrowLeft') {
            e.preventDefault();
            let previousIndex = currentIndex - 1;
            while ([0, 1, 5].includes(previousIndex)) previousIndex--;
            showScreen(previousIndex, false);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            resetToInitialSetup();
        }
    } else if (currentIndex === 4 && viewMode !== 'camera' && !preCountdownActive) {
        if (e.key === 'ArrowRight') {
            e.preventDefault();
            goToNextShort();
        } else if (e.key === 'ArrowLeft') {
            e.preventDefault();
            goToPrevShort();
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

function showPreCountdownOverlay(value) {
    const overlay = document.getElementById('pre-countdown-overlay');
    if (!overlay) return;
    overlay.innerText = String(value);
    overlay.classList.add('active');
}

function hidePreCountdownOverlay() {
    const overlay = document.getElementById('pre-countdown-overlay');
    if (!overlay) return;
    overlay.classList.remove('active');
}

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
        if (shortsPlayerReady && shortsPlayer) {
            try { shortsPlayer.pauseVideo(); } catch (e) {}
        }
    } else if (shortsPlayerReady && shortsPlayer) {
        try { shortsPlayer.playVideo(); } catch (e) {}
    }
}

document.getElementById('btn-toggle-view').addEventListener('click', () => {
    setViewMode(viewMode === 'shorts' ? 'camera' : 'shorts');
});

document.getElementById('viewfinder-wrapper').addEventListener('click', (e) => {
    if (currentIndex !== 4) return;
    if (viewMode === 'camera') return;
    if (preCountdownActive) return;
    if (e.target.closest('#btn-toggle-view, #btn-prev-short, #btn-next-short')) return;
    if (!shortsPlayerReady || !shortsPlayer) return;

    const state = shortsPlayer.getPlayerState();
    if (state === YT.PlayerState.PLAYING) {
        try { shortsPlayer.pauseVideo(); } catch (e) {}
    } else {
        try { shortsPlayer.playVideo(); } catch (e) {}
    }
});