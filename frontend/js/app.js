/**
 * KEPCO 안전관리 시스템 - 프론트엔드 JS
 */

const API_BASE = '';

// ── 상태 관리 ──
const state = {
    sites: [],
    selectedSiteId: null,
    currentWeather: null,
    alertHistory: [],
    refreshInterval: null,
    pushSubscription: null,
    branchOffice: null,  // 선택된 사업소 (null = 전체)
};

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
    // 저장된 사업소가 있으면 바로 진입, 없으면 선택 화면
    const saved = localStorage.getItem('branch_office');
    if (saved !== null) {
        state.branchOffice = saved === 'all' ? null : saved;
        startApp();
    } else {
        showBranchSelect();
    }
});

async function showBranchSelect() {
    const screen = document.getElementById('branch-select-screen');
    screen.style.display = 'flex';
    try {
        const data = await api('/api/branch-offices');
        const sel = document.getElementById('branch-select');
        data.offices.forEach(office => {
            sel.innerHTML += `<option value="${office}">${office}</option>`;
        });
    } catch (e) {}
}

function enterBranch() {
    const raw = document.getElementById('branch-select').value.trim();
    const val = (!raw || raw === '전체 (경남본부)') ? 'all' : raw;
    state.branchOffice = val === 'all' ? null : val;
    localStorage.setItem('branch_office', val);
    document.getElementById('branch-select-screen').style.display = 'none';
    startApp();
}

function changeBranch() {
    localStorage.removeItem('branch_office');
    location.reload();
}

function startApp() {
    // 헤더에 사업소 표시
    const h1 = document.querySelector('.header h1');
    if (h1 && state.branchOffice) h1.textContent = `KEPCO 안전관리 - ${state.branchOffice}`;

    // 본부(전체)만 엑셀 등록/초기화 가능
    const isHQ = !state.branchOffice;
    const excelBtn = document.getElementById('btn-excel-upload');
    const resetBtn = document.getElementById('btn-reset');
    if (excelBtn) excelBtn.style.display = isHQ ? '' : 'none';
    if (resetBtn) resetBtn.style.display = isHQ ? '' : 'none';

    loadSites();
    loadAlertHistory();
    loadStats();

    // 알림 이력/통계만 1분마다 갱신
    setInterval(() => { loadAlertHistory(); loadStats(); }, 60000);

    // 매시 정각 자동 날씨 조회 + 카운트다운
    scheduleHourlyWeather();
    setInterval(updateWeatherCountdown, 10000);  // 10초마다 카운트다운 갱신
}

// ── SMS 상태 확인 ──
async function checkSmsStatus() {
    const el = document.getElementById('sms-status');
    const cb = document.getElementById('sms-enabled');
    if (!cb.checked) { el.textContent = ''; return; }
    try {
        const status = await api('/api/sms/status');
        if (status.configured && status.reachable) {
            el.innerHTML = '<span style="color:var(--safe)">Gateway 연결됨</span>';
        } else if (status.configured) {
            el.innerHTML = '<span style="color:var(--danger)">Gateway 연결 안됨 - 폰 앱 확인</span>';
            cb.checked = false;
        } else {
            el.innerHTML = '<span style="color:var(--text-faint)">.env에 SMS_GATEWAY_URL 설정 필요</span>';
            cb.checked = false;
        }
    } catch (e) {
        el.innerHTML = '<span style="color:var(--danger)">확인 실패</span>';
    }
}

async function sendSmsToSiteWorkers(siteIds, message) {
    // 선택 현장 작업자에게 SMS 발송 (이름/현장 포함)
    const workers = [];
    const sites = state.allSitesWeather || [];
    sites.filter(s => !siteIds || siteIds.includes(s.site_id)).forEach(s => {
        (s.workers || []).forEach(w => {
            if (w.phone) workers.push({ name: w.name || '', phone: w.phone, site: s.site_name || '' });
        });
    });
    if (workers.length === 0) throw new Error('발송 대상 작업자가 없습니다 (전화번호 없음)');
    try {
        return await api('/api/sms/send', {
            method: 'POST',
            body: JSON.stringify({ message, workers, phone_numbers: workers.map(w => w.phone) }),
        });
    } catch (e) {
        console.error('SMS 발송 실패:', e);
        return { sent: 0, failed: workers.length, error: e.message };
    }
}

// ── 매시 정각 날씨 자동 조회 ──
let nextWeatherTime = null;

function scheduleHourlyWeather() {
    const now = new Date();
    const next = new Date(now);
    next.setMinutes(0, 0, 0);
    next.setHours(next.getHours() + 1);
    nextWeatherTime = next;

    const msUntilNext = next.getTime() - now.getTime();
    setTimeout(() => {
        loadAllSitesWeather();
        // 이후 1시간마다 반복
        setInterval(loadAllSitesWeather, 60 * 60 * 1000);
    }, msUntilNext);

    updateWeatherCountdown();
}

function updateWeatherCountdown() {
    const el = document.getElementById('weather-next-refresh');
    if (!el || !nextWeatherTime) return;
    const now = new Date();
    const diff = nextWeatherTime.getTime() - now.getTime();
    if (diff <= 0) {
        nextWeatherTime.setHours(nextWeatherTime.getHours() + 1);
        el.textContent = '조회 중...';
    } else {
        const min = Math.floor(diff / 60000);
        el.textContent = `다음 자동 조회: ${nextWeatherTime.toLocaleTimeString('ko-KR', {hour:'2-digit',minute:'2-digit'})} (${min}분 후)`;
    }
}

// ── Service Worker & 웹 푸시 ──
async function initServiceWorker() {
    if (!('serviceWorker' in navigator)) {
        console.warn('Service Worker를 지원하지 않는 브라우저입니다.');
        return;
    }

    try {
        await navigator.serviceWorker.register('/sw.js');
        const reg = await navigator.serviceWorker.ready;

        // 기존 구독이 있으면 서버에 재등록
        const sub = await reg.pushManager.getSubscription();
        if (sub) {
            state.pushSubscription = sub;
            updatePushButton(true);
            api('/api/push/subscribe', {
                method: 'POST',
                body: JSON.stringify({ subscription: sub.toJSON(), subscriber_type: 'admin' }),
            }).catch(() => {});
        }

        // 모바일 + PWA 미설치 + 처음 방문 → 설치 배너 표시
        if (isMobile() && !isPWA() && !sessionStorage.getItem('install-dismissed')) {
            const banner = document.getElementById('install-banner');
            if (banner) banner.style.display = 'block';
        }

        // SW로부터 푸시 메시지 수신
        navigator.serviceWorker.addEventListener('message', (event) => {
            if (event.data?.type === 'ADMIN_SUMMARY') {
                // 관리자에게 발송 결과 요약 1건만 표시
                showAdminSummary(event.data);
            } else if (event.data?.type === 'PUSH_RECEIVED') {
                // 작업자 알림이 관리자에 온 경우 (하위 호환)
                showInAppAlert(event.data);
            }
        });
    } catch (e) {
        console.error('Service Worker 등록 실패:', e);
    }
}

// ── 경고음 (Web Audio API) ──
function playAlertSound(stage) {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const isDanger = stage === '위험';
        const isWarning = stage === '경고';

        // 단계별 다른 경고음
        const freqs = isDanger ? [880, 660, 880, 660, 880] :
                      isWarning ? [780, 580, 780] :
                      [660, 520];
        const noteDuration = isDanger ? 0.15 : 0.2;
        const gap = 0.08;

        freqs.forEach((freq, i) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);

            osc.type = isDanger ? 'square' : 'sine';
            osc.frequency.value = freq;

            const start = ctx.currentTime + i * (noteDuration + gap);
            gain.gain.setValueAtTime(0.3, start);
            gain.gain.exponentialRampToValueAtTime(0.01, start + noteDuration);

            osc.start(start);
            osc.stop(start + noteDuration);
        });

        // 컨텍스트 자동 정리
        setTimeout(() => ctx.close(), 3000);
    } catch (e) {
        console.warn('경고음 재생 실패:', e);
    }
}

// ── 인앱 폭염 팝업 ──
function showInAppAlert(data) {
    // 경고음 재생
    playAlertSound(data.stage);

    const stageColors = {
        '관심': { bg: '#FFF8E1', border: '#FFC107', text: '#F57F17', icon: '/static/icons/alert-interest.svg' },
        '주의': { bg: '#FFF3E0', border: '#FF9800', text: '#E65100', icon: '/static/icons/alert-caution.svg' },
        '경고': { bg: '#FBE9E7', border: '#FF5722', text: '#BF360C', icon: '/static/icons/alert-warning.svg' },
        '위험': { bg: '#FFEBEE', border: '#D32F2F', text: '#B71C1C', icon: '/static/icons/alert-danger.svg' },
    };
    const colors = stageColors[data.stage] || stageColors['경고'];

    // 기존 인앱 알림 제거
    const old = document.getElementById('inapp-alert');
    if (old) old.remove();

    const popup = document.createElement('div');
    popup.id = 'inapp-alert';
    popup.style.cssText = `
        position:fixed; top:0; left:0; right:0; z-index:10000;
        animation: slideDown 0.3s ease-out;
    `;
    popup.innerHTML = `
        <div style="
            max-width:540px; margin:12px auto; padding:16px 18px;
            background:${colors.bg}; border:2px solid ${colors.border};
            border-radius:16px; box-shadow:0 8px 32px rgba(0,0,0,0.18);
            display:flex; align-items:flex-start; gap:14px;
        ">
            <img src="${colors.icon}" alt="" style="width:48px;height:48px;border-radius:12px;flex-shrink:0">
            <div style="flex:1;min-width:0">
                <div style="font-size:16px;font-weight:800;color:${colors.text};margin-bottom:4px">
                    ${data.title}
                </div>
                <div style="font-size:13px;color:#333;line-height:1.5;white-space:pre-line">${data.body}</div>
                ${data.actions?.length ? `<div style="font-size:12px;color:${colors.text};margin-top:6px;opacity:0.8">${data.actions[0]}</div>` : ''}
            </div>
            <button onclick="this.closest('#inapp-alert').remove()" style="
                background:none; border:none; font-size:22px; color:${colors.text};
                cursor:pointer; padding:0; line-height:1; opacity:0.6; flex-shrink:0;
            ">&times;</button>
        </div>
    `;
    document.body.appendChild(popup);

    // 위험 단계가 아니면 8초 후 자동 닫힘
    if (data.stage !== '위험') {
        setTimeout(() => {
            if (popup.parentNode) {
                popup.style.animation = 'slideUp 0.3s ease-in forwards';
                setTimeout(() => popup.remove(), 300);
            }
        }, 8000);
    }

    // 데이터 갱신
    loadAllSitesWeather();
    loadAlertHistory();
    loadStats();
}

// ── 관리자 발송 요약 표시 ──
function showAdminSummary(data) {
    playAlertSound(data.stage);

    const msg = `${data.site} - 폭염 ${data.stage} ${data.temperature}°C\n알림 ${data.sent_count}/${data.total_count}건 발송 완료`;
    showToast(msg, data.sent_count > 0 ? 'success' : 'warning', 6000);

    // 데이터 갱신
    loadAllSitesWeather();
    loadAlertHistory();
    loadStats();
}

async function togglePushSubscription() {
    if (state.pushSubscription) {
        await unsubscribePush();
    } else {
        await subscribePush();
    }
}

// ── 환경 감지 ──
function isPWA() {
    return window.matchMedia('(display-mode: standalone)').matches
        || window.navigator.standalone === true;
}
function isIOS() {
    return /iphone|ipad|ipod/i.test(navigator.userAgent);
}
function isAndroid() {
    return /android/i.test(navigator.userAgent);
}
function isMobile() {
    return isIOS() || isAndroid();
}

async function subscribePush() {
    // 1) Service Worker 미지원
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        showGuideModal(
            '이 브라우저에서는 알림을 지원하지 않습니다.',
            isMobile()
                ? 'Chrome 또는 Samsung Internet 브라우저로 접속해주세요.'
                : 'Chrome 또는 Edge 브라우저로 접속해주세요.'
        );
        return;
    }

    // 2) iOS + Safari이고 PWA 미설치 → 홈화면 추가 안내
    if (isIOS() && !isPWA()) {
        showGuideModal(
            '먼저 홈 화면에 앱을 추가해주세요',
            '① 하단 공유 버튼(□↑)을 터치\n② "홈 화면에 추가"를 터치\n③ 추가된 앱을 열고 다시 알림을 허용해주세요\n\n(iOS는 앱 설치 후에만 알림이 동작합니다)'
        );
        return;
    }

    // 3) 알림 권한 확인
    let permission = Notification.permission;

    if (permission === 'denied') {
        // 이미 거부됨 → 브라우저 설정 안내
        showGuideModal(
            '알림이 차단된 상태입니다',
            isMobile()
                ? '아래 방법으로 알림을 허용해주세요:\n\n'
                  + (isAndroid()
                      ? '① 주소창 왼쪽 자물쇠(🔒) 터치\n② "알림" → "허용"으로 변경\n③ 페이지 새로고침'
                      : '① 설정 > Safari > 알림 > 이 사이트 허용\n② 페이지 새로고침')
                : '① 주소창 왼쪽 자물쇠(🔒) 클릭\n② "알림" → "허용"으로 변경\n③ 페이지 새로고침'
        );
        return;
    }

    // 4) 권한 요청 (default 상태)
    if (permission === 'default') {
        permission = await Notification.requestPermission();
        if (permission !== 'granted') {
            showGuideModal(
                '알림 허용이 필요합니다',
                '방금 나타난 팝업에서 "허용"을 터치해야 합니다.\n\n팝업이 안 나타나면:\n'
                + (isMobile()
                    ? '① 주소창 왼쪽 자물쇠(🔒) 터치\n② "알림" → "허용"으로 변경'
                    : '① 주소창 왼쪽 자물쇠(🔒) 클릭\n② "알림" → "허용"으로 변경')
            );
            return;
        }
    }

    // 5) 푸시 구독 실행
    try {
        const { public_key } = await api('/api/push/vapid-key');
        const reg = await navigator.serviceWorker.ready;

        const sub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(public_key),
        });

        await api('/api/push/subscribe', {
            method: 'POST',
            body: JSON.stringify({ subscription: sub.toJSON(), subscriber_type: 'admin' }),
        });

        state.pushSubscription = sub;
        updatePushButton(true);

    } catch (e) {
        console.error('푸시 구독 실패:', e);
        showGuideModal(
            '알림 설정 중 오류가 발생했습니다',
            '잠시 후 다시 시도해주세요.\n문제가 계속되면 관리자에게 문의하세요.'
        );
    }
}

