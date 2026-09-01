const screens = document.querySelectorAll('.screen');
let currentIndex = 0;
let countdownInterval = null;
let privacyPollInterval = null;
let reportLoadingTimeout = null;
let typingInterval = null;

let timeLeft = 30;
let isPaused = false;

let debugModeEnabled = false;
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
    metricSources: { neck: [], torso: [], shoulder: [], pelvis: [] },
    legCross: []
};

let finalReportData = {
    score: 0,
    turtle: 0,
    torso: 0,
    shoulder: 0,
    pelvis: 0,
    metricSources: { neck: "threshold", torso: "threshold", shoulder: "threshold", pelvis: "threshold" },
    legCrossSeconds: 0
};

let generatedLLMAdvice = "";

const SUPABASE_URL = "https://orehrskvecfrfqxdhfur.supabase.co";

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
        if (window.pywebview) window.pywebview.api.toggle_camera(false);
        hideReelsIframe();
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

        // Safety fallback: if the backend never reports the camera as ready
        // (e.g. hardware issue), don't leave the user stuck on this screen forever.
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

        const qrUrl = `https://pose-report.netlify.app/#${currentUuid}`;

        try {
            const qrContainer = document.getElementById("qrcode-privacy");
            qrContainer.innerHTML = "";
            new QRCode(qrContainer, { text: qrUrl, width: 260, height: 260 });
        } catch (qrErr) { }

        const targetUrl = `${SUPABASE_URL}/rest/v1/main?uuid=eq.${currentUuid}&select=*`;
        clearInterval(privacyPollInterval);

        privacyPollInterval = setInterval(() => {
            if (window.pywebview?.api?.get_supabase_key) {
                window.pywebview.api.get_supabase_key().then(anonKey => {
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
        if (window.pywebview) window.pywebview.api.toggle_camera(true);

        collectedMetrics = { scores: [], turtle: [], torso: [], shoulder: [], pelvis: [], metricSources: { neck: [], torso: [], shoulder: [], pelvis: [] }, legCross: [] };

        timeLeft = 30;
        // The 30s timer stays paused until the user's sitting posture is
        // confirmed and the 3-second pre-countdown finishes (see updateFrame).
        isPaused = true;
        sittingConfirmed = false;
        hidePreCountdown();

        const statusBoxEl = document.getElementById('status-box');
        if (statusBoxEl) statusBoxEl.classList.remove('hidden');
        hideReelsIframe();

        const timerEl = document.getElementById('timer');
        timerEl.innerText = "30";

        clearInterval(countdownInterval);
        countdownInterval = setInterval(() => {
            if (isPaused) return;

            timeLeft--;
            timerEl.innerText = String(timeLeft).padStart(2, '0');

            if (timeLeft <= 0) {
                clearInterval(countdownInterval);

                hideReelsIframe();

                const calcAvg = arr => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
                const dominantSource = arr => {
                    if (!arr || !arr.length) return "threshold";
                    const mlCount = arr.filter(v => v === "ml").length;
                    return mlCount >= arr.length / 2 ? "ml" : "threshold";
                };
                const legCrossRatio = calcAvg(collectedMetrics.legCross);
                finalReportData = {
                    score: Math.round(calcAvg(collectedMetrics.scores)),
                    turtle: parseFloat(calcAvg(collectedMetrics.turtle).toFixed(1)),
                    torso: parseFloat(calcAvg(collectedMetrics.torso).toFixed(1)),
                    shoulder: parseFloat(calcAvg(collectedMetrics.shoulder).toFixed(1)),
                    pelvis: parseFloat(calcAvg(collectedMetrics.pelvis).toFixed(1)),
                    metricSources: {
                        neck: dominantSource(collectedMetrics.metricSources.neck),
                        torso: dominantSource(collectedMetrics.metricSources.torso),
                        shoulder: dominantSource(collectedMetrics.metricSources.shoulder),
                        pelvis: dominantSource(collectedMetrics.metricSources.pelvis)
                    },
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
                if (window.pywebview?.api?.generate_llm_advice) {
                    generatedLLMAdvice = await window.pywebview.api.generate_llm_advice(finalReportData);
                } else {
                    generatedLLMAdvice = "백엔드 API 연결 실패로 인해 AI 피드백을 불러올 수 없습니다.";
                }
            } catch (e) {
                generatedLLMAdvice = "AI 피드백을 생성하는 중 오류가 발생했습니다.";
            }
            // NOTE: the measurement result is intentionally never uploaded to
            // Supabase. The report is only ever shown locally and printed
            // (see screen 6 / btn-print), never persisted to the DB.
            showScreen(6, true);
        })();
    }

    if (currentIndex === 6) {
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

        const metricSourceLabel = source => source === "ml" ? "ML" : "Threshold";
        const setMetricUI = (valId, barId, value, goodText, warnText, source) => {
            const valEl = document.getElementById(valId);
            const barEl = document.getElementById(barId);
            const numeric = Math.max(0, Math.min(100, Number(value) || 0));
            const isGood = numeric >= 90;
            if (valEl) {
                valEl.innerText = `${Math.round(numeric)}점 · ${isGood ? goodText : warnText} · ${metricSourceLabel(source)}`;
                valEl.className = `metric-value ${isGood ? 'status-good' : 'status-warning'}`;
            }
            if (barEl) {
                barEl.className = `progress-bar-fill ${isGood ? 'fill-good' : 'fill-warning'}`;
                return { el: barEl, width: numeric + '%' };
            }
            return null;
        };

        const barTargets = [
            setMetricUI('val-turtle', 'bar-turtle', finalReportData.turtle, '양호', '주의', finalReportData.metricSources?.neck),
            setMetricUI('val-torso', 'bar-torso', finalReportData.torso, '안정', '주의', finalReportData.metricSources?.torso),
            setMetricUI('val-shoulder', 'bar-shoulder', finalReportData.shoulder, '정상', '주의', finalReportData.metricSources?.shoulder),
            setMetricUI('val-pelvis', 'bar-pelvis', finalReportData.pelvis, '정상', '주의', finalReportData.metricSources?.pelvis)
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
    const debugGroup = document.getElementById('cfg-debug-group');

    if (camGroup) camGroup.style.display = isAstra ? 'none' : '';
    if (debugCamGroup) debugCamGroup.style.display = isAstra ? '' : 'none';
    if (debugGroup) debugGroup.style.display = isAstra ? '' : 'none';

    if (!isAstra) {
        const debugCb = document.getElementById('cfg-debug');
        if (debugCb) debugCb.checked = false;
    }
}

document.getElementById('cfg-camera-source').addEventListener('change', syncCameraFieldsVisibility);
document.getElementById('cfg-debug').addEventListener('change', syncCameraFieldsVisibility);
syncCameraFieldsVisibility();

function startCaptureLoop() {
    const cameraSource = document.getElementById('cfg-camera-source').value;
    debugModeEnabled = cameraSource === 'astra' && document.getElementById('cfg-debug').checked;

    if (window.pywebview?.api) {
        window.pywebview.api.setup_and_start(
            document.getElementById('cfg-turtle').value,
            document.getElementById('cfg-torso').value,
            document.getElementById('cfg-shoulder').value,
            document.getElementById('cfg-pelvis').value,
            document.getElementById('cfg-head').value,
            document.getElementById('cfg-spine').value,

            cameraSource === 'astra' ? "" : document.getElementById('cfg-cam').value,
            cameraSource,
            debugModeEnabled,
            document.getElementById('cfg-debug-cam').value,

            document.getElementById('cfg-weight-neck').value,
            document.getElementById('cfg-weight-trunk').value,
            document.getElementById('cfg-weight-shoulder').value,
            document.getElementById('cfg-weight-pelvis').value,
            document.getElementById('cfg-weight-leg-cross').value
        );
    }
}

document.getElementById('btn-save').addEventListener('click', () => {
    showScreen(1, false);
});

document.getElementById('btn-start').addEventListener('click', () => showScreen(3, true));
document.getElementById('btn-restart').addEventListener('click', () => showScreen(2, true));

document.getElementById('btn-instagram-login').addEventListener('click', () => {
    if (window.pywebview?.api?.open_instagram_login) {
        window.pywebview.api.open_instagram_login();
    }
});

document.getElementById('btn-print').addEventListener('click', () => {
    window.print();
});

// Called from the Python backend once the (webcam or Astra) camera has
// delivered its first frame, i.e. the 3D camera load triggered on the
// loading screen has finished. Auto-advance to the main screen.
window.onCameraReady = function () {
    if (currentIndex === 1) {
        clearTimeout(cameraLoadingTimeout);
        showScreen(2, true);
    }
};

// 인스타그램이 X-Frame-Options/CSP frame-ancestors로 <iframe> 삽입을 차단하기
// 때문에, 릴스는 더 이상 iframe으로 로드하지 않는다. 대신 reels-overlay div가
// 화면에서 차지하는 자리(위치/크기)를 계산해서 파이썬(main.py)에 넘기면,
// 그 자리 위에 겹쳐지는 별도의 pywebview 네이티브 창으로 릴스를 띄운다.
// (X-Frame-Options는 "iframe 삽입"만 막을 뿐, 최상위 문서로 직접 여는 것은
// 막지 않기 때문에 이 방식은 차단되지 않는다.)

function showReelsIframe() {
    const overlay = document.getElementById('reels-overlay');
    if (!overlay) return;

    overlay.classList.remove('hidden');

    const rect = overlay.getBoundingClientRect();
    if (window.pywebview?.api?.open_reels_overlay) {
        window.pywebview.api.open_reels_overlay(rect.left, rect.top, rect.width, rect.height);
    }
}

function hideReelsIframe(muteOnly = false) {
    const overlay = document.getElementById('reels-overlay');
    if (!overlay) return;

    overlay.classList.add('hidden');

    if (window.pywebview?.api?.hide_reels_overlay) {
        window.pywebview.api.hide_reels_overlay(muteOnly);
    }
}

function hidePreCountdown() {
    clearTimeout(preCountdownTimeout);
    preCountdownTimeout = null;
    const overlay = document.getElementById('precountdown-overlay');
    if (overlay) overlay.classList.remove('active');
}

function restartPreCountdownAnimation(numberEl) {
    numberEl.style.animation = 'none';
    void numberEl.offsetWidth; // force reflow to restart the CSS animation
    numberEl.style.animation = '';
}

// Runs a 3-2-1 on-screen countdown after the user's seated posture is first
// confirmed, and only resumes the 30s measurement timer once it completes.
function startPreCountdown() {
    const overlay = document.getElementById('precountdown-overlay');
    const numberEl = document.getElementById('precountdown-number');
    if (!overlay || !numberEl) {
        // Fallback: no overlay available, just start immediately.
        sittingConfirmed = true;
        isPaused = false;
        showReelsIframe();
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
            showReelsIframe();
            return;
        }
        numberEl.textContent = String(count);
        restartPreCountdownAnimation(numberEl);
        preCountdownTimeout = setTimeout(tick, 1000);
    };
    preCountdownTimeout = setTimeout(tick, 1000);
}

window.updateFrame = function(base64Image, statusText, isNormal, score, turtleAng, torsoAng, shoulderAng, pelvisAng, legCross, mlScores, metricSources) {
    if (currentIndex !== 4) return;

    document.getElementById('viewfinder').src = 'data:image/jpeg;base64,' + base64Image;

    const statusBox = document.getElementById('status-box');

    if (isNormal === 1 || isNormal === 0) {
        // Person detected and seated: hide the status box entirely so the
        // person isn't tempted to "perform" a correct posture, and let the
        // 3-2-1 countdown / Instagram Reels screen take over instead.
        statusBox.classList.add('hidden');

        // Seated posture just became detected: run the 3-second pre-countdown
        // before the 30s measurement timer is allowed to run.
        if (!sittingConfirmed && preCountdownTimeout === null) {
            isPaused = true;
            startPreCountdown();
        }

        if (sittingConfirmed) {
            isPaused = false;
            if (typeof score === 'number') {
                collectedMetrics.scores.push(score);
                const scores = mlScores || {};
                collectedMetrics.turtle.push(typeof scores.neck === "number" ? scores.neck : (turtleAng || 0));
                collectedMetrics.torso.push(typeof scores.torso === "number" ? scores.torso : (torsoAng || 0));
                collectedMetrics.shoulder.push(typeof scores.shoulder === "number" ? scores.shoulder : (shoulderAng || 0));
                collectedMetrics.pelvis.push(typeof scores.pelvis === "number" ? scores.pelvis : (pelvisAng || 0));
                const sources = metricSources || {};
                collectedMetrics.metricSources.neck.push(sources.neck || "threshold");
                collectedMetrics.metricSources.torso.push(sources.torso || "threshold");
                collectedMetrics.metricSources.shoulder.push(sources.shoulder || "threshold");
                collectedMetrics.metricSources.pelvis.push(sources.pelvis || "threshold");
                collectedMetrics.legCross.push(legCross ? 1 : 0);
            }
        }
    } else {
        // isNormal === 2: no person recognized at all.
        // isNormal === 3: a person is recognized but not seated yet.
        statusBox.classList.remove('hidden');
        statusBox.innerText = statusText;
        statusBox.className = "status-overlay";
        statusBox.classList.add(isNormal === 3 ? "status-not-seated" : "status-unknown");

        const wasSittingConfirmed = sittingConfirmed;
        isPaused = true;
        sittingConfirmed = false;
        hidePreCountdown();

        // The person stood up / left mid-measurement: briefly hide + mute
        // the Reels iframe (without discarding it) so the status box is
        // visible again and nothing keeps playing in the background. It
        // resumes right where it left off once the person is seated again.
        if (wasSittingConfirmed) {
            hideReelsIframe(true);
        }
    }
};

window.updateDebugFrame = function(base64Image) {
    if (currentIndex !== 4) return;
    const debugImg = document.getElementById('debug-viewfinder');
    if (debugImg) debugImg.src = 'data:image/jpeg;base64,' + base64Image;
};

window.addEventListener('keydown', (e) => {
    if (e.ctrlKey) {
        if (e.key === 'ArrowRight') {
            e.preventDefault();
            showScreen(currentIndex + 1, false);
        } else if (e.key === 'ArrowLeft') {
            e.preventDefault();
            showScreen(currentIndex - 1, false);
        }
    }
    if (e.key === 'F11') {
        e.preventDefault();
        if (window.pywebview) window.pywebview.api.toggle_fullscreen();
    }
    if (e.key === 'Escape') {
        e.preventDefault();
        if (window.pywebview) window.pywebview.api.close_window();
    }
});