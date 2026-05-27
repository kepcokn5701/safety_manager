/**
 * KEPCO 현장안전 - 작업자용 앱 JS
 */

const API_BASE = '';
let siteId = null;
let pushSubscription = null;

// ── API 호출 ──
async function api(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || '요청 실패');
    }
    return res.json();
}

// ── 초기화 ──
document.addEventListener('DOMContentLoaded', () => {
    // URL에서 site_id 추출: /worker/3 → 3
    const match = window.location.pathname.match(/\/worker\/(\d+)/);
    if (match) {
        siteId = parseInt(match[1]);
        // 다음 접속을 위해 저장
        localStorage.setItem('worker_site_id', siteId);
    } else {
        // URL에 site_id 없으면 저장된 값 사용
        const saved = localStorage.getItem('worker_site_id');
        if (saved) {
            siteId = parseInt(saved);
        } else {
            document.getElementById('alert-banner').innerHTML = `
                <div class="alert-content"><h2>현장 정보가 없습니다</h2><p>관리자에게 QR코드를 받아 다시 접속해주세요</p></div>`;
            return;
        }
    }
    loadWeather();
    initServiceWorker();

    // 60초마다 자동 갱신
    setInterval(loadWeather, 60000);
});

// ── 날씨 조회 ──
async function loadWeather() {
    try {
        const data = await api(`/api/weather/status/${siteId}`);
        renderWeather(data);
    } catch (e) {
        console.error('날씨 조회 실패:', e);
    }
}

function renderWeather(data) {
    const { weather, stage, wbgt_work_recommendation, work_site_name, checked_at } = data;

    // 헤더 타이틀
    document.getElementById('header-title').textContent = work_site_name || 'KEPCO 현장안전';

    // 조회 시간
    const timeEl = document.getElementById('checked-time');
    if (checked_at) {
        timeEl.textContent = new Date(checked_at).toLocaleString('ko-KR', { hour:'2-digit', minute:'2-digit' }) + ' 기준';
    }

    // 경보 배너
    renderBanner(stage, weather, work_site_name);

    // 단계 바
    const lvl = !stage ? 0 : stage.stage_key === 'stage_1_interest' ? 1 : stage.stage_key === 'stage_2_caution' ? 2 : stage.stage_key === 'stage_3_warning' ? 3 : 4;
    const segs = document.querySelectorAll('.stage-seg');
    segs.forEach((seg, i) => {
        seg.classList.toggle('active', i < lvl);
    });

    // 날씨 수치
    const isHot = weather.apparent_temperature >= 33;
    document.getElementById('weather-content').innerHTML = `
        <div class="metric-grid">
            <div class="metric ${isHot ? 'highlight' : ''}">
                <div class="label">체감온도</div>
                <div class="value">${weather.apparent_temperature}<span class="unit">°</span></div>
            </div>
            <div class="metric">
                <div class="label">기온</div>
                <div class="value">${weather.temperature}<span class="unit">°</span></div>
            </div>
            <div class="metric">
                <div class="label">습도</div>
                <div class="value">${weather.humidity}<span class="unit">%</span></div>
            </div>
        </div>
        <div style="display:flex;gap:8px">
            <div class="metric" style="flex:1">
                <div class="label">풍속</div>
                <div class="value" style="font-size:18px">${weather.wind_speed}<span class="unit"> m/s</span></div>
            </div>
            <div class="metric" style="flex:2">
                <div class="label">WBGT 추정</div>
                <div class="value" style="font-size:18px">${weather.wbgt_estimated}<span class="unit">°C</span></div>
                <div style="font-size:11px;color:#0066cc;margin-top:2px">${wbgt_work_recommendation || ''}</div>
            </div>
        </div>`;

    // 조치사항
    const actEl = document.getElementById('actions-content');
    if (stage) {
        actEl.innerHTML = `
            <ul class="action-list">
                ${stage.actions.map(a => `<li>${a}</li>`).join('')}
            </ul>
            <div class="rest-badge"><strong>휴식:</strong> ${stage.rest_guideline}</div>`;
    } else {
        actEl.innerHTML = '<p style="text-align:center;color:#8896a6;padding:20px">특별 조치사항 없음</p>';
    }

    // 하단 현장 정보 + 알림 상태
    const pushStatus = pushSubscription ? '알림 ON' : '알림 OFF';
    const pwaMode = isPWA() ? 'PWA' : '브라우저';
    const notifPerm = typeof Notification !== 'undefined' ? Notification.permission : '미지원';
    const pushApi = 'PushManager' in window ? 'O' : 'X';
    document.getElementById('site-info').innerHTML = `${work_site_name} | ${pushStatus} | ${pwaMode} 모드<br><span style="font-size:10px;color:#b0bec5">알림권한:${notifPerm} | PushAPI:${pushApi}</span>`;
}