async function unsubscribePush() {
    try {
        if (state.pushSubscription) {
            const endpoint = state.pushSubscription.endpoint;
            await state.pushSubscription.unsubscribe();
            await api('/api/push/unsubscribe', {
                method: 'POST',
                body: JSON.stringify({ endpoint }),
            }).catch(() => {});
        }
        state.pushSubscription = null;
        updatePushButton(false);
    } catch (e) {
        console.error('구독 해제 실패:', e);
    }
}

function updatePushButton(subscribed) {
    const btn = document.getElementById('push-btn');
    if (!btn) return;
    btn.className = subscribed ? 'btn-notify active' : 'btn-notify';
    btn.textContent = subscribed ? 'ал림 ON' : '알림 허용';
    btn.textContent = subscribed ? '알림 ON' : '알림 허용';
}

// ── 토스트 알림 (alert 대체) ──
function showToast(message, type = 'info', duration = 4000) {
    const colors = {
        success: { bg: '#ecfdf5', border: '#10b981', text: '#065f46', icon: 'V' },
        error:   { bg: '#fef2f2', border: '#ef4444', text: '#991b1b', icon: 'X' },
        info:    { bg: '#eff6ff', border: '#3b82f6', text: '#1e40af', icon: 'i' },
        warning: { bg: '#fffbeb', border: '#f59e0b', text: '#92400e', icon: '!' },
    };
    const c = colors[type] || colors.info;

    const toast = document.createElement('div');
    toast.style.cssText = `position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:10001;
        max-width:480px;width:calc(100% - 32px);padding:14px 18px;
        background:${c.bg};border:1px solid ${c.border};border-radius:12px;
        box-shadow:0 8px 24px rgba(0,0,0,0.12);
        display:flex;align-items:flex-start;gap:10px;
        animation:slideUp 0.3s ease-out reverse;font-size:13px;line-height:1.5`;
    toast.innerHTML = `
        <span style="flex-shrink:0;width:22px;height:22px;border-radius:50%;background:${c.border};color:white;
            display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700">${c.icon}</span>
        <div style="flex:1;color:${c.text};white-space:pre-line">${message}</div>
        <button onclick="this.parentElement.remove()" style="background:none;border:none;color:${c.text};opacity:0.5;cursor:pointer;font-size:16px">&times;</button>
    `;
    document.body.appendChild(toast);
    if (duration > 0) {
        setTimeout(() => { if (toast.parentNode) toast.remove(); }, duration);
    }
}

// ── 프로그레스바 ──
function showProgress(containerId, message) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = `
        <div style="padding:20px">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
                <div class="progress-spinner"></div>
                <span style="font-size:13px;color:var(--text-mid,#4a5568)" id="${containerId}-msg">${message}</span>
            </div>
            <div style="height:4px;background:var(--border,#e2e8f0);border-radius:4px;overflow:hidden">
                <div id="${containerId}-bar" style="height:100%;width:0%;background:var(--kepco,#0066cc);border-radius:4px;transition:width 0.3s ease"></div>
            </div>
        </div>`;
}

function updateProgress(containerId, percent, message) {
    const bar = document.getElementById(`${containerId}-bar`);
    const msg = document.getElementById(`${containerId}-msg`);
    if (bar) bar.style.width = `${Math.min(percent, 100)}%`;
    if (msg && message) msg.textContent = message;
}

// ── 안내 모달 (alert 대체) ──
function showGuideModal(title, message) {
    // 기존 모달 제거
    const old = document.getElementById('guide-modal');
    if (old) old.remove();

    const modal = document.createElement('div');
    modal.id = 'guide-modal';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;justify-content:center;align-items:center;padding:20px';
    modal.innerHTML = `
        <div style="background:#fff;border-radius:16px;max-width:380px;width:100%;padding:28px 24px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,0.15)">
            <div style="font-size:18px;font-weight:700;margin-bottom:12px;color:#1a1a2e">${title}</div>
            <div style="font-size:14px;line-height:1.8;color:#4a5568;white-space:pre-line;text-align:left;margin-bottom:20px">${message}</div>
            <button onclick="this.closest('#guide-modal').remove()" style="width:100%;padding:12px;background:#0066cc;color:white;border:none;border-radius:10px;font-size:15px;font-weight:600;cursor:pointer">확인</button>
        </div>
    `;
    document.body.appendChild(modal);
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
}

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = window.atob(base64);
    const arr = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
    return arr;
}

// ── 작업현장 목록 ──
async function loadSites() {
    try {
        state.sites = await api('/api/sites');
        renderSiteList();
        // 현장이 있으면 일단 기본 목록을 먼저 보여주고, 날씨는 비동기로
        if (state.sites.length > 0) {
            renderSitesBasicList();
            loadAllSitesWeather();
        }
    } catch (e) {
        console.error('현장 목록 로딩 실패:', e);
    }
}

function renderSitesBasicList() {
    const container = document.getElementById('all-sites-overview');
    if (!container || !state.sites.length) return;
    container.innerHTML = state.sites.map(site => `
        <div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;cursor:pointer" onclick="selectSiteFromOverview(${site.id})">
            <div style="flex:1;min-width:0">
                <div style="font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${site.name}</div>
                <div style="font-size:11px;color:var(--text-dim);margin-top:2px">${site.address || ''}</div>
            </div>
            <div style="font-size:12px;color:var(--text-dim)">날씨 조회 중...</div>
        </div>
    `).join('');
}

function renderSiteList() {
    const container = document.getElementById('site-list');
    if (!container) return;

    if (state.sites.length === 0) {
        container.innerHTML = `
            <div style="padding:20px;text-align:center;color:var(--text-secondary)">
                등록된 작업현장이 없습니다.<br>
                <button class="btn btn-primary btn-sm" style="margin-top:10px"
                        onclick="openModal('site-modal')">현장 등록</button>
            </div>`;
        return;
    }

    container.innerHTML = state.sites.map(site => `
        <div class="site-item" onclick="selectSite(${site.id})"
             style="${state.selectedSiteId === site.id ? 'background:var(--bg-card-hover)' : ''}">
            <div>
                <div class="site-name">${site.name}</div>
                <div style="font-size:12px;color:var(--text-secondary)">${site.address || ''}</div>
            </div>
            <div id="site-badge-${site.id}"></div>
        </div>
    `).join('');
}

async function selectSite(siteId) {
    state.selectedSiteId = siteId;
    renderSiteList();
    await loadWeather(siteId);
}

// ── 전체 현장 날씨 일괄 조회 ──
async function loadAllSitesWeather() {
    // 모의 테스트 모드에서는 실제 날씨 조회 안 함
    if (mockMode) return;
    const progressEl = document.getElementById('send-progress');
    try {
        // 프로그레스를 별도 영역에 표시 (현장 목록 유지)
        if (progressEl) {
            progressEl.style.display = 'block';
            progressEl.innerHTML = `<div style="display:flex;align-items:center;gap:8px">
                <div class="progress-spinner"></div>
                <span style="font-size:13px;color:var(--text-mid)">${state.sites.length}개 현장 날씨 조회 중...</span>
            </div>`;
        }

        const data = await api('/api/weather/status-all');
        if (progressEl) progressEl.style.display = 'none';
        state.allSitesWeather = data.sites;

        // 조회 결과 표시
        const timeEl = document.getElementById('weather-checked-time');
        const statusEl = document.getElementById('weather-status');
        const firstWithTime = data.sites.find(s => s.checked_at);
        if (timeEl && firstWithTime) {
            timeEl.textContent = `${new Date(firstWithTime.checked_at).toLocaleString('ko-KR', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})} 기준`;
        }
        if (statusEl) {
            const ok = data.weather_success || 0;
            const fail = data.weather_error || 0;
            const grids = data.grids_queried || 0;
            if (fail > 0) {
                statusEl.innerHTML = `<span style="color:var(--safe)">${ok}개 성공</span> <span style="color:var(--danger)">${fail}개 실패</span> (${grids}격자)`;
            } else {
                statusEl.innerHTML = `<span style="color:var(--safe)">${ok}개 조회 완료</span> (${grids}격자)`;
            }
        }

        // 첫 번째 현장 또는 가장 위험한 현장을 상세 표시
        if (data.sites.length > 0) {
            const top = data.sites.find(s => s.weather) || data.sites[0];
            if (top && top.weather) {
                state.selectedSiteId = top.site_id;
                renderWeatherDashboard({
                    work_site_name: top.site_name,
                    weather: top.weather,
                    stage: top.stage,
                    wbgt_work_recommendation: top.wbgt_recommendation,
                });
            }
        }

        // 사이트 목록에 배지 표시
        data.sites.forEach(s => {
            const badge = document.getElementById(`site-badge-${s.site_id}`);
            if (badge && s.weather) {
                const stg = s.stage;
                const color = stg ? stg.color : '#27ae60';
                const label = stg ? stg.name : '정상';
                const temp = s.weather.apparent_temperature;
                badge.innerHTML = `
                    <div style="text-align:right">
                        <div style="font-size:18px;font-weight:700">${temp}°</div>
                        <span class="site-stage-badge" style="background:${color};color:white">${label}</span>
                    </div>`;
            }
        });

        // 필터 적용 및 전체 목록 렌더링 (마지막에 실행하여 최종 상태 반영)
        renderSiteList();
        filterSites(currentFilter);
    } catch (e) {
        console.error('전체 현장 날씨 조회 실패:', e);
        if (progressEl) {
            progressEl.innerHTML = `<div style="color:var(--danger);font-size:13px;padding:4px">날씨 조회 실패: ${e.message}</div>`;
            setTimeout(() => { progressEl.style.display = 'none'; }, 8000);
        }
        // 날씨 실패해도 기본 현장 목록은 유지
        const container = document.getElementById('all-sites-overview');
        if (container && state.sites.length > 0) {
            container.innerHTML = state.sites.map(site => `
                <div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
                    <div style="flex:1;min-width:0">
                        <div style="font-weight:600;font-size:14px">${site.name}</div>
                        <div style="font-size:11px;color:var(--text-dim);margin-top:2px">${site.address || ''}</div>
                    </div>
                    <div style="font-size:12px;color:var(--text-dim)">날씨 조회 실패</div>
                </div>
            `).join('');
        }
    }
}

