const screens = document.querySelectorAll('.screen');
let currentIndex = 0;
let countdownInterval = null;
let privacyPollInterval = null;
let reportLoadingTimeout = null;
let typingInterval = null;

let timeLeft = 60;
let isPaused = false;

let debugModeEnabled = false;
let captureLoopStarted = false;

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

screens.forEach((screen, idx) => {
    if (idx === 0) screen.removeAttribute('style');
    screen.classList.toggle('active', idx === currentIndex);
});

const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

async function showScreen(index, useFade = true) {
    if (index < 0 || index >= screens.length) return;

    if (currentIndex === 3) {
        clearInterval(countdownInterval);
        if (window.pywebview) window.pywebview.api.toggle_camera(false);
    }

    if (currentIndex === 2) clearInterval(privacyPollInterval);
    clearTimeout(reportLoadingTimeout);

    if (currentIndex === 5) {
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

    if (currentIndex === 1 && !captureLoopStarted) {
        captureLoopStarted = true;
        startCaptureLoop();
    }

    if (currentIndex === 2) {
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
                            showScreen(3, true);
                        }
                    })
                    .catch(() => {});
                }).catch(() => {});
            }
        }, 1000);
    }

    if (currentIndex === 3) {
        if (window.pywebview) window.pywebview.api.toggle_camera(true);

        collectedMetrics = { scores: [], turtle: [], torso: [], shoulder: [], pelvis: [], legCross: [] };

        timeLeft = 60;
        isPaused = false;
        const timerEl = document.getElementById('timer');
        timerEl.innerText = "60";

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
                    legCrossSeconds: parseFloat((legCrossRatio * 60).toFixed(1))
                };

                showScreen(4, true);
            }
        }, 1000);
    }

    if (currentIndex === 4) {
        const helptext = document.querySelector('.help-text');

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
            helptext.innerText = "리포트를 업로드 하는 중...";
            try {
                if (window.pywebview?.api?.get_supabase_key && currentUuid) {
                    const anonKey = await window.pywebview.api.get_supabase_key();
                    const updateUrl = `${SUPABASE_URL}/rest/v1/main?uuid=eq.${currentUuid}`;

                    const thresholds = {
                        turtle: parseFloat(document.getElementById('cfg-turtle').value) || 18.0,
                        torso: parseFloat(document.getElementById('cfg-torso').value) || 28.0,
                        shoulder: parseFloat(document.getElementById('cfg-shoulder').value) || 8.0,
                        pelvis: parseFloat(document.getElementById('cfg-pelvis').value) || 7.0,
                        head: parseFloat(document.getElementById('cfg-head').value) || 5.0,
                        spine: parseFloat(document.getElementById('cfg-spine').value) || 8.0
                    };

                    const payload = {
                        result: {
                            metrics: finalReportData,
                            advice: generatedLLMAdvice,
                            thresholds
                        }
                    };

                    await fetch(updateUrl, {
                        method: 'PATCH',
                        headers: {
                            'apikey': anonKey,
                            'Authorization': `Bearer ${anonKey}`,
                            'Content-Type': 'application/json',
                            'Prefer': 'return=minimal'
                        },
                        body: JSON.stringify(payload)
                    });
                }
            } catch (err) {
                console.error(err);
            }
            showScreen(5, true);
        })();
    }

    if (currentIndex === 5) {
        try {
            const qrDownloadContainer = document.getElementById("qrcode-download");
            if (qrDownloadContainer) {
                qrDownloadContainer.innerHTML = "";
                const resultQrUrl = `https://pose-report.netlify.app/result/#${currentUuid}`;
                new QRCode(qrDownloadContainer, {
                    text: resultQrUrl,
                    width: 200,
                    height: 200
                });
            }
        } catch (err) {
            console.error(err);
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

        const cfgTurtle = parseFloat(document.getElementById('cfg-turtle').value) || 18.0;
        const cfgTorso = parseFloat(document.getElementById('cfg-torso').value) || 28.0;
        const cfgShoulder = parseFloat(document.getElementById('cfg-shoulder').value) || 8.0;
        const cfgPelvis = parseFloat(document.getElementById('cfg-pelvis').value) || 7.0;

        const setMetricUI = (valId, barId, value, threshold, goodText, warnText) => {
            const valEl = document.getElementById(valId);
            const isGood = value <= threshold;
            if (valEl) {
                valEl.innerText = `${isGood ? goodText : warnText} (${value}°)`;
                valEl.className = `metric-value ${isGood ? 'status-good' : 'status-warning'}`;
            }

            const barRatio = Math.max(10, Math.min(100, Math.round(100 - (value / (threshold * 2)) * 100)));
            const barEl = document.getElementById(barId);
            if (barEl) {
                barEl.className = `progress-bar-fill ${isGood ? 'fill-good' : 'fill-warning'}`;
                return { el: barEl, width: barRatio + '%' };
            }
            return null;
        };

        const barTargets = [
            setMetricUI('val-turtle', 'bar-turtle', finalReportData.turtle, cfgTurtle, '양호', '위험'),
            setMetricUI('val-torso', 'bar-torso', finalReportData.torso, cfgTorso, '안정', '위험'),
            setMetricUI('val-shoulder', 'bar-shoulder', finalReportData.shoulder, cfgShoulder, '정상', '주의'),
            setMetricUI('val-pelvis', 'bar-pelvis', finalReportData.pelvis, cfgPelvis, '정상', '주의')
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
            document.getElementById('cfg-debug-cam').value
        );
    }
}

document.getElementById('btn-save').addEventListener('click', () => {
    showScreen(1, false);
});

document.getElementById('btn-start').addEventListener('click', () => showScreen(2, true));
document.getElementById('btn-restart').addEventListener('click', () => showScreen(1, true));

window.updateFrame = function(base64Image, statusText, isNormal, score, turtleAng, torsoAng, shoulderAng, pelvisAng, legCross) {
    if (currentIndex !== 3) return;

    document.getElementById('viewfinder').src = 'data:image/jpeg;base64,' + base64Image;

    const statusBox = document.getElementById('status-box');

    if (typeof score !== 'undefined' && isNormal !== 2) {
        statusBox.innerText = `${statusText} (점수: ${score}점)`;
    } else {
        statusBox.innerText = statusText;
    }

    statusBox.className = "status-overlay";

    if (isNormal === 1 || isNormal === 0) {
        statusBox.classList.add(isNormal === 1 ? "status-normal" : "status-warning");
        isPaused = false;
        if (typeof score === 'number') {
            collectedMetrics.scores.push(score);
            collectedMetrics.turtle.push(turtleAng || 0);
            collectedMetrics.torso.push(torsoAng || 0);
            collectedMetrics.shoulder.push(shoulderAng || 0);
            collectedMetrics.pelvis.push(pelvisAng || 0);
            collectedMetrics.legCross.push(legCross ? 1 : 0);
        }
    } else {
        statusBox.classList.add("status-unknown");
        isPaused = true;
    }
};

window.updateDebugFrame = function(base64Image) {
    if (currentIndex !== 3) return;
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