function renderBanner(stage, weather, siteName) {
    const banner = document.getElementById('alert-banner');
    const classMap = { 'stage_1_interest': 'interest', 'stage_2_caution': 'caution', 'stage_3_warning': 'warning', 'stage_4_danger': 'danger' };
    const iconMap = {
        'stage_1_interest': '/static/icons/alert-interest.svg',
        'stage_2_caution': '/static/icons/alert-caution.svg',
        'stage_3_warning': '/static/icons/alert-warning.svg',
        'stage_4_danger': '/static/icons/alert-danger.svg',
    };

    if (!stage) {
        banner.className = 'alert-banner safe';
        banner.innerHTML = `<div class="alert-content"><h2>정상 - 안전 작업 가능</h2><p>${siteName} | 체감 ${weather.apparent_temperature}°C</p></div>`;
        return;
    }

    banner.className = `alert-banner ${classMap[stage.stage_key] || 'safe'}`;
    banner.innerHTML = `
        <img class="icon" src="${iconMap[stage.stage_key] || '/static/icons/icon-192.svg'}" alt="">
        <div class="alert-content">
            <h2>폭염 ${stage.stage_name} 단계</h2>
            <p>${siteName} | 체감 ${weather.apparent_temperature}°C | ${stage.work_restriction}</p>
        </div>`;
}

// ── Service Worker & 푸시 ──
async function initServiceWorker() {
    if (!('serviceWorker' in navigator)) return;

    try {
        const reg = await navigator.serviceWorker.register('/sw.js');

        // 기존 구독 확인
        const sub = await reg.pushManager.getSubscription();
        if (sub) {
            pushSubscription = sub;
            updatePushButton(true);
            api('/api/push/subscribe', {
                method: 'POST',
                body: JSON.stringify({
                    subscription: sub.toJSON(),
                    subscriber_type: 'worker',
                    site_id: siteId,
                }),
            }).catch(() => {});
        }

        // 모바일 + PWA 미설치 → 설치 배너
        if (isMobile() && !isPWA() && !sessionStorage.getItem('install-dismissed')) {
            const banner = document.getElementById('install-banner');
            if (banner) banner.style.display = 'block';
        }

        // SW 메시지 수신 → 인앱 알림
        navigator.serviceWorker.addEventListener('message', (event) => {
            if (event.data?.type === 'PUSH_RECEIVED') {
                showWorkerAlert(event.data);
            } else if (event.data?.type === 'NOTICE') {
                showNoticePopup(event.data);
            }
        });
    } catch (e) {
        console.error('SW 등록 실패:', e);
    }
}

function isPWA() { return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true; }
function isIOS() { return /iphone|ipad|ipod/i.test(navigator.userAgent); }
function isAndroid() { return /android/i.test(navigator.userAgent); }
function isMobile() { return isIOS() || isAndroid(); }

async function togglePush() {
    if (pushSubscription) {
        await unsubscribePush();
    } else {
        await subscribePush();
    }
}