function renderAllSitesOverview(sites) {
    const container = document.getElementById('all-sites-overview');
    if (!container) return;

    if (sites.length === 0) {
        if (state.allSitesWeather && state.allSitesWeather.length > 0) {
            // 날씨는 로드됐지만 필터/사업소 조건에 맞는 현장이 없음
            container.innerHTML = '<p style="padding:20px;text-align:center;color:var(--text-secondary)">해당 조건에 맞는 현장이 없습니다.</p>';
        } else if (state.sites.length > 0) {
            // 아직 날씨 로딩 중
            container.innerHTML = state.sites.map(site => `
                <div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;cursor:pointer" onclick="selectSiteFromOverview(${site.id})">
                    <div style="flex:1;min-width:0">
                        <div style="font-weight:600;font-size:14px">${site.name}</div>
                        <div style="font-size:11px;color:var(--text-dim);margin-top:2px">${site.address || ''}</div>
                    </div>
                    <div style="font-size:12px;color:var(--text-dim)">날씨 조회 중...</div>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p style="padding:20px;text-align:center;color:var(--text-secondary)">현장을 등록하면 날씨가 표시됩니다.</p>';
        }
        return;
    }

    container.innerHTML = sites.map(s => {
        if (s.error) {
            return `<div style="padding:10px;border-bottom:1px solid rgba(255,255,255,0.05);font-size:13px;color:var(--text-secondary)">
                ${s.site_name}: 조회 실패</div>`;
        }

        const stg = s.stage;
        const color = stg ? stg.color : '#27ae60';
        const label = stg ? stg.name : '정상';
        const w = s.weather || {};
        const isSelected = state.selectedSiteId === s.site_id;

        // 날씨 데이터가 없는 경우 (좌표 없음 등)
        if (!s.weather) {
            return `
            <div onclick="selectSiteFromOverview(${s.site_id})" style="
                padding:14px 16px;
                border-bottom:1px solid var(--border-light, #edf2f7);
                cursor:pointer;
                ${isSelected ? 'background:var(--kepco-light, #e8f2ff);border-left:3px solid var(--kepco, #0066cc)' : 'border-left:3px solid transparent'}
            ">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div style="flex:1;min-width:0">
                        <div style="font-weight:600;font-size:14px;color:var(--text, #1a1a2e)">${s.site_name}</div>
                        <div style="font-size:11px;color:var(--text-dim, #8896a6);margin-top:2px">${s.address || ''}</div>
                    </div>
                    <div style="font-size:12px;color:var(--text-dim)">날씨 정보 없음</div>
                </div>
            </div>`;
        }

        return `
        <div onclick="selectSiteFromOverview(${s.site_id})" style="
            padding:14px 16px;
            border-bottom:1px solid var(--border-light, #edf2f7);
            cursor:pointer;
            transition:background 0.12s;
            ${isSelected ? 'background:var(--kepco-light, #e8f2ff);border-left:3px solid var(--kepco, #0066cc)' : 'border-left:3px solid transparent'}
        ">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <div style="flex:1;min-width:0">
                    <div style="display:flex;align-items:center;gap:6px">
                        <input type="checkbox" class="site-check" data-site-id="${s.site_id}" onclick="event.stopPropagation();updateSelectedCount()" style="width:auto;display:none">
                        <span style="font-weight:600;font-size:14px;color:var(--text, #1a1a2e);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1">${s.site_name}</span>
                    </div>
                    <div style="font-size:11px;color:var(--text-dim, #8896a6);margin-top:2px">${s.branch_office ? `<span style="color:var(--kepco)">${s.branch_office}</span> | ` : ''}${s.address || ''}</div>
                    ${s.worker_count > 0 ? (() => {
                        const total = s.workers?.length || 0;
                        const sent = s.workers?.filter(w => w.last_alert?.status === 'sent').length || 0;
                        const failed = s.workers?.filter(w => w.last_alert?.status === 'failed').length || 0;
                        const hasAlerts = (sent + failed) > 0;
                        return `<div style="font-size:11px;margin-top:2px">
                            <span style="color:var(--kepco,#0066cc)">작업자 ${total}명</span>${s.workers?.some(w=>w.is_vulnerable) ? ' <span style="color:#e74c3c;font-size:10px">(취약 포함)</span>' : ''}
                            ${hasAlerts ? ` <span style="color:var(--text-dim)">|</span> 알림 <span style="color:${sent > 0 ? 'var(--safe)' : 'var(--text-faint)'};font-weight:600">${sent}</span><span style="color:var(--text-faint)">/${total}건</span>` : ''}
                        </div>`;
                    })() : ''}
                </div>
                <div style="display:flex;align-items:center;gap:12px;flex-shrink:0;margin-left:12px">
                    <div style="text-align:right">
                        <div style="font-size:11px;color:var(--text-dim, #8896a6)">체감</div>
                        <div style="font-size:20px;font-weight:700;color:${w.apparent_temperature >= 33 ? color : 'var(--text, #1a1a2e)'}">${w.apparent_temperature}°</div>
                    </div>
                    <div class="site-detail" style="display:flex;gap:10px">
                        <div style="text-align:center"><div style="font-size:10px;color:var(--text-dim)">기온</div><div style="font-weight:600;font-size:13px">${w.temperature}°</div></div>
                        <div style="text-align:center"><div style="font-size:10px;color:var(--text-dim)">습도</div><div style="font-weight:600;font-size:13px">${w.humidity}%</div></div>
                    </div>
                    <span class="badge" style="background:${color}">${label}</span>
                    <button onclick="event.stopPropagation();verifyWeather(${s.site_id})" style="flex-shrink:0;padding:2px 6px;background:var(--bg-hover,#f7f9fb);border:1px solid var(--border,#e2e8f0);border-radius:4px;font-size:10px;color:var(--text-dim,#8896a6);cursor:pointer" title="날씨 데이터 검증">검증</button>
                </div>
            </div>
            ${stg && stg.key !== 'stage_1_interest' ? `<div style="margin-top:6px;font-size:12px;color:${color}">${stg.work_restriction}</div>` : ''}
            ${s.workers?.length > 0 && isSelected ? `<div style="margin-top:8px;padding:8px;background:var(--bg-card,#f8fafc);border-radius:6px;font-size:12px">
                <div style="font-weight:600;margin-bottom:4px;color:var(--text-dim)">배정 작업자 (${s.workers.length}명)</div>
                ${s.workers.map(w => {
                    const a = w.last_alert;
                    const alertOk = a && a.status === 'sent';
                    const alertFail = a && a.status === 'failed';
                    const stageNames = { 'stage_1_interest': '관심', 'stage_2_caution': '주의', 'stage_3_warning': '경고', 'stage_4_danger': '위험' };
                    const alertTime = a ? new Date(a.sent_at).toLocaleString('ko-KR', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
                    return `<div style="display:flex;justify-content:space-between;align-items:center;padding:3px 0;border-bottom:1px solid var(--border-light,#edf2f7)">
                    <div style="display:flex;align-items:center;gap:6px">
                        <span style="font-weight:500">${w.name}</span>
                        <span style="color:var(--text-faint);font-size:11px">${w.phone}</span>
                        ${w.is_vulnerable ? '<span style="font-size:9px;padding:1px 4px;background:rgba(231,76,60,0.12);color:#e74c3c;border-radius:4px">취약</span>' : ''}
                    </div>
                    <div style="display:flex;align-items:center;gap:4px;font-size:11px">
                        ${a ? `
                            <span style="color:${alertOk ? 'var(--safe,#10b981)' : 'var(--danger,#dc2626)'};font-weight:600">${alertOk ? 'V' : 'X'}</span>
                            <span style="color:${alertOk ? 'var(--safe,#10b981)' : 'var(--danger,#dc2626)'}">${stageNames[a.stage] || ''} ${a.temperature}°</span>
                            <span style="color:var(--text-faint);font-size:10px">${alertTime}</span>
                            <span style="color:var(--text-faint);font-size:9px;padding:1px 3px;background:var(--border-light,#edf2f7);border-radius:3px">${a.channel === 'web_push' ? '푸시' : a.channel === 'kakao_alimtalk' ? '카톡' : a.channel || ''}</span>
                        ` : '<span style="color:var(--text-faint)">알림 없음</span>'}
                    </div>
                </div>`;
                }).join('')}
            </div>` : ''}
        </div>`;
    }).join('');
}

function selectSiteFromOverview(siteId) {
    state.selectedSiteId = siteId;
    // 해당 현장 날씨 데이터를 캐시에서 찾아 렌더링
    const siteData = (state.allSitesWeather || []).find(s => s.site_id === siteId);
    if (siteData && siteData.weather) {
        renderWeatherDashboard({
            work_site_name: siteData.site_name,
            weather: siteData.weather,
            stage: siteData.stage,
            wbgt_work_recommendation: siteData.wbgt_recommendation,
        });
    } else {
        loadWeather(siteId);
    }
    renderSiteList();
    renderAllSitesOverview(state.allSitesWeather || []);
    // 모바일에서 상단으로 스크롤
    if (isMobile()) window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── 개별 현장 날씨 조회 ──
async function loadWeather(siteId) {
    try {
        const data = await api(`/api/weather/status/${siteId}`);
        state.currentWeather = data;
        renderWeatherDashboard(data);
    } catch (e) {
        console.error('날씨 조회 실패:', e);
        document.getElementById('weather-content').innerHTML =
            '<p style="color:var(--text-secondary);padding:20px">날씨 데이터를 불러올 수 없습니다.</p>';
    }
}

function renderWeatherDashboard(data) {
    if (!data || !data.weather) return;
    const { weather, stage, wbgt_work_recommendation, work_site_name, checked_at } = data;

    renderAlertBanner(stage, weather, work_site_name);

    // 타이틀에 현장명 + 조회 시간
    const titleEl = document.getElementById('weather-title');
    if (titleEl) {
        const timeStr = checked_at ? new Date(checked_at).toLocaleString('ko-KR', {hour:'2-digit',minute:'2-digit'}) : '';
        titleEl.textContent = (work_site_name || '현재 날씨') + (timeStr ? ` (${timeStr} 기준)` : '');
    }

    // 날씨 수치
    const weatherEl = document.getElementById('weather-content');
    if (weatherEl) {
        const isHot = weather.apparent_temperature >= 33;
        weatherEl.innerHTML = `
            <div class="grid grid-3" style="gap:8px;margin-bottom:12px">
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
                    <div style="font-size:11px;color:var(--kepco-light);margin-top:2px">${wbgt_work_recommendation || ''}</div>
                </div>
            </div>
            ${state.selectedSiteId ? `<button onclick="verifyWeather(${state.selectedSiteId})" style="margin-top:8px;width:100%;padding:8px;background:none;border:1px dashed var(--border);border-radius:var(--radius-sm);font-size:11px;color:var(--text-dim);cursor:pointer;display:flex;align-items:center;justify-content:center;gap:4px" title="기상청 API 원시 데이터와 계산 과정을 상세 검증합니다"><span style="font-size:13px">&#128269;</span> 날씨 데이터 검증</button>` : ''}`;
    }

    renderStageIndicator(stage);
    renderActions(stage);
}

async function verifyAllWeather() {
    const btn = event?.target?.closest('button');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="progress-spinner" style="width:12px;height:12px;border-width:2px;display:inline-block;vertical-align:middle;margin-right:4px"></span>전체 검증 중...'; }
    try {
        const v = await api('/api/weather/verify-all');
        if (v.error) { showToast(v.error, 'error'); return; }

        const results = v.results || [];
        const matchCount = results.filter(r => r.comparison?.temperature_match && r.comparison?.humidity_match).length;
        const mismatchCount = results.filter(r => r.comparison && (!r.comparison.temperature_match || !r.comparison.humidity_match)).length;
        const noDataCount = results.filter(r => !r.comparison).length;
        const errorCount = results.filter(r => r.error).length;

        let rowsHtml = results.map(r => {
            if (r.error) {
                return `<tr style="background:#fef2f2">
                    <td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;font-weight:500">${r.site_name}</td>
                    <td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;font-size:10px;color:#64748b">${r.grid}</td>
                    <td colspan="6" style="padding:6px 8px;border-bottom:1px solid #f1f5f9;color:#dc2626">${r.error}</td>
                </tr>`;
            }
            const kma = r.kma_raw || {};
            const sys = r.system_cached || {};
            const cmp = r.comparison || {};
            const tempOk = cmp.temperature_match;
            const humOk = cmp.humidity_match;
            const appOk = cmp.apparent_match;
            const rowBg = (tempOk === false || humOk === false) ? '#fffbeb' : '';

            return `<tr style="background:${rowBg}">
                <td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;font-weight:500;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.site_name}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;font-size:10px;color:#64748b;text-align:center">${r.grid}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;text-align:center">${kma.temperature}°</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;text-align:center">${sys?.temperature != null ? sys.temperature + '°' : '<span style="color:#94a3b8">-</span>'}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;text-align:center;color:${tempOk === false ? '#dc2626' : tempOk === true ? '#16a34a' : '#94a3b8'};font-weight:600">${tempOk === true ? '&#10003;' : tempOk === false ? '&#10005; ' + (cmp.temp_diff || '') + '°' : '-'}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;text-align:center">${kma.apparent_temperature}°</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;text-align:center">${kma.humidity}%</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;text-align:center">${kma.stage}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;text-align:center">
                    <button onclick="event.stopPropagation();verifyWeather(${r.site_id})" style="padding:2px 8px;background:none;border:1px solid #e2e8f0;border-radius:4px;font-size:10px;color:#64748b;cursor:pointer">상세</button>
                </td>
            </tr>`;
        }).join('');

        const modal = document.createElement('div');
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;justify-content:center;align-items:flex-start;padding:20px;overflow-y:auto';
        modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
        modal.innerHTML = `
        <div style="background:white;border-radius:12px;max-width:900px;width:100%;padding:0;box-shadow:0 20px 60px rgba(0,0,0,0.2);margin:20px auto;max-height:90vh;overflow-y:auto">
            <div style="padding:16px 20px;border-bottom:1px solid #e2e8f0;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;background:white;border-radius:12px 12px 0 0;z-index:1">
                <div>
                    <div style="font-size:15px;font-weight:700">&#128269; 전체 현장 날씨 데이터 검증</div>
                    <div style="font-size:11px;color:#64748b">${new Date(v.timestamp).toLocaleString('ko-KR')} | 발표 ${v.base_date} ${v.base_time} | 예보 ${v.target_fcst_time} | ${v.grids_queried}개 격자 조회</div>
                </div>
                <button onclick="this.closest('[style*=fixed]').remove()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#64748b;padding:4px 8px">&times;</button>
            </div>

            <div style="padding:12px 20px;display:flex;gap:12px;flex-wrap:wrap;border-bottom:1px solid #e2e8f0">
                <div style="padding:8px 16px;background:${v.all_match ? '#f0fdf4' : '#fffbeb'};border-radius:8px;text-align:center">
                    <div style="font-size:20px;font-weight:700;color:${v.all_match ? '#16a34a' : '#d97706'}">${v.all_match ? '&#10003; 일치' : '&#9888; 불일치'}</div>
                    <div style="font-size:10px;color:#64748b">전체 결과</div>
                </div>
                <div style="padding:8px 16px;background:#f0fdf4;border-radius:8px;text-align:center">
                    <div style="font-size:20px;font-weight:700;color:#16a34a">${matchCount}</div>
                    <div style="font-size:10px;color:#64748b">일치</div>
                </div>
                ${mismatchCount > 0 ? `<div style="padding:8px 16px;background:#fffbeb;border-radius:8px;text-align:center">
                    <div style="font-size:20px;font-weight:700;color:#d97706">${mismatchCount}</div>
                    <div style="font-size:10px;color:#64748b">불일치</div>
                </div>` : ''}
                ${noDataCount > 0 ? `<div style="padding:8px 16px;background:#f8fafc;border-radius:8px;text-align:center">
                    <div style="font-size:20px;font-weight:700;color:#94a3b8">${noDataCount}</div>
                    <div style="font-size:10px;color:#64748b">캐시없음</div>
                </div>` : ''}
                ${errorCount > 0 ? `<div style="padding:8px 16px;background:#fef2f2;border-radius:8px;text-align:center">
                    <div style="font-size:20px;font-weight:700;color:#dc2626">${errorCount}</div>
                    <div style="font-size:10px;color:#64748b">오류</div>
                </div>` : ''}
            </div>

            <div style="padding:0 20px 16px;overflow-x:auto">
                <table style="width:100%;border-collapse:collapse;font-size:11px;margin-top:12px">
                    <thead><tr style="background:#f8fafc;position:sticky;top:56px">
                        <th style="padding:6px 8px;text-align:left;border-bottom:2px solid #e2e8f0;font-weight:600">현장명</th>
                        <th style="padding:6px 8px;text-align:center;border-bottom:2px solid #e2e8f0;font-weight:600">격자</th>
                        <th style="padding:6px 8px;text-align:center;border-bottom:2px solid #e2e8f0;font-weight:600;color:#0066cc">KMA 기온</th>
                        <th style="padding:6px 8px;text-align:center;border-bottom:2px solid #e2e8f0;font-weight:600;color:#7c3aed">시스템 기온</th>
                        <th style="padding:6px 8px;text-align:center;border-bottom:2px solid #e2e8f0;font-weight:600">일치</th>
                        <th style="padding:6px 8px;text-align:center;border-bottom:2px solid #e2e8f0;font-weight:600">체감</th>
                        <th style="padding:6px 8px;text-align:center;border-bottom:2px solid #e2e8f0;font-weight:600">습도</th>
                        <th style="padding:6px 8px;text-align:center;border-bottom:2px solid #e2e8f0;font-weight:600">단계</th>
                        <th style="padding:6px 8px;text-align:center;border-bottom:2px solid #e2e8f0;font-weight:600"></th>
                    </tr></thead>
                    <tbody>${rowsHtml}</tbody>
                </table>
            </div>

            <div style="padding:12px 20px;border-top:1px solid #e2e8f0;font-size:10px;color:#94a3b8;line-height:1.6">
                * <b>KMA 기온</b>: 기상청 API에서 실시간으로 가져온 원시 값 | <b>시스템 기온</b>: 마지막 새로고침 시 저장된 캐시 값<br>
                * 새로고침 후 "전체 검증"하면 두 값이 일치해야 정상입니다. 불일치 시 새로고침 후 재확인하세요.<br>
                * 각 현장의 [상세] 버튼으로 계산 과정(체감온도 공식, WBGT 등)을 세부 검증할 수 있습니다.
            </div>
        </div>`;
        document.body.appendChild(modal);
    } catch (e) {
        showToast('전체 검증 실패: ' + e.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '전체 검증'; }
    }
}

async function verifyWeather(siteId) {
    const btn = event?.target?.closest('button');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="progress-spinner" style="width:12px;height:12px;border-width:2px;display:inline-block;vertical-align:middle;margin-right:4px"></span>검증 중...'; }
    try {
        const v = await api(`/api/weather/verify/${siteId}`);
        if (v.error) { showToast(v.error, 'error'); return; }

        const s = v.summary || {};
        const grid = v.grid || {};
        const req = v.api_request || {};
        const raw = v.raw_kma_data || {};
        const hi = v.heat_index_calculation || {};
        const wb = v.wbgt_calculation || {};
        const st = v.stage_determination || {};
        const links = v.external_links || {};
        const hourly = v.hourly_forecast || [];

        // 시간대별 기온 테이블
        let hourlyHtml = '';
        if (hourly.length > 0) {
            hourlyHtml = `<div style="margin-top:12px"><div style="font-weight:600;font-size:12px;margin-bottom:4px">오늘 시간대별 예보 (KMA 원시)</div>
                <div style="max-height:140px;overflow-y:auto;border:1px solid #e2e8f0;border-radius:6px">
                <table style="width:100%;border-collapse:collapse;font-size:11px">
                    <thead><tr style="background:#f8fafc;position:sticky;top:0">
                        <th style="padding:4px 6px;border-bottom:1px solid #e2e8f0;text-align:center">시각</th>
                        <th style="padding:4px 6px;border-bottom:1px solid #e2e8f0;text-align:center">기온(°C)</th>
                        <th style="padding:4px 6px;border-bottom:1px solid #e2e8f0;text-align:center">습도(%)</th>
                        <th style="padding:4px 6px;border-bottom:1px solid #e2e8f0;text-align:center">풍속(m/s)</th>
                    </tr></thead><tbody>`;
            hourly.forEach(h => {
                const isCurrent = h.time === (raw.used_forecast_time || '').replace(/(\d{2})(\d{2})/, '$1:$2');
                hourlyHtml += `<tr style="${isCurrent ? 'background:#e8f2ff;font-weight:600' : ''}">
                    <td style="padding:3px 6px;text-align:center;border-bottom:1px solid #f1f5f9">${h.time}${isCurrent ? ' *' : ''}</td>
                    <td style="padding:3px 6px;text-align:center;border-bottom:1px solid #f1f5f9">${h.temperature ?? '-'}</td>
                    <td style="padding:3px 6px;text-align:center;border-bottom:1px solid #f1f5f9">${h.humidity ?? '-'}</td>
                    <td style="padding:3px 6px;text-align:center;border-bottom:1px solid #f1f5f9">${h.wind_speed ?? '-'}</td>
                </tr>`;
            });
            hourlyHtml += '</tbody></table></div></div>';
        }

        // 단계 판정 테이블
        let stageHtml = '';
        if (st.thresholds) {
            stageHtml = st.thresholds.map(t =>
                `<span style="display:inline-block;padding:2px 8px;margin:2px;border-radius:4px;font-size:11px;${t.matched ? 'background:#fee2e2;color:#991b1b;font-weight:600' : 'background:#f1f5f9;color:#64748b'}">${t.name} ${t.min_temp}°C ${t.matched ? '&#10003;' : ''}</span>`
            ).join('');
        }

        // 카테고리 데이터
        let catHtml = '';
        if (raw.categories) {
            catHtml = Object.entries(raw.categories).map(([k, c]) =>
                `<tr><td style="padding:3px 8px;border-bottom:1px solid #f1f5f9;font-weight:500">${k}</td>
                 <td style="padding:3px 8px;border-bottom:1px solid #f1f5f9">${c.label}</td>
                 <td style="padding:3px 8px;border-bottom:1px solid #f1f5f9;font-weight:600">${c.value}</td></tr>`
            ).join('');
        }

        // 체감온도 계산 과정
        let hiDetail = '';
        if (hi.coefficients) {
            hiDetail = Object.entries(hi.coefficients).map(([k, v]) =>
                `<span style="display:inline-block;padding:1px 6px;margin:1px;background:#f8fafc;border-radius:3px;font-size:10px;font-family:monospace">${k}=${v}</span>`
            ).join(' ');
        }

        const modal = document.createElement('div');
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;justify-content:center;align-items:flex-start;padding:20px;overflow-y:auto';
        modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
        modal.innerHTML = `
        <div style="background:white;border-radius:12px;max-width:600px;width:100%;padding:0;box-shadow:0 20px 60px rgba(0,0,0,0.2);margin:20px auto;max-height:90vh;overflow-y:auto">
            <div style="padding:16px 20px;border-bottom:1px solid #e2e8f0;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;background:white;border-radius:12px 12px 0 0;z-index:1">
                <div>
                    <div style="font-size:15px;font-weight:700">&#128269; 날씨 데이터 검증</div>
                    <div style="font-size:11px;color:#64748b">${v.site?.name || ''} | ${v.timestamp ? new Date(v.timestamp).toLocaleString('ko-KR') : ''}</div>
                </div>
                <button onclick="this.closest('[style*=fixed]').remove()" style="background:none;border:none;font-size:20px;cursor:pointer;color:#64748b;padding:4px 8px">&times;</button>
            </div>
            <div style="padding:16px 20px;font-size:12px;line-height:1.7">

                <!-- 1. 최종 요약 -->
                <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;padding:12px;margin-bottom:14px">
                    <div style="font-weight:700;font-size:13px;margin-bottom:6px">&#9989; 최종 결과</div>
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <div><span style="color:#64748b">기온</span> <b>${s.temperature}°C</b></div>
                        <div><span style="color:#64748b">습도</span> <b>${s.humidity}%</b></div>
                        <div><span style="color:#64748b">풍속</span> <b>${s.wind_speed}m/s</b></div>
                        <div><span style="color:#64748b">체감</span> <b style="color:#dc2626">${s.apparent_temperature}°C</b></div>
                        <div><span style="color:#64748b">WBGT</span> <b>${s.wbgt}°C</b></div>
                        <div><span style="color:#64748b">단계</span> <b>${s.stage}</b></div>
                    </div>
                </div>

                <!-- 2. 좌표 & API 요청 -->
                <div style="margin-bottom:14px">
                    <div style="font-weight:700;margin-bottom:4px">&#128205; 좌표 변환 & API 요청</div>
                    <div style="background:#f8fafc;border-radius:6px;padding:8px 10px;font-size:11px;line-height:1.8">
                        <div>위경도: <b>${v.site?.latitude}, ${v.site?.longitude}</b> → 기상청 격자: <b>nx=${grid.nx}, ny=${grid.ny}</b></div>
                        <div>발표시각: <b>${req.base_date} ${req.base_time}</b> | 예보시각: <b>${raw.used_forecast_time || req.target_fcst_time}</b>${raw.is_fallback ? ' <span style="color:#d97706">(폴백)</span>' : ''}</div>
                    </div>
                </div>

                <!-- 3. KMA 원시 데이터 -->
                <div style="margin-bottom:14px">
                    <div style="font-weight:700;margin-bottom:4px">&#128225; 기상청 API 원시 데이터</div>
                    <table style="width:100%;border-collapse:collapse;font-size:11px;border:1px solid #e2e8f0;border-radius:6px">
                        <thead><tr style="background:#f8fafc"><th style="padding:4px 8px;text-align:left;border-bottom:1px solid #e2e8f0">코드</th><th style="padding:4px 8px;text-align:left;border-bottom:1px solid #e2e8f0">항목</th><th style="padding:4px 8px;text-align:left;border-bottom:1px solid #e2e8f0">값</th></tr></thead>
                        <tbody>${catHtml}</tbody>
                    </table>
                </div>

                <!-- 4. 체감온도 계산 -->
                <div style="margin-bottom:14px">
                    <div style="font-weight:700;margin-bottom:4px">&#127777; 체감온도 계산 과정</div>
                    <div style="background:#f8fafc;border-radius:6px;padding:8px 10px;font-size:11px;line-height:1.8">
                        <div>공식: <b>${hi.formula || '-'}</b></div>
                        <div>입력: 기온=<b>${hi.input_temperature}°C</b>, 습도=<b>${hi.input_humidity}%</b></div>
                        ${hi.note ? `<div style="color:#d97706">${hi.note}</div>` : ''}
                        ${hiDetail ? `<div style="margin-top:4px">계수별 값: ${hiDetail}</div>` : ''}
                        <div style="margin-top:4px;font-weight:600;color:#0066cc">결과: ${hi.result}°C${hi.raw_result ? ` (반올림 전: ${hi.raw_result})` : ''}</div>
                    </div>
                </div>

                <!-- 5. WBGT 계산 -->
                <div style="margin-bottom:14px">
                    <div style="font-weight:700;margin-bottom:4px">&#127777; WBGT 계산 과정</div>
                    <div style="background:#f8fafc;border-radius:6px;padding:8px 10px;font-size:11px;line-height:1.8">
                        <div>공식: <b>${wb.formula || '-'}</b></div>
                        <div>건구(Ta): <b>${wb.Ta_dry_bulb}°C</b> | 습구(Tw): <b>${wb.Tw_wet_bulb}°C</b> <span style="color:#64748b">(${wb.Tw_formula})</span></div>
                        <div>흑구(Tg): <b>${wb.Tg_globe}°C</b> <span style="color:#64748b">${wb.Tg_note || ''}</span></div>
                        <div style="font-weight:600;color:#0066cc">${wb.breakdown || ''} = ${wb.result}°C</div>
                    </div>
                </div>

                <!-- 6. 폭염 단계 판정 -->
                <div style="margin-bottom:14px">
                    <div style="font-weight:700;margin-bottom:4px">&#9888; 폭염 단계 판정</div>
                    <div style="background:#f8fafc;border-radius:6px;padding:8px 10px;font-size:11px">
                        <div>체감온도 <b>${st.apparent_temperature}°C</b> → <b style="font-size:13px">${st.determined_stage}</b></div>
                        <div style="margin-top:4px">${stageHtml}</div>
                    </div>
                </div>

                <!-- 7. 시간대별 예보 -->
                ${hourlyHtml}

                <!-- 8. 외부 비교 -->
                <div style="margin-top:14px;padding-top:12px;border-top:1px solid #e2e8f0">
                    <div style="font-weight:700;margin-bottom:6px">&#128279; 외부 비교 (직접 확인)</div>
                    <div style="display:flex;gap:6px;flex-wrap:wrap">
                        <a href="${links.naver_weather || '#'}" target="_blank" style="padding:6px 12px;background:#03c75a;color:white;border-radius:6px;font-size:11px;text-decoration:none;font-weight:600">네이버 날씨</a>
                        <a href="${links.kma_weather || '#'}" target="_blank" style="padding:6px 12px;background:#0066cc;color:white;border-radius:6px;font-size:11px;text-decoration:none;font-weight:600">기상청 관측</a>
                    </div>
                    <div style="margin-top:6px;font-size:10px;color:#94a3b8;line-height:1.6">
                        * 네이버/기상청 웹 표시값은 <b>관측값(실황)</b>이며, 본 시스템은 <b>단기예보 데이터</b>를 사용합니다.<br>
                        * 관측값과 예보값은 통상 1~3°C 차이가 발생할 수 있으며, 이는 정상적인 오차 범위입니다.<br>
                        * 격자(5km) 단위 예보이므로 정확한 지점 온도와 다를 수 있습니다.
                    </div>
                </div>
            </div>
        </div>`;
        document.body.appendChild(modal);
    } catch (e) {
        showToast('검증 실패: ' + e.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<span style="font-size:13px">&#128269;</span> 날씨 데이터 검증'; }
    }
}

function renderAlertBanner(stage, weather, siteName) {
    const banner = document.getElementById('alert-banner');
    if (!banner) return;

    const classMap = { 'stage_1_interest': 'interest', 'stage_2_caution': 'caution', 'stage_3_warning': 'warning', 'stage_4_danger': 'danger' };
    const iconMap = { 'stage_1_interest': '!', 'stage_2_caution': '!!', 'stage_3_warning': '!!!', 'stage_4_danger': 'X' };

    if (!stage) {
        banner.className = 'alert-banner safe';
        banner.innerHTML = `
            <div class="alert-icon">V</div>
            <div class="alert-content">
                <h2>정상 - 안전 작업 가능</h2>
                <p>${siteName} | 체감 ${weather.apparent_temperature}°C</p>
            </div>`;
        return;
    }

    banner.className = `alert-banner ${classMap[stage.stage_key] || 'safe'}`;
    banner.innerHTML = `
        <div class="alert-icon">${iconMap[stage.stage_key] || 'V'}</div>
        <div class="alert-content">
            <h2>폭염 ${stage.stage_name} 단계</h2>
            <p>${siteName} | 체감 ${weather.apparent_temperature}°C | ${stage.work_restriction}</p>
        </div>
        ${stage.stage_key === 'stage_4_danger' ? '<button class="btn btn-danger btn-sm" onclick="triggerMonitoring()">긴급 알림</button>' : ''}`;
}

function renderStageIndicator(stage) {
    const el = document.getElementById('stage-indicator');
    if (!el) return;

    const lvl = !stage ? 0 : stage.stage_key === 'stage_1_interest' ? 1 : stage.stage_key === 'stage_2_caution' ? 2 : stage.stage_key === 'stage_3_warning' ? 3 : 4;

    el.innerHTML = `
        <div class="stage-bar-wrap">
            <div class="stage-segment s1 ${lvl >= 1 ? 'active' : ''}"></div>
            <div class="stage-segment s2 ${lvl >= 2 ? 'active' : ''}"></div>
            <div class="stage-segment s3 ${lvl >= 3 ? 'active' : ''}"></div>
            <div class="stage-segment s4 ${lvl >= 4 ? 'active' : ''}"></div>
        </div>`;
}

function renderActions(stage) {
    const el = document.getElementById('actions-content');
    if (!el) return;

    if (!stage) {
        el.innerHTML = '<p style="text-align:center;color:var(--text-dim);padding:20px">특별 조치사항 없음</p>';
        return;
    }

    el.innerHTML = `
        <ul class="action-list">
            ${stage.actions.map(a => `<li>${a}</li>`).join('')}
        </ul>
        <div class="rest-badge"><strong>휴식:</strong> ${stage.rest_guideline}</div>
    `;
}

// ── 알림 이력 ──
async function loadAlertHistory() {
    try {
        state.alertHistory = await api('/api/alerts/history?limit=20');
        renderAlertHistory();
    } catch (e) {
        console.error('알림 이력 로딩 실패:', e);
    }
}

function renderAlertHistory() {
    const el = document.getElementById('alert-history');
    if (!el) return;

    if (state.alertHistory.length === 0) {
        el.innerHTML = '<p style="text-align:center;color:var(--text-dim)">알림 이력이 없습니다</p>';
        return;
    }

    const stageNames = { 'stage_1_interest': '관심', 'stage_2_caution': '주의', 'stage_3_warning': '경고', 'stage_4_danger': '위험' };
    const stageColors = { 'stage_1_interest': 'var(--interest)', 'stage_2_caution': 'var(--caution)', 'stage_3_warning': 'var(--warning)', 'stage_4_danger': 'var(--danger)' };

    el.innerHTML = state.alertHistory.map(log => {
        const name = stageNames[log.stage] || log.stage;
        const color = stageColors[log.stage] || 'var(--text-dim)';
        const ok = log.status === 'sent';
        return `
            <div class="log-item">
                <div class="time">${new Date(log.sent_at).toLocaleString('ko-KR')}</div>
                <div class="detail">
                    <span style="color:${ok ? 'var(--safe)' : 'var(--danger)'}">${ok ? 'V' : 'X'}</span>
                    <strong style="color:${color}">${name}</strong>
                    체감 ${log.apparent_temperature}°C
                </div>
            </div>`;
    }).join('');
}

// ── 통계 ──
async function loadStats() {
    try {
        const stats = await api('/api/alerts/stats?days=7');
        const el = document.getElementById('stats-content');
        if (el) {
            el.innerHTML = `
                <div class="stat-grid">
                    <div class="stat-box">
                        <div class="label">총 발송</div>
                        <div class="value">${stats.total}</div>
                    </div>
                    <div class="stat-box">
                        <div class="label">성공</div>
                        <div class="value" style="color:var(--safe)">${stats.sent}</div>
                    </div>
                    <div class="stat-box">
                        <div class="label">실패</div>
                        <div class="value" style="color:var(--danger)">${stats.failed}</div>
                    </div>
                    <div class="stat-box">
                        <div class="label">현장</div>
                        <div class="value">${state.sites.length}</div>
                    </div>
                </div>`;
        }
    } catch (e) {
        console.error('통계 로딩 실패:', e);
    }
}

// ── 수동 모니터링 트리거 ──
async function triggerMonitoring(siteIds = null) {
    const label = siteIds ? `${siteIds.length}개 선택 현장` : `${state.sites?.length || 0}개 전체 현장`;
    const progressEl = document.getElementById('send-progress');
    if (progressEl) {
        progressEl.style.display = 'block';
        progressEl.innerHTML = `<div style="display:flex;align-items:center;gap:8px">
            <div class="progress-spinner"></div>
            <span style="font-size:13px;color:var(--text-mid)">${label} 알림 발송 중... (현재 날씨 기준)</span>
        </div>`;
    }
    try {
        const result = await api('/api/monitor/trigger', {
            method: 'POST',
            body: siteIds ? JSON.stringify(siteIds) : undefined,
        });
        const msg = `${result.sites_checked}개 현장, ${result.alerts_sent}건 처리${result.alerts_skipped ? ` (${result.alerts_skipped}건 중복스킵)` : ''}`;
        if (progressEl) {
            progressEl.innerHTML = `<div style="font-size:13px;color:var(--safe);padding:4px 0">발송 완료 - ${msg}</div>`;
            setTimeout(() => { progressEl.style.display = 'none'; }, 5000);
        }
        // SMS 동시 발송
        let smsMsg = '';
        if (document.getElementById('sms-enabled')?.checked) {
            const smsResult = await sendSmsToSiteWorkers(siteIds, `[KEPCO 안전관리] 폭염 경보\n${result.sites_checked}개 현장 알림 발송됨. 앱에서 상세 확인하세요.`);
            if (smsResult) smsMsg = ` | SMS ${smsResult.sent}건`;
        }
        showToast(`발송 완료 - ${msg}${smsMsg}`, 'success');
        loadAlertHistory();
        loadStats();
    } catch (e) {
        if (progressEl) {
            progressEl.innerHTML = `<div style="color:var(--danger);font-size:13px">발송 실패: ${e.message}</div>`;
        }
        showToast('발송 실패: ' + e.message, 'error');
    }
}

// ── 모달 ──
function openModal(id) {
    document.getElementById(id).classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

// ── 현장 등록 탭 전환 ──
function switchSiteTab(tab) {
    const manualTab = document.getElementById('site-tab-manual');
    const excelTab = document.getElementById('site-tab-excel');
    const btnManual = document.getElementById('tab-manual');
    const btnExcel = document.getElementById('tab-excel');

    if (tab === 'manual') {
        manualTab.style.display = 'block';
        excelTab.style.display = 'none';
        btnManual.style.background = 'var(--kepco-light)';
        btnManual.style.color = 'white';
        btnExcel.style.background = 'var(--bg-card)';
        btnExcel.style.color = 'var(--text-secondary)';
    } else {
        manualTab.style.display = 'none';
        excelTab.style.display = 'block';
        btnExcel.style.background = 'var(--kepco-light)';
        btnExcel.style.color = 'white';
        btnManual.style.background = 'var(--bg-card)';
        btnManual.style.color = 'var(--text-secondary)';
    }
}

// ── 작업현장 등록 (직접 입력) ──
async function submitSite(e) {
    e.preventDefault();
    const form = e.target;
    const data = {
        name: form.site_name.value,
        address: form.site_address.value,
        latitude: parseFloat(form.site_lat.value),
        longitude: parseFloat(form.site_lng.value),
        work_intensity: form.site_intensity.value,
        is_outdoor: true,
    };

    try {
        await api('/api/sites', { method: 'POST', body: JSON.stringify(data) });
        closeModal('site-modal');
        form.reset();
        showToast('현장이 등록되었습니다.', 'success');
        loadSites();
    } catch (e) {
        showToast('등록 실패: ' + e.message, 'error');
    }
}

// ── 엑셀 업로드 ──
let excelData = null;  // 파싱된 엑셀 데이터

function handleExcelDrop(e) {
    e.preventDefault();
    e.currentTarget.style.borderColor = 'var(--border-color)';
    const file = e.dataTransfer.files[0];
    if (file) uploadExcelFile(file);
}

function handleExcelUpload(input) {
    const file = input.files[0];
    if (file) uploadExcelFile(file);
}

async function uploadExcelFile(file) {
    const area = document.getElementById('excel-upload-area');
    area.innerHTML = '<div style="padding:20px;color:var(--text-secondary)">파일 분석 중...</div>';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/upload/parse-excel', { method: 'POST', body: formData });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || '파일 처리 실패');
        }
        excelData = await res.json();
        renderExcelPreview(file.name);
    } catch (e) {
        area.innerHTML = `
            <div style="color:var(--stage-danger);padding:20px">
                <div style="font-size:15px;font-weight:600;margin-bottom:4px">파일 처리 실패</div>
                <div style="font-size:13px">${e.message}</div>
                <button class="btn btn-sm" style="margin-top:12px;background:var(--kepco-light);color:white" onclick="resetExcelUpload()">다시 시도</button>
            </div>`;
    }
}

function renderExcelPreview(filename) {
    document.getElementById('excel-upload-area').style.display = 'none';
    document.getElementById('excel-preview').style.display = 'block';
    document.getElementById('excel-info').textContent = `${filename} - ${excelData.total_rows}건`;

    // 컬럼 매핑 표시
    const mappingEl = document.getElementById('mapping-fields');
    const fields = [
        { key: 'name', label: '현장명' },
        { key: 'address', label: '주소' },
    ];
    mappingEl.innerHTML = fields.map(f => {
        const matchedCol = Object.entries(excelData.mapped_columns).find(([, v]) => v === f.key);
        const options = excelData.columns.map(c =>
            `<option value="${c}" ${matchedCol && matchedCol[0] === c ? 'selected' : ''}>${c}</option>`
        ).join('');
        return `
            <div style="display:flex;align-items:center;gap:6px">
                <span style="font-size:12px;min-width:50px;color:var(--text-secondary)">${f.label}:</span>
                <select data-field="${f.key}" style="flex:1;padding:4px 6px;background:rgba(255,255,255,0.05);border:1px solid var(--border-color);border-radius:4px;color:var(--text-primary);font-size:12px">
                    <option value="">(선택 안 함)</option>
                    ${options}
                </select>
            </div>`;
    }).join('');

    // 테이블 렌더링
    const table = document.getElementById('excel-table');
    const cols = excelData.columns.slice(0, 8); // 최대 8열만 표시
    let html = '<thead><tr>';
    html += '<th style="padding:6px 8px;background:rgba(41,128,185,0.2);border:1px solid var(--border-color);text-align:center;width:40px"><input type="checkbox" checked onchange="toggleAllRows(this)"></th>';
    cols.forEach(c => {
        const mapped = excelData.mapped_columns[c];
        const highlight = mapped ? 'background:rgba(41,128,185,0.3)' : 'background:rgba(41,128,185,0.2)';
        html += `<th style="padding:6px 8px;${highlight};border:1px solid var(--border-color);font-size:11px;white-space:nowrap">${c}${mapped ? ' *' : ''}</th>`;
    });
    html += '</tr></thead><tbody>';

    excelData.rows.forEach((row, i) => {
        html += `<tr>`;
        html += `<td style="padding:4px 8px;border:1px solid var(--border-color);text-align:center"><input type="checkbox" class="row-check" data-idx="${i}" checked></td>`;
        cols.forEach(c => {
            const val = row[c] || '';
            html += `<td style="padding:4px 8px;border:1px solid var(--border-color);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${val}">${val}</td>`;
        });
        html += '</tr>';
    });
    html += '</tbody>';
    table.innerHTML = html;

    // 추출된 작업자 표시
    const workerSection = document.getElementById('extracted-workers');
    if (workerSection && excelData.extracted_workers && excelData.extracted_workers.length > 0) {
        const workers = excelData.extracted_workers;
        workerSection.style.display = 'block';
        workerSection.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                <div style="font-size:12px;font-weight:600">자동 추출된 작업자 (${workers.length}명)</div>
                <label style="display:flex;align-items:center;gap:4px;font-size:11px;cursor:pointer">
                    <input type="checkbox" id="import-workers-check" checked style="width:auto"> 작업자도 함께 등록
                </label>
            </div>
            <div style="max-height:120px;overflow:auto;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px">
                <table style="width:100%;border-collapse:collapse">
                    <thead><tr>
                        <th style="padding:4px 8px;background:rgba(39,174,96,0.15);border:1px solid var(--border);text-align:left">이름</th>
                        <th style="padding:4px 8px;background:rgba(39,174,96,0.15);border:1px solid var(--border);text-align:left">전화번호</th>
                        <th style="padding:4px 8px;background:rgba(39,174,96,0.15);border:1px solid var(--border);text-align:left">출처</th>
                    </tr></thead>
                    <tbody>${workers.map(w => `<tr>
                        <td style="padding:3px 8px;border:1px solid var(--border)">${w.name}</td>
                        <td style="padding:3px 8px;border:1px solid var(--border)">${w.phone}</td>
                        <td style="padding:3px 8px;border:1px solid var(--border)">${w.source}</td>
                    </tr>`).join('')}</tbody>
                </table>
            </div>
        `;
    } else if (workerSection) {
        workerSection.style.display = 'none';
    }
}

function toggleAllRows(master) {
    document.querySelectorAll('.row-check').forEach(cb => cb.checked = master.checked);
}

function resetExcelUpload() {
    excelData = null;
    document.getElementById('excel-upload-area').style.display = 'block';
    document.getElementById('excel-upload-area').innerHTML = `
        <div style="font-size:36px;margin-bottom:8px;opacity:0.5">+</div>
        <div style="font-size:15px;font-weight:600">사전신고정보 파일을 드래그하거나 클릭하세요</div>
        <div style="font-size:12px;color:var(--text-secondary);margin-top:6px">지원 형식: .xls, .xlsx, .csv (최대 10MB)</div>
        <input type="file" id="excel-file" accept=".xls,.xlsx,.csv" style="display:none" onchange="handleExcelUpload(this)">`;
    document.getElementById('excel-preview').style.display = 'none';
}

function toggleLocationMode() {
    const mode = document.querySelector('input[name="location-mode"]:checked')?.value;
    document.getElementById('location-auto').style.display = mode === 'auto' ? 'block' : 'none';
    document.getElementById('location-manual').style.display = mode === 'manual' ? 'block' : 'none';
}

async function importSelectedSites() {
    if (!excelData) return;

    // 선택된 행 인덱스
    const checked = [...document.querySelectorAll('.row-check:checked')].map(cb => parseInt(cb.dataset.idx));
    if (checked.length === 0) {
        alert('등록할 현장을 선택하세요.');
        return;
    }

    // 매핑된 컬럼 확인
    const nameCol = document.querySelector('[data-field="name"]')?.value;
    const addrCol = document.querySelector('[data-field="address"]')?.value;

    if (!nameCol) {
        alert('현장명 컬럼을 선택하세요.');
        return;
    }

    const locationMode = document.querySelector('input[name="location-mode"]:checked')?.value || 'auto';
    const intensity = 'moderate';
    const branchOffice = state.branchOffice || '';

    let lat = 0, lng = 0;
    if (locationMode === 'manual') {
        lat = parseFloat(document.getElementById('bulk-lat').value) || 0;
        lng = parseFloat(document.getElementById('bulk-lng').value) || 0;
        if (!lat || !lng) {
            alert('좌표를 입력하세요.');
            return;
        }
    } else if (!addrCol) {
        alert('자동 좌표 변환을 사용하려면 주소 컬럼을 선택하세요.');
        return;
    }

    // 각 현장에 해당하는 작업자 매칭 (row_index 기준)
    const extractedWorkers = excelData.extracted_workers || [];

    const sites = checked.map(i => {
        const row = excelData.rows[i];
        const siteName = row[nameCol] || `현장 ${i + 1}`;
        // 이 행에서 추출된 작업자들
        const siteWorkers = extractedWorkers
            .filter(w => w.row_index === i)
            .map(w => ({ name: w.name, phone: w.phone }));
        return {
            name: siteName,
            address: addrCol ? (row[addrCol] || '') : '',
            latitude: lat,
            longitude: lng,
            work_intensity: intensity,
            branch_office: branchOffice,
            workers: siteWorkers,
        };
    }).filter(s => s.name.trim());

    if (sites.length === 0) {
        alert('등록할 유효한 현장이 없습니다.');
        return;
    }

    const btn = document.querySelector('#excel-preview .btn-primary');
    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = locationMode === 'auto'
                ? '<span class="progress-spinner" style="width:14px;height:14px;border-width:2px;display:inline-block;vertical-align:middle;margin-right:6px"></span>주소 변환 및 등록 중... (현장 ' + sites.length + '개)'
                : '<span class="progress-spinner" style="width:14px;height:14px;border-width:2px;display:inline-block;vertical-align:middle;margin-right:6px"></span>등록 중...';
        }

        const result = await api('/api/upload/import-sites', {
            method: 'POST',
            body: JSON.stringify({ sites }),
        });

        closeModal('site-modal');
        resetExcelUpload();

        let msg = `현장 ${result.created}건 등록 완료`;
        if (result.geocoded > 0) msg += ` (좌표 변환 ${result.geocoded}건)`;
        if (result.workers_assigned > 0) msg += `\n작업자 ${result.workers_created}명 등록, ${result.workers_assigned}명 배정`;
        if (result.errors > 0) msg += `\n실패 ${result.errors}건`;
        if (result.error_details?.length > 0) {
            const first3 = result.error_details.slice(0, 3).map(e => `${e.name}: ${e.error}`).join(', ');
            msg += ` (${first3})`;
        }
        showToast(msg, result.errors > 0 ? 'warning' : 'success', 6000);
        await loadSites();
    } catch (e) {
        showToast('일괄 등록 실패: ' + e.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = '일괄 등록';
        }
    }
}

function getCurrentLocationBulk() {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
        (pos) => {
            document.getElementById('bulk-lat').value = pos.coords.latitude.toFixed(6);
            document.getElementById('bulk-lng').value = pos.coords.longitude.toFixed(6);
        },
        () => alert('위치를 가져올 수 없습니다.'),
    );
}

