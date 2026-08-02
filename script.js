const screens = document.querySelectorAll('.screen');
let currentIndex = 0;
let countdownInterval = null;
let privacyPollInterval = null;
let reportLoadingTimeout = null;
let typingInterval = null;

let timeLeft = 60;
let isPaused = false; 

const SUPABASE_URL = "https://orehrskvecfrfqxdhfur.supabase.co";

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

function showScreen(index, useFade = true) {
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

if (currentIndex === 2) {
        const uuid = (typeof crypto !== 'undefined' && crypto.randomUUID) 
            ? crypto.randomUUID() 
            : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                const r = Math.random() * 16 | 0;
                const v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });

        const qrUrl = `https://pose-report.netlify.app/#${uuid}`;

        try {
            const qrContainer = document.getElementById("qrcode-privacy");
            qrContainer.innerHTML = "";
            new QRCode(qrContainer, { text: qrUrl, width: 260, height: 260 });
        } catch (qrErr) { }

        const targetUrl = `${SUPABASE_URL}/rest/v1/privacy?id=eq.${uuid}&select=*`;
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
                showScreen(4, true);
            }
        }, 1000);
    }

    if (currentIndex === 4) {
        const helptext = document.querySelector('.help-text');
        const messages = [
            "측정 결과를 분석하는 중...",
            "LLM으로 리포트를 생성하는 중...",
            "리포트 생성을 마무리 하는 중..."
        ];
        let msgIndex = 0;
        const displayMessage = () => {
            if (msgIndex < messages.length) {
                helptext.innerText = messages[msgIndex];
                msgIndex++;
                setTimeout(displayMessage, 1000);
            }
        };
        displayMessage();
        reportLoadingTimeout = setTimeout(() => showScreen(5, true), 3000);
    }

    if (currentIndex === 5) {
        document.querySelectorAll('.progress-bar-fill').forEach(bar => bar.style.width = '0%');
        const scoreRing = document.getElementById('score-ring-progress');
        if (scoreRing) scoreRing.style.strokeDashoffset = '314';
        clearInterval(typingInterval);
        const adviceEl = document.getElementById('llm-advice');
        if (adviceEl) adviceEl.innerText = '';

        const fadeDelay = useFade ? 800 : 50;
        setTimeout(() => {
            const barTargets = [
                { id: 'bar-turtle', targetWidth: '85%' },
                { id: 'bar-torso', targetWidth: '80%' },
                { id: 'bar-shoulder', targetWidth: '55%' },
                { id: 'bar-pelvis', targetWidth: '90%' }
            ];

            barTargets.forEach(item => {
                const el = document.getElementById(item.id);
                if (el) el.style.width = item.targetWidth;
            });

            if (scoreRing) {
                const targetScore = 85;
                const circumference = 314;
                const offset = circumference * (1 - targetScore / 100);
                scoreRing.style.strokeDashoffset = offset;
            }

            const Advice = `텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트텍스트`;
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
                }, 10);
            }
        }, fadeDelay);
    }
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
document.getElementById('btn-restart').addEventListener('click', () => showScreen(1, true));

window.updateFrame = function(base64Image, statusText, isNormal) {
    if (currentIndex !== 3) return;

    document.getElementById('viewfinder').src = 'data:image/jpeg;base64,' + base64Image;

    const statusBox = document.getElementById('status-box');
    statusBox.innerText = statusText;
    statusBox.className = "status-overlay";

    if (isNormal === 1) {
        statusBox.classList.add("status-normal");
        isPaused = false;
    } else if (isNormal === 0) {
        statusBox.classList.add("status-warning");
        isPaused = false;
    } else {
        statusBox.classList.add("status-unknown");
        isPaused = true;
    }
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
})