async function subscribePush() {
    // 1) 브라우저 지원 확인
    if (!('serviceWorker' in navigator)) {
        showGuideModal('알림을 지원하지 않는 브라우저',
            'Chrome, Samsung Internet, Edge 브라우저로 접속해주세요.\n\n현재 브라우저: ' + navigator.userAgent.slice(0, 80));
        return;
    }

    if (!('PushManager' in window)) {
        if (isIOS()) {
            showGuideModal('iPhone 알림 설정 방법',
                !isPWA()
                    ? '① 하단 공유 버튼(□↑)을 터치\n② "홈 화면에 추가"를 터치\n③ 홈 화면에서 앱을 열기\n④ 다시 "알림 허용" 터치\n\n(iOS 16.4 이상 필요)'
                    : 'iOS 설정 > Safari > 고급 > Push API가 켜져있는지 확인하세요.\n\niOS 16.4 이상에서만 알림이 지원됩니다.\n현재 iOS 버전을 확인해주세요.');
        } else {
            showGuideModal('알림을 지원하지 않습니다',
                'Chrome 또는 Samsung Internet 최신 버전으로 업데이트해주세요.');
        }
        return;
    }

    // 2) iOS는 반드시 PWA 모드
    if (isIOS() && !isPWA()) {
        showGuideModal('먼저 홈 화면에 앱을 추가해주세요',
            '① Safari 하단 공유 버튼(□↑) 터치\n② "홈 화면에 추가" 터치\n③ 홈 화면에서 앱을 열기\n④ 다시 "알림 허용" 터치\n\n(반드시 Safari에서 추가해야 합니다)');
        return;
    }

    // 3) 알림 권한
    let permission = Notification.permission;
    if (permission === 'denied') {
        showGuideModal('알림이 차단된 상태입니다',
            isIOS()
                ? '① iPhone 설정 앱 열기\n② 현장안전 앱 찾기\n③ 알림 → 허용\n④ 앱으로 돌아와서 다시 시도'
                : isAndroid()
                    ? '① 주소창 왼쪽 자물쇠(🔒) 터치\n② "알림" → "허용"으로 변경\n③ 페이지 새로고침'
                    : '① 주소창 왼쪽 자물쇠 클릭\n② "알림" → "허용"으로 변경');
        return;
    }

    if (permission === 'default') {
        permission = await Notification.requestPermission();
        if (permission !== 'granted') {
            showGuideModal('알림을 허용해주세요',
                '방금 나타난 팝업에서 "허용"을 눌러야 합니다.\n\n팝업이 안 나타나면:\n'
                + (isAndroid() ? '주소창 왼쪽 자물쇠 → 알림 → 허용' : '브라우저 설정에서 알림을 허용해주세요.'));
            return;
        }
    }

    // 4) 푸시 구독
    try {
        const { public_key } = await api('/api/push/vapid-key');
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(public_key),
        });

        await api('/api/push/subscribe', {
            method: 'POST',
            body: JSON.stringify({
                subscription: sub.toJSON(),
                subscriber_type: 'worker',
                site_id: siteId,
            }),
        });

        pushSubscription = sub;
        updatePushButton(true);
        showGuideModal('알림 설정 완료', '폭염 경보 발생 시 알림을 받게 됩니다.\n앱을 닫아도 알림이 도착합니다.');
    } catch (e) {
        console.error('푸시 구독 실패:', e);
        showGuideModal('알림 설정 실패',
            `오류: ${e.message}\n\n다시 시도하거나, 브라우저를 최신 버전으로 업데이트해주세요.`);
    }
}

async function unsubscribePush() {
    try {
        if (pushSubscription) {
            const endpoint = pushSubscription.endpoint;
            await pushSubscription.unsubscribe();
            await api('/api/push/unsubscribe', { method: 'POST', body: JSON.stringify({ endpoint }) }).catch(() => {});
        }
        pushSubscription = null;
        updatePushButton(false);
    } catch (e) {
        console.error('구독 해제 실패:', e);
    }
}

function updatePushButton(active) {
    const btn = document.getElementById('push-btn');
    if (!btn) return;
    btn.className = active ? 'btn-notify active' : 'btn-notify';
    btn.textContent = active ? '알림 ON' : '알림 허용';
}

// ── 인앱 알림 ──
function showWorkerAlert(data) {
    // 경고음
    playAlertSound(data.stage);

    const old = document.getElementById('worker-alert-popup');
    if (old) old.remove();

    const stageColors = {
        '관심': { bg: '#FFF8E1', border: '#FFC107', text: '#F57F17' },
        '주의': { bg: '#FFF3E0', border: '#FF9800', text: '#E65100' },
        '경고': { bg: '#FBE9E7', border: '#FF5722', text: '#BF360C' },
        '위험': { bg: '#FFEBEE', border: '#D32F2F', text: '#B71C1C' },
    };
    const c = stageColors[data.stage] || stageColors['경고'];

    const popup = document.createElement('div');
    popup.id = 'worker-alert-popup';
    popup.style.cssText = `position:fixed;top:60px;left:12px;right:12px;z-index:10000;`;
    popup.innerHTML = `
        <div style="padding:16px;background:${c.bg};border:2px solid ${c.border};border-radius:14px;box-shadow:0 8px 24px rgba(0,0,0,0.15)">
            <div style="font-size:18px;font-weight:800;color:${c.text};margin-bottom:4px">${data.title}</div>
            <div style="font-size:14px;color:#333;line-height:1.5;white-space:pre-line">${data.body}</div>
            ${data.actions?.length ? `<div style="font-size:13px;color:${c.text};margin-top:8px">${data.actions[0]}</div>` : ''}
            <button onclick="this.closest('#worker-alert-popup').remove()" style="margin-top:10px;width:100%;padding:10px;background:${c.border};color:white;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer">확인</button>
        </div>`;
    document.body.appendChild(popup);

    // 데이터 갱신
    loadWeather();
}