// ── 작업자 등록 탭 전환 ──
function switchWorkerTab(tab) {
    const manualTab = document.getElementById('worker-tab-manual');
    const excelTab = document.getElementById('worker-tab-excel');
    const btnManual = document.getElementById('worker-tab-manual-btn');
    const btnExcel = document.getElementById('worker-tab-excel-btn');

    if (tab === 'manual') {
        manualTab.style.display = 'block';
        excelTab.style.display = 'none';
        btnManual.style.background = 'var(--kepco-light)';
        btnManual.style.color = 'white';
        btnExcel.style.background = 'var(--bg-card)';
        btnExcel.style.color = 'var(--text-secondary)';
    } else {
        manualTab.style.display = 'none';
        excelTab.style.display = 'block';
        btnExcel.style.background = 'var(--kepco-light)';
        btnExcel.style.color = 'white';
        btnManual.style.background = 'var(--bg-card)';
        btnManual.style.color = 'var(--text-secondary)';
    }
}

// ── 작업자 엑셀 업로드 ──
let workerExcelData = null;

function handleWorkerExcelDrop(e) {
    e.preventDefault();
    e.currentTarget.style.borderColor = 'var(--border-color)';
    const file = e.dataTransfer.files[0];
    if (file) uploadWorkerExcelFile(file);
}

