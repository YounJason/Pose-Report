const screens = document.querySelectorAll('.screen');
let currentIndex = 0;
let countdownInterval = null;
let privacyPollInterval = null;
const SUPABASE_URL = "https://orehrskvecfrfqxdhfur.supabase.co";

function initScreens() {
    screens.forEach((screen, idx) => {
        if (idx === 0) screen.removeAttribute('style');
        screen.classList.toggle('active', idx === currentIndex);
    });

    if (typeof QRCode !== 'undefined') {
        new QRCode(document.getElementById("qrcode-download"), {
            text: "example",
            width: 200,
            height: 200
        });
    }
}
initScreens();

function showScreen(index, useFade = true) {
    if (index < 0 || index >= screens.length) return;

    if (currentIndex === 3) {
        clearInterval(countdownInterval);
        if (window.pywebview) window.pywebview.api.toggle_camera(false);
    }

    if (currentIndex === 2) clearInterval(privacyPollInterval);

    screens.forEach(screen => screen.classList.toggle('fade-effect', useFade));
    screens[currentIndex].classList.remove('active');
    currentIndex = index;
    screens[currentIndex].classList.add('active');

    if (currentIndex === 2) startPrivacyConsentWorkflow();
    if (currentIndex === 3) startCaptureSession();
}

function startPrivacyConsentWorkflow() {
    const randomStr = Math.random().toString(36).substring(2, 9);
    const qrUrl = `https://pose-report.netlify.app/#${randomStr}`;

    try {
        const qrContainer = document.getElementById("qrcode-privacy");
        qrContainer.innerHTML = "";
        new QRCode(qrContainer, { text: qrUrl, width: 260, height: 260 });
    } catch (qrErr) { }

    const targetUrl = `${SUPABASE_URL}/rest/v1/privacy?id=eq.${randomStr}&select=*`;
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

document.getElementById('btn-save').addEventListener('click', () => {
    if (window.pywebview?.api) {
        window.pywebview.api.setup_and_start(
            document.getElementById('cfg-turtle').value,
            document.getElementById('cfg-torso').value,
            document.getElementById('cfg-shoulder').value,
            document.getElementById('cfg-pelvis').value,
            document.getElementById('cfg-head').value,
            document.getElementById('cfg-spine').value,
            document.getElementById('cfg-cam').value
        );
    }
    showScreen(1, false);
});

document.getElementById('btn-start').addEventListener('click', () => showScreen(2, true));

function startCaptureSession() {
    if (window.pywebview) window.pywebview.api.toggle_camera(true);

    let timeLeft = 60;
    const timerEl = document.getElementById('timer');
    timerEl.innerText = "01:00";

    countdownInterval = setInterval(() => {
        timeLeft--;
        const mins = String(Math.floor(timeLeft / 60)).padStart(2, '0');
        const secs = String(timeLeft % 60).padStart(2, '0');
        timerEl.innerText = `${mins}:${secs}`;

        if (timeLeft <= 0) {
            clearInterval(countdownInterval);
            showScreen(4, true);
        }
    }, 1000);
}

function updateFrame(base64Image, statusText, isNormal) {
    if (currentIndex !== 3) return;

    document.getElementById('viewfinder').src = 'data:image/jpeg;base64,' + base64Image;

    const statusBox = document.getElementById('status-box');
    statusBox.innerText = statusText;
    statusBox.className = "status-overlay";

    if (isNormal === 1) statusBox.classList.add("status-normal");
    else if (isNormal === 0) statusBox.classList.add("status-warning");
    else statusBox.classList.add("status-unknown");
}

window.updateFrame = updateFrame;

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
});
