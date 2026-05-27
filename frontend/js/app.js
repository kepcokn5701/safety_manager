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
    loadSites();
    loadAlertHistory();
    loadStats();
    initServiceWorker();

    // 1분마다 자동 갱신
    state.refreshInterval = setInterval(() => {
        if (state.selectedSiteId) {
            loadWeather(state.selectedSiteId);
        }
        loadAlertHistory();
    }, 60000);
});

// ── Service Worker & 웹 푸시 ──
async function initServiceWorker() {
    if (!('serviceWorker' in navigator)) {
        console.warn('Service Worker를 지원하지 않는 브라우저입니다.');
        return;
    }

    try {
        const reg = await navigator.serviceWorker.register('/sw.js');
        console.log('Service Worker 등록 성공:', reg.scope);

        // 기존 구독 확인
        const sub = await reg.pushManager.getSubscription();
        if (sub) {
            state.pushSubscription = sub;
            updatePushButton(true);
        }
    } catch (e) {
        console.error('Service Worker 등록 실패:', e);
    }
}

async function togglePushSubscription() {
    if (state.pushSubscription) {
        await unsubscribePush();
    } else {
        await subscribePush();
    }
}

async function subscribePush() {
    try {
        // VAPID 공개키 가져오기
        const { public_key } = await api('/api/push/vapid-key');
        if (!public_key) {
            alert('푸시 알림 설정이 완료되지 않았습니다.\n관리자에게 VAPID 키 설정을 요청하세요.');
            return;
        }

        const reg = await navigator.serviceWorker.ready;

        // 브라우저 알림 권한 요청
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') {
            alert('알림 권한이 거부되었습니다.\n브라우저 설정에서 알림을 허용해주세요.');
            return;
        }

        // 푸시 구독
        const sub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(public_key),
        });

        // 전화번호 입력 받기 (구독 식별용)
        const phone = prompt('알림을 받을 전화번호를 입력하세요:\n(작업자 등록 시 입력한 번호와 동일해야 합니다)', '010-');
        if (!phone) {
            await sub.unsubscribe();
            return;
        }

        // 서버에 구독 등록
        await api('/api/push/subscribe', {
            method: 'POST',
            body: JSON.stringify({
                phone: phone,
                subscription: sub.toJSON(),
            }),
        });

        state.pushSubscription = sub;
        updatePushButton(true);
        alert('푸시 알림이 활성화되었습니다!\n폭염 주의 단계 이상 시 알림을 받게 됩니다.');

    } catch (e) {
        console.error('푸시 구독 실패:', e);
        alert('푸시 알림 설정 실패: ' + e.message);
    }
}