function handleWorkerExcelUpload(input) {
    const file = input.files[0];
    if (file) uploadWorkerExcelFile(file);
}

async function uploadWorkerExcelFile(file) {
    const area = document.getElementById('worker-excel-upload-area');
    area.innerHTML = '<div style="padding:20px;color:var(--text-secondary)">파일 분석 중...</div>';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/upload/parse-worker-excel', { method: 'POST', body: formData });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || '파일 처리 실패');
        }
        workerExcelData = await res.json();
        renderWorkerExcelPreview(file.name);
    } catch (e) {
        area.innerHTML = `
            <div style="color:var(--stage-danger);padding:20px">
                <div style="font-size:15px;font-weight:600;margin-bottom:4px">파일 처리 실패</div>
                <div style="font-size:13px">${e.message}</div>
                <button class="btn btn-sm" style="margin-top:12px;background:var(--kepco-light);color:white" onclick="resetWorkerExcelUpload()">다시 시도</button>
            </div>`;
    }
}

function renderWorkerExcelPreview(filename) {
    document.getElementById('worker-excel-upload-area').style.display = 'none';
    document.getElementById('worker-excel-preview').style.display = 'block';
    document.getElementById('worker-excel-info').textContent = `${filename} - ${workerExcelData.total_rows}명`;

    // 컬럼 매핑 표시
    const mappingEl = document.getElementById('worker-mapping-fields');
    const fields = [
        { key: 'name', label: '이름' },
        { key: 'phone', label: '전화번호' },
        { key: 'department', label: '소속' },
        { key: 'team', label: '작업반' },
    ];
    mappingEl.innerHTML = fields.map(f => {
        const matchedCol = Object.entries(workerExcelData.mapped_columns).find(([, v]) => v === f.key);
        const options = workerExcelData.columns.map(c =>
            `<option value="${c}" ${matchedCol && matchedCol[0] === c ? 'selected' : ''}>${c}</option>`
        ).join('');
        return `
            <div style="display:flex;align-items:center;gap:6px">
                <span style="font-size:12px;min-width:55px;color:var(--text-secondary)">${f.label}:</span>
                <select data-worker-field="${f.key}" style="flex:1;padding:4px 6px;background:rgba(255,255,255,0.05);border:1px solid var(--border-color);border-radius:4px;color:var(--text-primary);font-size:12px">
                    <option value="">(선택 안 함)</option>
                    ${options}
                </select>
            </div>`;
    }).join('');

    // 테이블 렌더링
    const table = document.getElementById('worker-excel-table');
    const cols = workerExcelData.columns.slice(0, 8);
    let html = '<thead><tr>';
    html += '<th style="padding:6px 8px;background:rgba(41,128,185,0.2);border:1px solid var(--border-color);text-align:center;width:40px"><input type="checkbox" checked onchange="toggleAllWorkerRows(this)"></th>';
    cols.forEach(c => {
        const mapped = workerExcelData.mapped_columns[c];
        const highlight = mapped ? 'background:rgba(41,128,185,0.3)' : 'background:rgba(41,128,185,0.2)';
        html += `<th style="padding:6px 8px;${highlight};border:1px solid var(--border-color);font-size:11px;white-space:nowrap">${c}${mapped ? ' *' : ''}</th>`;
    });
    html += '</tr></thead><tbody>';

    workerExcelData.rows.forEach((row, i) => {
        html += `<tr>`;
        html += `<td style="padding:4px 8px;border:1px solid var(--border-color);text-align:center"><input type="checkbox" class="worker-row-check" data-idx="${i}" checked></td>`;
        cols.forEach(c => {
            const val = row[c] || '';
            html += `<td style="padding:4px 8px;border:1px solid var(--border-color);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${val}">${val}</td>`;
        });
        html += '</tr>';
    });
    html += '</tbody>';
    table.innerHTML = html;
}