function showNoticePopup(data) {
    playAlertSound('관심');

    const old = document.getElementById('worker-alert-popup');
    if (old) old.remove();

    const popup = document.createElement('div');
    popup.id = 'worker-alert-popup';
    popup.style.cssText = 'position:fixed;top:60px;left:12px;right:12px;z-index:10000;';
    popup.innerHTML = `
        <div style="padding:16px;background:#eff6ff;border:2px solid #3b82f6;border-radius:14px;box-shadow:0 8px 24px rgba(0,0,0,0.15)">
            <div style="font-size:11px;color:#3b82f6;font-weight:600;margin-bottom:4px">공지사항</div>
            <div style="font-size:17px;font-weight:800;color:#1e40af;margin-bottom:6px">${data.title}</div>
            <div style="font-size:14px;color:#333;line-height:1.6;white-space:pre-line">${data.body}</div>
            <button onclick="this.closest('#worker-alert-popup').remove()" style="margin-top:12px;width:100%;padding:10px;background:#3b82f6;color:white;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer">확인</button>
        </div>`;
    document.body.appendChild(popup);
}

function playAlertSound(stage) {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const isDanger = stage === '위험';
        const freqs = isDanger ? [880, 660, 880, 660, 880] : stage === '경고' ? [780, 580, 780] : [660, 520];
        const dur = isDanger ? 0.15 : 0.2;
        freqs.forEach((freq, i) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain); gain.connect(ctx.destination);
            osc.type = isDanger ? 'square' : 'sine';
            osc.frequency.value = freq;
            const start = ctx.currentTime + i * (dur + 0.08);
            gain.gain.setValueAtTime(0.35, start);
            gain.gain.exponentialRampToValueAtTime(0.01, start + dur);
            osc.start(start); osc.stop(start + dur);
        });
        setTimeout(() => ctx.close(), 3000);
    } catch (e) {}
}

// ── 유틸 ──
function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = window.atob(base64);
    const arr = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
    return arr;
}

function showGuideModal(title, message) {
    const old = document.querySelector('.guide-overlay');
    if (old) old.remove();
    const modal = document.createElement('div');
    modal.className = 'guide-overlay';
    modal.innerHTML = `
        <div style="background:white;border-radius:16px;max-width:360px;width:100%;padding:28px 24px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,0.15)">
            <div style="font-size:18px;font-weight:700;margin-bottom:12px">${title}</div>
            <div style="font-size:14px;line-height:1.8;color:#4a5568;white-space:pre-line;text-align:left;margin-bottom:20px">${message}</div>
            <button onclick="this.closest('.guide-overlay').remove()" style="width:100%;padding:12px;background:#0066cc;color:white;border:none;border-radius:10px;font-size:15px;font-weight:600;cursor:pointer">확인</button>
        </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
}

// ── PWA 설치 ──
let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (!sessionStorage.getItem('install-dismissed')) {
        document.getElementById('install-banner').style.display = 'block';
    }
});

async function installApp() {
    if (!deferredPrompt) {
        showGuideModal('앱 설치', '메뉴 > "홈 화면에 추가"를 선택해주세요.');
        return;
    }
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    document.getElementById('install-banner').style.display = 'none';
    deferredPrompt = null;
}

function dismissInstall() {
    document.getElementById('install-banner').style.display = 'none';
    sessionStorage.setItem('install-dismissed', '1');
}

window.addEventListener('appinstalled', () => {
    document.getElementById('install-banner').style.display = 'none';
    deferredPrompt = null;
});