async function unsubscribePush() {
    try {
        if (state.pushSubscription) {
            await state.pushSubscription.unsubscribe();
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
    if (subscribed) {
        btn.textContent = '알림 ON';
        btn.style.background = 'rgba(39, 174, 96, 0.8)';
        btn.style.borderColor = '#27ae60';
    } else {
        btn.textContent = '알림 허용';
        btn.style.background = 'rgba(255,255,255,0.2)';
        btn.style.borderColor = 'rgba(255,255,255,0.3)';
    }
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
        if (state.sites.length > 0) {
            selectSite(state.sites[0].id);
        }
    } catch (e) {
        console.error('현장 목록 로딩 실패:', e);
    }
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
        <div class="site-item ${state.selectedSiteId === site.id ? 'active' : ''}"
             onclick="selectSite(${site.id})"
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

// ── 날씨 조회 ──
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
    const { weather, stage, wbgt_work_recommendation, work_site_name } = data;

    // 상단 배너
    renderAlertBanner(stage, weather, work_site_name);

    // 날씨 카드
    const weatherEl = document.getElementById('weather-content');
    if (weatherEl) {
        weatherEl.innerHTML = `
            <div class="weather-grid">
                <div class="weather-item">
                    <div class="label">현재 기온</div>
                    <div class="value">${weather.temperature}<span class="unit">°C</span></div>
                </div>
                <div class="weather-item">
                    <div class="label">체감온도</div>
                    <div class="value ${weather.apparent_temperature >= 33 ? 'temp-highlight' : ''}">${weather.apparent_temperature}<span class="unit">°C</span></div>
                </div>
                <div class="weather-item">
                    <div class="label">습도</div>
                    <div class="value">${weather.humidity}<span class="unit">%</span></div>
                </div>
                <div class="weather-item">
                    <div class="label">풍속</div>
                    <div class="value">${weather.wind_speed}<span class="unit">m/s</span></div>
                </div>
            </div>
            <div style="margin-top:16px;padding:12px;background:rgba(255,255,255,0.05);border-radius:8px">
                <div style="font-size:12px;color:var(--text-secondary)">WBGT 추정값</div>
                <div style="font-size:24px;font-weight:700">${weather.wbgt_estimated}<span style="font-size:14px;color:var(--text-secondary)">°C</span></div>
                <div style="font-size:13px;margin-top:4px;color:var(--stage-caution)">${wbgt_work_recommendation || ''}</div>
            </div>
        `;
    }

    // 단계 인디케이터
    renderStageIndicator(stage);

    // 조치사항
    renderActions(stage);
}

function renderAlertBanner(stage, weather, siteName) {
    const banner = document.getElementById('alert-banner');
    if (!banner) return;

    if (!stage) {
        banner.className = 'alert-banner safe';
        banner.innerHTML = `
            <div class="alert-icon">O</div>
            <div class="alert-content">
                <h2>정상 - 안전 작업 가능</h2>
                <p>${siteName} | 체감온도 ${weather.apparent_temperature}°C</p>
            </div>
        `;
        return;
    }

    const classMap = {
        'stage_1_interest': 'interest',
        'stage_2_caution': 'caution',
        'stage_3_warning': 'warning',
        'stage_4_danger': 'danger',
    };

    const iconMap = {
        'stage_1_interest': '!',
        'stage_2_caution': '!!',
        'stage_3_warning': '!!!',
        'stage_4_danger': 'X',
    };

    banner.className = `alert-banner ${classMap[stage.stage_key] || 'safe'}`;
    banner.innerHTML = `
        <div class="alert-icon">${iconMap[stage.stage_key] || 'O'}</div>
        <div class="alert-content">
            <h2>폭염 ${stage.stage_name} 단계</h2>
            <p>${siteName} | 체감온도 ${weather.apparent_temperature}°C | ${stage.work_restriction}</p>
        </div>
        ${stage.stage_key === 'stage_4_danger' ? '<button class="btn btn-danger" onclick="triggerMonitoring()">긴급 알림 발송</button>' : ''}
    `;
}

function renderStageIndicator(stage) {
    const el = document.getElementById('stage-indicator');
    if (!el) return;

    const activeLevel = !stage ? 0 :
        stage.stage_key === 'stage_1_interest' ? 1 :
        stage.stage_key === 'stage_2_caution' ? 2 :
        stage.stage_key === 'stage_3_warning' ? 3 : 4;

    el.innerHTML = `
        <div class="stage-indicator">
            <div class="stage-bar s1 ${activeLevel >= 1 ? 'active' : ''}"></div>
            <div class="stage-bar s2 ${activeLevel >= 2 ? 'active' : ''}"></div>
            <div class="stage-bar s3 ${activeLevel >= 3 ? 'active' : ''}"></div>
            <div class="stage-bar s4 ${activeLevel >= 4 ? 'active' : ''}"></div>
        </div>
        <div class="stage-labels">
            <span>관심 33°C</span>
            <span>주의 35°C</span>
            <span>경고 38°C</span>
            <span>위험 41°C</span>
        </div>
    `;
}

function renderActions(stage) {
    const el = document.getElementById('actions-content');
    if (!el) return;

    if (!stage) {
        el.innerHTML = '<p style="padding:12px;color:var(--text-secondary)">현재 특별 조치사항 없음</p>';
        return;
    }

    el.innerHTML = `
        <ul class="action-list">
            ${stage.actions.map(a => `<li>${a}</li>`).join('')}
        </ul>
        <div style="padding:12px;margin-top:8px;background:rgba(255,255,255,0.05);border-radius:8px;font-size:13px">
            <strong>휴식 기준:</strong> ${stage.rest_guideline}
        </div>
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
        el.innerHTML = '<p style="padding:20px;text-align:center;color:var(--text-secondary)">알림 이력이 없습니다.</p>';
        return;
    }

    el.innerHTML = state.alertHistory.map(log => {
        const stageNames = {
            'stage_1_interest': '관심',
            'stage_2_caution': '주의',
            'stage_3_warning': '경고',
            'stage_4_danger': '위험',
        };
        const stageName = stageNames[log.stage] || log.stage;
        const statusIcon = log.status === 'sent' ? '[전송]' : '[실패]';

        return `
            <div class="alert-history-item">
                <div class="time">${new Date(log.sent_at).toLocaleString('ko-KR')}</div>
                <div class="detail">
                    ${statusIcon} 폭염 <strong>${stageName}</strong> |
                    체감온도 ${log.apparent_temperature}°C | ${log.channel}
                </div>
            </div>
        `;
    }).join('');
}

// ── 통계 ──
async function loadStats() {
    try {
        const stats = await api('/api/alerts/stats?days=7');
        const el = document.getElementById('stats-content');
        if (el) {
            el.innerHTML = `
                <div class="weather-grid">
                    <div class="weather-item">
                        <div class="label">총 발송 (7일)</div>
                        <div class="value">${stats.total}</div>
                    </div>
                    <div class="weather-item">
                        <div class="label">성공</div>
                        <div class="value" style="color:var(--stage-safe)">${stats.sent}</div>
                    </div>
                    <div class="weather-item">
                        <div class="label">실패</div>
                        <div class="value" style="color:var(--stage-danger)">${stats.failed}</div>
                    </div>
                    <div class="weather-item">
                        <div class="label">현장 수</div>
                        <div class="value">${state.sites.length}</div>
                    </div>
                </div>
            `;
        }
    } catch (e) {
        console.error('통계 로딩 실패:', e);
    }
}

// ── 수동 모니터링 트리거 ──
async function triggerMonitoring() {
    try {
        const result = await api('/api/monitor/trigger', { method: 'POST' });
        alert(`모니터링 완료\n점검 현장: ${result.sites_checked}개\n알림 발송: ${result.alerts_sent}건`);
        loadAlertHistory();
        loadStats();
    } catch (e) {
        alert('모니터링 실행 실패: ' + e.message);
    }
}

// ── 모달 ──
function openModal(id) {
    document.getElementById(id).classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

// ── 작업현장 등록 ──
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
        loadSites();
    } catch (e) {
        alert('등록 실패: ' + e.message);
    }
}

// ── 작업자 등록 ──
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
        alert('작업자가 등록되었습니다.');
    } catch (e) {
        alert('등록 실패: ' + e.message);
    }
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

// ── PWA 앱 설치 ──
let deferredPrompt = null;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    // 이전에 닫은 적 없으면 배너 표시
    if (!sessionStorage.getItem('install-dismissed')) {
        document.getElementById('install-banner').style.display = 'block';
    }
});

async function installApp() {
    if (!deferredPrompt) {
        alert('이 브라우저에서는 앱 설치를 지원하지 않습니다.\n\n모바일 Chrome/Samsung Internet:\n메뉴 > "홈 화면에 추가"\n\niPhone Safari:\n공유 버튼 > "홈 화면에 추가"');
        return;
    }
    deferredPrompt.prompt();
    const result = await deferredPrompt.userChoice;
    if (result.outcome === 'accepted') {
        document.getElementById('install-banner').style.display = 'none';
    }
    deferredPrompt = null;
}

function dismissInstall() {
    document.getElementById('install-banner').style.display = 'none';
    sessionStorage.setItem('install-dismissed', '1');
}

// 이미 설치된 경우 배너 숨김
window.addEventListener('appinstalled', () => {
    document.getElementById('install-banner').style.display = 'none';
    deferredPrompt = null;
});