function toggleAllWorkerRows(master) {
    document.querySelectorAll('.worker-row-check').forEach(cb => cb.checked = master.checked);
}

function resetWorkerExcelUpload() {
    workerExcelData = null;
    document.getElementById('worker-excel-upload-area').style.display = 'block';
    document.getElementById('worker-excel-upload-area').innerHTML = `
        <div style="font-size:32px;margin-bottom:8px;opacity:0.3">+</div>
        <div style="font-size:14px;font-weight:600">작업자 명단 파일 선택</div>
        <div style="font-size:12px;color:var(--text-faint);margin-top:4px">.xls .xlsx .csv</div>
        <input type="file" id="worker-excel-file" accept=".xls,.xlsx,.csv" style="display:none" onchange="handleWorkerExcelUpload(this)">`;
    document.getElementById('worker-excel-preview').style.display = 'none';
}

async function importSelectedWorkers() {
    if (!workerExcelData) return;

    const checked = [...document.querySelectorAll('.worker-row-check:checked')].map(cb => parseInt(cb.dataset.idx));
    if (checked.length === 0) {
        alert('등록할 작업자를 선택하세요.');
        return;
    }

    const nameCol = document.querySelector('[data-worker-field="name"]')?.value;
    const phoneCol = document.querySelector('[data-worker-field="phone"]')?.value;
    const deptCol = document.querySelector('[data-worker-field="department"]')?.value;
    const teamCol = document.querySelector('[data-worker-field="team"]')?.value;
    const bulkVulnerable = document.getElementById('worker-bulk-vulnerable')?.checked || false;

    if (!nameCol) {
        alert('이름 컬럼을 선택하세요.');
        return;
    }
    if (!phoneCol) {
        alert('전화번호 컬럼을 선택하세요.');
        return;
    }

    const workers = checked.map(i => {
        const row = workerExcelData.rows[i];
        return {
            name: (row[nameCol] || '').trim(),
            phone: (row[phoneCol] || '').trim(),
            department: deptCol ? (row[deptCol] || '').trim() : '',
            team: teamCol ? (row[teamCol] || '').trim() : '',
            is_vulnerable: bulkVulnerable,
        };
    }).filter(w => w.name && w.phone);

    if (workers.length === 0) {
        alert('등록할 유효한 작업자가 없습니다.\n이름과 전화번호가 있는 행이 필요합니다.');
        return;
    }

    try {
        const result = await api('/api/upload/import-workers', {
            method: 'POST',
            body: JSON.stringify({ workers }),
        });
        let msg = `작업자 ${result.created}명 등록 완료`;
        if (result.skipped > 0) msg += ` (중복 ${result.skipped}명 건너뜀)`;
        if (result.errors > 0) msg += ` (실패 ${result.errors}건)`;
        showToast(msg, result.errors > 0 ? 'warning' : 'success');
        closeModal('worker-modal');
        resetWorkerExcelUpload();
        switchWorkerTab('manual');
        loadSites();
    } catch (e) {
        showToast('일괄 등록 실패: ' + e.message, 'error');
    }
}

// ── 작업자 등록 (직접 입력) ──
async function submitWorker(e) {
    e.preventDefault();
    const form = e.target;
    const data = {
        name: form.worker_name.value,
        phone: form.worker_phone.value,
        department: form.worker_dept.value,
        team: form.worker_team.value,
        is_vulnerable: form.worker_vulnerable.checked,
    };

    try {
        await api('/api/workers', { method: 'POST', body: JSON.stringify(data) });
        closeModal('worker-modal');
        form.reset();
        showToast('작업자가 등록되었습니다.', 'success');
        loadSites();
    } catch (e) {
        showToast('등록 실패: ' + e.message, 'error');
    }
}

// ── 작업자 목록 ──
async function loadWorkers() {
    const el = document.getElementById('worker-list-content');
    if (!el) return;
    try {
        const workers = await api('/api/workers');
        if (workers.length === 0) {
            el.innerHTML = '<p style="text-align:center;color:var(--text-dim)">등록된 작업자가 없습니다</p>';
            return;
        }
        el.innerHTML = `
            <div style="font-size:12px;color:var(--text-dim);margin-bottom:6px">총 ${workers.length}명</div>
            ${workers.map(w => `
                <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border)">
                    <div>
                        <span style="font-weight:600">${w.name}</span>
                        <span style="color:var(--text-dim);margin-left:6px;font-size:11px">${w.phone}</span>
                    </div>
                    ${w.is_vulnerable ? '<span style="font-size:10px;padding:1px 6px;background:rgba(231,76,60,0.15);color:#e74c3c;border-radius:8px">취약</span>' : ''}
                </div>
            `).join('')}
        `;
    } catch (e) {
        el.innerHTML = '<p style="text-align:center;color:var(--text-dim)">조회 실패</p>';
    }
}

// ── 데이터 초기화 ──
async function resetAllData() {
    if (!confirm('모든 작업현장과 작업자 데이터를 삭제합니다.\n정말 초기화하시겠습니까?')) return;
    try {
        await api('/api/reset', { method: 'POST' });
        showToast('초기화 완료', 'success');
        state.allSitesWeather = [];
        state.selectedSiteId = null;
        state.currentWeather = null;
        await loadSites();
        loadStats();
        loadAlertHistory();
        filterSites('all');
    } catch (e) {
        showToast('초기화 실패: ' + e.message, 'error');
    }
}

// ── 모의 날씨 테스트 ──
let mockMode = false;

function toggleMockWeather() {
    mockMode = !mockMode;
    const btn = document.getElementById('mock-toggle-btn');
    if (mockMode) {
        btn.style.background = '#e74c3c';
        btn.style.color = 'white';
        btn.textContent = '모의 테스트 ON';
        loadMockWeather();
    } else {
        btn.style.background = '';
        btn.style.color = '#e74c3c';
        btn.textContent = '모의 테스트';
        const mockBanner = document.getElementById('mock-data-banner');
        if (mockBanner) mockBanner.style.display = 'none';
        loadAllSitesWeather();
    }
}

async function loadMockWeather() {
    const progressEl = document.getElementById('send-progress');
    try {
        if (progressEl) {
            progressEl.style.display = 'block';
            progressEl.innerHTML = '<div style="display:flex;align-items:center;gap:8px"><div class="progress-spinner"></div><span style="font-size:13px;color:#e74c3c">모의 테스트 데이터 생성 중...</span></div>';
        }
        const data = await api('/api/weather/status-all/mock');
        if (progressEl) progressEl.style.display = 'none';
        state.allSitesWeather = data.sites;

        const statusEl = document.getElementById('weather-status');
        if (statusEl) {
            statusEl.innerHTML = '<span style="color:#e74c3c;font-weight:700">모의 테스트 모드</span>';
        }
        const timeEl = document.getElementById('weather-checked-time');
        if (timeEl) timeEl.textContent = '가상 데이터 (실제 날씨 아님)';

        // 모의 데이터 배너 표시
        let mockBanner = document.getElementById('mock-data-banner');
        if (!mockBanner) {
            mockBanner = document.createElement('div');
            mockBanner.id = 'mock-data-banner';
            mockBanner.style.cssText = 'background:repeating-linear-gradient(45deg,#fff3cd,#fff3cd 10px,#fff8e1 10px,#fff8e1 20px);border:2px solid #e74c3c;border-radius:8px;padding:10px 14px;margin:8px 0;font-size:12px;color:#991b1b;text-align:center;font-weight:600;line-height:1.6';
            mockBanner.innerHTML = '&#9888; 현재 <span style="color:#e74c3c;text-decoration:underline">모의 테스트 모드</span>입니다<br><span style="font-weight:400;font-size:11px;color:#7c2d12">아래 모든 현장/작업자/날씨 데이터는 <b>가상 데이터</b>이며 실제와 무관합니다.<br>이름, 전화번호, 공사명은 모두 허구입니다. SMS 발송 시 실제 발송되지 않습니다.</span>';
            const statsEl = document.getElementById('stats-content');
            if (statsEl) statsEl.parentElement.insertBefore(mockBanner, statsEl);
        }
        mockBanner.style.display = 'block';

        if (data.sites.length > 0) {
            const top = data.sites.find(s => s.weather) || data.sites[0];
            if (top && top.weather) {
                state.selectedSiteId = top.site_id;
                renderWeatherDashboard({
                    work_site_name: top.site_name,
                    weather: top.weather,
                    stage: top.stage,
                    wbgt_work_recommendation: top.wbgt_recommendation,
                });
            }
        }
        renderSiteList();
        filterSites(currentFilter);
    } catch (e) {
        console.error('모의 테스트 실패:', e);
        if (progressEl) {
            progressEl.innerHTML = '<div style="color:var(--danger);font-size:13px">모의 테스트 실패: ' + e.message + '</div>';
            setTimeout(() => { progressEl.style.display = 'none'; }, 5000);
        }
    }
}

// ── 폭염 시뮬레이션 ──
function toggleTestMode() {
    const on = document.getElementById('test-mode-toggle')?.checked;
    document.getElementById('test-mode-panel').style.display = on ? 'block' : 'none';
}

function updateSimTemp() {
    const temp = document.getElementById('sim-temp').value;
    const el = document.getElementById('sim-temp-value');
    el.textContent = `${temp}°C`;
    const colors = { 25:'#27ae60', 33:'#FFC107', 35:'#FF9800', 38:'#FF5722', 41:'#D32F2F' };
    let color = '#27ae60';
    for (const [t, c] of Object.entries(colors)) { if (temp >= t) color = c; }
    el.style.color = color;
}

function runSimulation() {
    // 미리보기 전용 - 실제 발송 없음, 클라이언트에서 단계 계산
    const temp = parseFloat(document.getElementById('sim-temp').value);
    const humidity = parseFloat(document.getElementById('sim-humidity').value);
    const resultEl = document.getElementById('sim-result');

    // 체감온도 근사 계산 (Heat Index)
    let apparentTemp = temp;
    if (temp >= 27 && humidity >= 40) {
        const T = temp, R = humidity;
        apparentTemp = -8.784 + 1.611*T + 2.339*R - 0.146*T*R
            - 0.013*T*T - 0.016*R*R + 0.002*T*T*R + 0.001*T*R*R - 0.000004*T*T*R*R;
        apparentTemp = Math.round(apparentTemp * 10) / 10;
    }

    // 단계 판정
    const stages = [
        { min: 41, name: '위험', color: '#D32F2F', bg: 'rgba(211,47,47,0.1)', actions: ['즉시 작업 중지', '근로자 대피', '긴급 연락망 가동'] },
        { min: 38, name: '경고', color: '#FF5722', bg: 'rgba(255,87,34,0.1)', actions: ['1시간 주기 휴식', '무거운 작업 금지', '음료 수시 섭취'] },
        { min: 35, name: '주의', color: '#FF9800', bg: 'rgba(255,152,0,0.1)', actions: ['2시간 주기 휴식', '그늘 휴식공간 확보', '음료 비치'] },
        { min: 33, name: '관심', color: '#FFC107', bg: 'rgba(255,193,7,0.1)', actions: ['건강 상태 확인', '충분한 수분 섭취 권고'] },
    ];
    const stage = stages.find(s => apparentTemp >= s.min);
    const workerCount = (state.allSitesWeather || []).reduce((sum, s) => sum + (s.worker_count || 0), 0);

    let html = `<div style="padding:12px;border-radius:8px;margin-top:4px;background:${stage ? stage.bg : 'rgba(16,185,129,0.1)'}">`;
    html += `<div style="font-weight:700;font-size:14px;color:${stage ? stage.color : 'var(--safe)'};margin-bottom:6px">`;
    html += stage ? `폭염 ${stage.name} 단계` : '정상 (발송 대상 아님)';
    html += `</div>`;
    html += `<div style="font-size:13px;margin-bottom:4px">기온 ${temp}°C, 습도 ${humidity}% → <strong>체감온도 ${apparentTemp}°C</strong></div>`;
    if (stage) {
        html += `<div style="font-size:12px;color:var(--text-mid);margin-bottom:4px">발송 대상: ${state.sites?.length || 0}개 현장, ${workerCount}명</div>`;
        html += `<ul style="margin:6px 0 0;padding-left:18px;font-size:12px;color:var(--text-mid)">`;
        stage.actions.forEach(a => html += `<li>${a}</li>`);
        html += `</ul>`;
    } else {
        html += `<div style="font-size:12px;color:var(--text-dim)">체감온도 33°C 미만은 관심 단계에 해당하지 않아 알림이 발송되지 않습니다.</div>`;
    }
    html += `</div>`;
    resultEl.innerHTML = html;
}

// ── 현재 위치 가져오기 ──
function getCurrentLocation() {
    if (!navigator.geolocation) {
        alert('위치 서비스를 지원하지 않는 브라우저입니다.');
        return;
    }
    navigator.geolocation.getCurrentPosition(
        (pos) => {
            document.getElementById('site_lat').value = pos.coords.latitude.toFixed(6);
            document.getElementById('site_lng').value = pos.coords.longitude.toFixed(6);
        },
        () => alert('위치를 가져올 수 없습니다.'),
    );
}

// ── 현장 선택 발송 ──
// ── 단계별 필터 ──
let currentFilter = 'all';

function filterSites(stage) {
    currentFilter = 'all'; // 공사현황은 항상 전체 표시
    let sites = state.allSitesWeather || [];

    // 사업소 필터 (로그인한 사업소 및 사업소 미지정 현장 포함)
    if (state.branchOffice) {
        sites = sites.filter(s => !s.branch_office || s.branch_office === state.branchOffice || s.branch_office.includes(state.branchOffice) || state.branchOffice.includes(s.branch_office));
    }

    renderAllSitesOverview(sites);

    // 알림 발송 목록도 갱신
    renderAlertSendList();
}

function showSelectBar() {
    document.getElementById('site-select-bar').style.display = 'flex';
    document.querySelectorAll('.site-check').forEach(cb => cb.style.display = 'inline');
    updateSelectedCount();
}
function hideSelectBar() {
    document.getElementById('site-select-bar').style.display = 'none';
    document.querySelectorAll('.site-check').forEach(cb => { cb.checked = false; cb.style.display = 'none'; });
    document.getElementById('select-all-sites').checked = false;
}
function toggleSelectAllSites(master) {
    document.querySelectorAll('.site-check').forEach(cb => cb.checked = master.checked);
    updateSelectedCount();
}
function updateSelectedCount() {
    const checked = document.querySelectorAll('.site-check:checked').length;
    const total = document.querySelectorAll('.site-check').length;
    const el = document.getElementById('selected-count');
    el.textContent = `${checked}/${total}개 선택`;
    el.style.color = checked > 0 ? 'var(--kepco)' : 'var(--text-faint)';
}
async function triggerSelectedSites() {
    const siteIds = [...document.querySelectorAll('.site-check:checked')].map(cb => parseInt(cb.dataset.siteId));
    if (siteIds.length === 0) {
        showToast('발송할 현장을 선택하세요.', 'warning');
        return;
    }
    hideSelectBar();
    showAlertPreview(siteIds);
}

// ── 알림 발송 목록 필터 ──
let alertFilter = 'all';

function filterAlertList(stage) {
    alertFilter = stage;
    document.querySelectorAll('[data-filter-group="alert"]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.stage === stage);
    });
    renderAlertSendList();
}

function getAlertFilteredSites() {
    const stageKeyMap = {
        'danger': 'stage_4_danger', 'warning': 'stage_3_warning',
        'caution': 'stage_2_caution', 'interest': 'stage_1_interest',
    };
    let sites = state.allSitesWeather || [];
    if (state.branchOffice) {
        sites = sites.filter(s => !s.branch_office || s.branch_office === state.branchOffice || s.branch_office.includes(state.branchOffice) || state.branchOffice.includes(s.branch_office));
    }
    if (alertFilter === 'all') return sites;
    if (alertFilter === 'safe') return sites.filter(s => !s.stage);
    return sites.filter(s => s.stage?.key === stageKeyMap[alertFilter]);
}

function renderAlertSendList() {
    const listEl = document.getElementById('alert-send-list');
    if (!listEl) return;

    const filtered = getAlertFilteredSites();
    const allSites = state.allSitesWeather || [];

    // 카운트 업데이트
    const countEl = document.getElementById('alert-filter-count');
    if (countEl) countEl.textContent = `${filtered.length}/${allSites.length}개`;

    // 알림 필터 버튼 카운트
    let sites = allSites;
    if (state.branchOffice) {
        sites = sites.filter(s => !s.branch_office || s.branch_office === state.branchOffice || s.branch_office.includes(state.branchOffice) || state.branchOffice.includes(s.branch_office));
    }
    const counts = { danger: 0, warning: 0, caution: 0, interest: 0, safe: 0 };
    sites.forEach(s => {
        if (!s.stage) counts.safe++;
        else if (s.stage.key === 'stage_4_danger') counts.danger++;
        else if (s.stage.key === 'stage_3_warning') counts.warning++;
        else if (s.stage.key === 'stage_2_caution') counts.caution++;
        else counts.interest++;
    });
    document.querySelectorAll('[data-filter-group="alert"]').forEach(btn => {
        const stg = btn.dataset.stage;
        if (stg !== 'all') {
            const cnt = counts[stg] || 0;
            const label = btn.dataset.label || stg;
            const temp = btn.dataset.temp ? ` ${btn.dataset.temp}°` : '';
            btn.textContent = cnt > 0 ? `${label}${temp}(${cnt})` : `${label}${temp}`;
        }
    });

    if (filtered.length === 0) {
        listEl.innerHTML = '<p style="color:var(--text-dim);text-align:center;padding:16px">해당 단계의 현장이 없습니다</p>';
        updateAlertSelectedCount();
        return;
    }

    listEl.innerHTML = filtered.map(s => {
        const stg = s.stage;
        const color = stg ? stg.color : '#27ae60';
        const label = stg ? stg.name : '정상';
        const temp = s.weather ? s.weather.apparent_temperature : '-';
        const workers = s.workers || [];

        return `<div style="border-bottom:1px solid var(--border-light,#edf2f7);padding:10px 16px">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                <input type="checkbox" class="alert-site-check" data-site-id="${s.site_id}" onchange="updateAlertSelectedCount()" style="width:auto" checked>
                <span class="badge" style="background:${color};font-size:10px">${label}</span>
                <span style="font-weight:600;font-size:13px;flex:1">${s.site_name}</span>
                <span style="font-size:13px;font-weight:700;color:${color}">체감 ${temp}°</span>
            </div>
            ${workers.length > 0 ? `<div style="display:flex;flex-wrap:wrap;gap:2px 10px;padding-left:28px">
                ${workers.map(w => {
                    const vulnTag = w.is_vulnerable ? '<span style="font-size:9px;padding:0 3px;background:rgba(231,76,60,0.12);color:#e74c3c;border-radius:3px">취약</span>' : '';
                    return `<span style="font-size:11px"><span style="font-weight:500">${w.name}</span> <span style="color:var(--text-faint)">${w.phone}</span>${vulnTag}</span>`;
                }).join('')}
            </div>` : '<div style="font-size:11px;color:var(--text-faint);padding-left:28px">작업자 없음</div>'}
            ${stg && stg.work_restriction && stg.work_restriction !== '없음' ? `<div style="margin-top:3px;font-size:11px;color:${color};padding-left:28px">${stg.work_restriction}</div>` : ''}
        </div>`;
    }).join('');

    updateAlertSelectedCount();
}

function toggleAlertSelectAll(master) {
    document.querySelectorAll('.alert-site-check').forEach(cb => cb.checked = master.checked);
    updateAlertSelectedCount();
}

function updateAlertSelectedCount() {
    const checked = document.querySelectorAll('.alert-site-check:checked').length;
    const total = document.querySelectorAll('.alert-site-check').length;
    const el = document.getElementById('alert-selected-count');
    if (el) {
        const workerCount = getAlertSelectedWorkerCount();
        el.textContent = checked > 0 ? `${checked}개 현장 / ${workerCount}명` : '';
    }
    const el2 = document.getElementById('alert-selected-count-bottom');
    if (el2) {
        const workerCount2 = checked > 0 ? getAlertSelectedWorkerCount() : 0;
        el2.textContent = checked > 0 ? `${checked}개 현장 / ${workerCount2}명 선택됨` : '';
    }
    const selectAll = document.getElementById('alert-select-all');
    if (selectAll) selectAll.checked = total > 0 && checked === total;
}

function getAlertSelectedWorkerCount() {
    const siteIds = [...document.querySelectorAll('.alert-site-check:checked')].map(cb => parseInt(cb.dataset.siteId));
    const sites = state.allSitesWeather || [];
    return siteIds.reduce((sum, id) => {
        const s = sites.find(x => x.site_id === id);
        return sum + (s?.workers?.length || 0);
    }, 0);
}

async function sendSelectedAlerts() {
    const siteIds = [...document.querySelectorAll('.alert-site-check:checked')].map(cb => parseInt(cb.dataset.siteId));
    if (siteIds.length === 0) {
        showToast('발송할 현장을 선택하세요.', 'warning');
        return;
    }
    const workerCount = getAlertSelectedWorkerCount();
    if (!confirm(`${siteIds.length}개 현장, ${workerCount}명 작업자에게 푸시 알림을 발송합니다.\n계속하시겠습니까?`)) return;
    await triggerMonitoring(siteIds);
}

async function sendSelectedSms() {
    const siteIds = [...document.querySelectorAll('.alert-site-check:checked')].map(cb => parseInt(cb.dataset.siteId));
    if (siteIds.length === 0) {
        showToast('발송할 현장을 선택하세요.', 'warning');
        return;
    }
    const workerCount = getAlertSelectedWorkerCount();
    const customMsg = document.getElementById('sms-message')?.value?.trim();
    const msg = customMsg || `[KEPCO 안전관리] 폭염 알림\n선택된 ${siteIds.length}개 현장에 폭염 주의 알림이 발송되었습니다. 안전수칙을 준수해주세요.`;

    if (!confirm(`${siteIds.length}개 현장, ${workerCount}명 작업자에게 SMS를 발송합니다.\n\n내용: ${msg}\n\n계속하시겠습니까?`)) return;

    // 발송 버튼 비활성화 + 로딩
    const btn = document.querySelector('#sms-message').parentElement.querySelector('button');
    const origText = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = '<span class="progress-spinner" style="width:14px;height:14px;border-width:2px;display:inline-block;vertical-align:middle;margin-right:4px"></span>발송 중...';

    try {
        const result = await sendSmsToSiteWorkers(siteIds, msg);
        if (result) {
            const successCount = result.sent || 0;
            const failCount = result.failed || 0;
            const total = successCount + failCount;
            const isAllFail = successCount === 0 && failCount > 0;
            const bgColor = isAllFail ? '#fef2f2' : (failCount > 0 ? '#fffbeb' : '#f0fdf4');
            const headerColor = isAllFail ? '#dc2626' : (failCount > 0 ? '#d97706' : '#16a34a');
            const headerIcon = isAllFail ? '&#10060;' : (failCount > 0 ? '&#9888;&#65039;' : '&#9989;');
            const headerText = isAllFail ? 'SMS 발송 실패' : (failCount > 0 ? 'SMS 발송 일부 실패' : 'SMS 발송 완료');

            let resultHtml = `<div style="padding:14px 16px;border-top:1px solid var(--border);background:${bgColor}">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
                    <span style="font-size:18px">${headerIcon}</span>
                    <span style="font-weight:700;font-size:14px;color:${headerColor};flex:1">${headerText}</span>
                    <button onclick="this.closest('[style*=border-top]').remove()" style="background:none;border:1px solid var(--border);color:var(--text-dim);padding:4px 14px;border-radius:6px;font-size:12px;cursor:pointer;flex-shrink:0">닫기</button>
                </div>
                <div style="display:flex;gap:16px;margin-bottom:6px">
                    <div style="text-align:center;padding:8px 16px;background:white;border-radius:8px;border:1px solid #e2e8f0">
                        <div style="font-size:11px;color:var(--text-dim)">총 발송</div>
                        <div style="font-size:20px;font-weight:700">${total}</div>
                    </div>
                    <div style="text-align:center;padding:8px 16px;background:white;border-radius:8px;border:1px solid #e2e8f0">
                        <div style="font-size:11px;color:var(--text-dim)">성공</div>
                        <div style="font-size:20px;font-weight:700;color:#16a34a">${successCount}</div>
                    </div>
                    <div style="text-align:center;padding:8px 16px;background:white;border-radius:8px;border:1px solid #e2e8f0">
                        <div style="font-size:11px;color:var(--text-dim)">실패</div>
                        <div style="font-size:20px;font-weight:700;color:${failCount > 0 ? '#dc2626' : 'var(--text-dim)'}">${failCount}</div>
                    </div>
                </div>`;

            // 전체 에러 사유 (API 오류 등)
            if (result.error) {
                resultHtml += `<div style="background:white;border:1px solid #fecaca;border-radius:8px;padding:10px 12px;margin:8px 0;font-size:12px;color:#991b1b;line-height:1.6">
                    <div style="font-weight:600;margin-bottom:4px">
                        &#128680; 실패 원인${result.error_code ? ' <span style="font-weight:400;color:#b91c1c;font-size:11px">[' + result.error_code + ']</span>' : ''}
                    </div>
                    <div>${result.error}</div>
                </div>`;
            }

            // 개별 작업자별 상세 결과
            if (result.details && result.details.length > 0) {
                const failedDetails = result.details.filter(d => d.status !== 'sent');
                const sentDetails = result.details.filter(d => d.status === 'sent');

                resultHtml += `<div style="margin-top:8px">
                    <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:4px;cursor:pointer"
                         onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none';this.querySelector('span').textContent=this.nextElementSibling.style.display==='none'?'&#9654;':'&#9660;'">
                        <span>&#9660;</span> 작업자별 상세 결과 (${result.details.length}명)
                    </div>
                    <div style="max-height:240px;overflow-y:auto;border:1px solid #e2e8f0;border-radius:8px;background:white">
                        <table style="width:100%;border-collapse:collapse;font-size:11px">
                            <thead>
                                <tr style="background:#f8fafc;position:sticky;top:0">
                                    <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #e2e8f0;font-weight:600">상태</th>
                                    <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #e2e8f0;font-weight:600">현장</th>
                                    <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #e2e8f0;font-weight:600">이름</th>
                                    <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #e2e8f0;font-weight:600">전화번호</th>
                                    <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #e2e8f0;font-weight:600">사유</th>
                                </tr>
                            </thead>
                            <tbody>`;

                // 실패 건을 먼저 표시
                failedDetails.forEach(d => {
                    resultHtml += `<tr style="background:#fef2f2">
                        <td style="padding:5px 8px;border-bottom:1px solid #f1f5f9"><span style="color:#dc2626;font-weight:700">&#10005; 실패</span></td>
                        <td style="padding:5px 8px;border-bottom:1px solid #f1f5f9">${d.site || '-'}</td>
                        <td style="padding:5px 8px;border-bottom:1px solid #f1f5f9;font-weight:500">${d.name || '-'}</td>
                        <td style="padding:5px 8px;border-bottom:1px solid #f1f5f9;font-family:monospace">${d.phone || '-'}</td>
                        <td style="padding:5px 8px;border-bottom:1px solid #f1f5f9;color:#dc2626">${d.error || '알 수 없는 오류'}</td>
                    </tr>`;
                });
                // 성공 건
                sentDetails.forEach(d => {
                    resultHtml += `<tr>
                        <td style="padding:5px 8px;border-bottom:1px solid #f1f5f9"><span style="color:#16a34a">&#10003; 성공</span></td>
                        <td style="padding:5px 8px;border-bottom:1px solid #f1f5f9">${d.site || '-'}</td>
                        <td style="padding:5px 8px;border-bottom:1px solid #f1f5f9;font-weight:500">${d.name || '-'}</td>
                        <td style="padding:5px 8px;border-bottom:1px solid #f1f5f9;font-family:monospace">${d.phone || '-'}</td>
                        <td style="padding:5px 8px;border-bottom:1px solid #f1f5f9;color:#16a34a">발송 완료</td>
                    </tr>`;
                });

                resultHtml += `</tbody></table></div></div>`;
            }

            resultHtml += `</div>`;

            const statsEl = document.getElementById('stats-content');
            if (statsEl) statsEl.insertAdjacentHTML('beforebegin', resultHtml);

            // 하단 통계 즉시 업데이트
            const statsEl2 = document.getElementById('stats-content');
            if (statsEl2) {
                statsEl2.innerHTML = `
                    <div class="stat-grid">
                        <div class="stat-box">
                            <div class="label">총 발송</div>
                            <div class="value">${total}</div>
                        </div>
                        <div class="stat-box">
                            <div class="label">성공</div>
                            <div class="value" style="color:var(--safe)">${successCount}</div>
                        </div>
                        <div class="stat-box">
                            <div class="label">실패</div>
                            <div class="value" style="color:${failCount > 0 ? 'var(--danger)' : 'var(--text-dim)'}">${failCount}</div>
                        </div>
                        <div class="stat-box">
                            <div class="label">현장</div>
                            <div class="value">${getAlertFilteredSites().filter(s => document.querySelector(`.alert-site-check[data-site-id="${s.site_id}"]:checked`)).length || state.sites.length}</div>
                        </div>
                    </div>`;
            }

            showToast(`SMS ${successCount}건 성공${failCount > 0 ? `, ${failCount}건 실패` : ''}`, failCount > 0 ? 'warning' : 'success');
            document.getElementById('sms-message').value = '';
        }
    } catch (e) {
        const errorHtml = `<div style="padding:14px 16px;border-top:1px solid var(--border);background:#fef2f2">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
                <span style="font-size:18px">&#10060;</span>
                <span style="font-weight:700;font-size:14px;color:#dc2626;flex:1">SMS 발송 실패</span>
                <button onclick="this.closest('[style*=border-top]').remove()" style="background:none;border:1px solid var(--border);color:var(--text-dim);padding:4px 14px;border-radius:6px;font-size:12px;cursor:pointer;flex-shrink:0">닫기</button>
            </div>
            <div style="background:white;border:1px solid #fecaca;border-radius:8px;padding:10px 12px;font-size:12px;color:#991b1b;line-height:1.6">
                <div style="font-weight:600;margin-bottom:4px">&#128680; 오류 사유:</div>
                <div>${e.message}</div>
                <div style="margin-top:8px;color:var(--text-dim);font-size:11px">
                    SMS API 설정을 확인해주세요.<br>
                    (.env 파일의 SMS_APP_KEY, SMS_SECRET_KEY, SMS_SENDER_PHONE)
                </div>
            </div>
        </div>`;

        const statsEl = document.getElementById('stats-content');
        if (statsEl) statsEl.insertAdjacentHTML('beforebegin', errorHtml);

        showToast('SMS 발송 실패', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = origText;
    }
}

// 날씨 데이터 로드 후 알림 목록도 갱신
const _origFilterSites = filterSites;
// (filterSites 호출 시 알림 목록도 함께 갱신)

// ── PWA 앱 설치 ──
