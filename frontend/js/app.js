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
    loadWorkers();
    loadAlertHistory();
    loadStats();
    initServiceWorker();

    // 1분마다 자동 갱신
    state.refreshInterval = setInterval(() => {
        if (state.sites.length > 0) {
            loadAllSitesWeather();
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

        // 기존 구독이 있으면 서버에 재등록 (서버 재시작 대응)
        const sub = await reg.pushManager.getSubscription();
        if (sub) {
            state.pushSubscription = sub;
            updatePushButton(true);
            api('/api/push/subscribe', {
                method: 'POST',
                body: JSON.stringify({ subscription: sub.toJSON() }),
            }).catch(() => {});
        }

        // 모바일 + PWA 미설치 + 처음 방문 → 설치 배너 표시
        if (isMobile() && !isPWA() && !sessionStorage.getItem('install-dismissed')) {
            const banner = document.getElementById('install-banner');
            if (banner) banner.style.display = 'block';
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
            body: JSON.stringify({ subscription: sub.toJSON() }),
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
    try {
        const data = await api('/api/weather/status-all');
        state.allSitesWeather = data.sites;
        renderAllSitesOverview(data.sites);

        // 헤더에 조회 시간 표시
        const firstWithTime = data.sites.find(s => s.checked_at);
        if (firstWithTime) {
            const timeEl = document.getElementById('weather-checked-time');
            if (timeEl) {
                timeEl.textContent = `기상청 ${new Date(firstWithTime.checked_at).toLocaleString('ko-KR', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'})} 기준`;
            }
        }

        // 첫 번째 현장 또는 가장 위험한 현장을 상세 표시
        if (data.sites.length > 0) {
            const top = data.sites[0];
            if (top.weather) {
                state.selectedSiteId = top.site_id;
                renderSiteList();
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
    } catch (e) {
        console.error('전체 현장 날씨 조회 실패:', e);
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
        container.innerHTML = '<p style="padding:20px;text-align:center;color:var(--text-secondary)">등록된 현장이 없습니다.</p>';
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
        const w = s.weather;
        const isSelected = state.selectedSiteId === s.site_id;

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
                    <div style="font-weight:600;font-size:14px;color:var(--text, #1a1a2e);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${s.site_name}</div>
                    <div style="font-size:11px;color:var(--text-dim, #8896a6);margin-top:2px">${s.address || ''}</div>
                    ${s.worker_count > 0 ? `<div style="font-size:11px;color:var(--kepco, #0066cc);margin-top:1px">작업자 ${s.worker_count}명${s.workers?.some(w=>w.is_vulnerable) ? ' (취약 포함)' : ''}</div>` : ''}
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
                </div>
            </div>
            ${stg && stg.key !== 'stage_1_interest' ? `<div style="margin-top:6px;font-size:12px;color:${color}">${stg.work_restriction}</div>` : ''}
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
            </div>`;
    }

    renderStageIndicator(stage);
    renderActions(stage);
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
        loadSites();
    } catch (e) {
        alert('등록 실패: ' + e.message);
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
    const intensity = document.getElementById('bulk-intensity').value;

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
            workers: siteWorkers,
        };
    }).filter(s => s.name.trim());

    if (sites.length === 0) {
        alert('등록할 유효한 현장이 없습니다.');
        return;
    }

    try {
        const btn = document.querySelector('#excel-preview .btn-primary');
        if (btn) {
            btn.disabled = true;
            btn.textContent = locationMode === 'auto' ? '주소 변환 및 등록 중...' : '등록 중...';
        }

        const result = await api('/api/upload/import-sites', {
            method: 'POST',
            body: JSON.stringify({ sites }),
        });

        let msg = `[현장] ${result.created}건 등록`;
        if (result.geocoded > 0) msg += ` (좌표 변환 ${result.geocoded}건)`;
        if (result.workers_assigned > 0) msg += `\n[작업자] ${result.workers_created}명 신규등록, ${result.workers_assigned}명 현장 배정`;
        if (result.errors > 0) msg += `\n[실패] ${result.errors}건`;

        if (result.error_details?.length > 0) {
            const first3 = result.error_details.slice(0, 3).map(e => `  - ${e.name}: ${e.error}`).join('\n');
            msg += `\n\n실패 상세:\n${first3}`;
        }
        alert(msg);
        closeModal('site-modal');
        resetExcelUpload();
        loadSites();
        loadWorkers();
    } catch (e) {
        alert('일괄 등록 실패: ' + e.message);
    } finally {
        const btn = document.querySelector('#excel-preview .btn-primary');
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
        let msg = `등록 완료!\n성공: ${result.created}명`;
        if (result.skipped > 0) msg += `\n중복 건너뜀: ${result.skipped}명`;
        if (result.errors > 0) msg += `\n실패: ${result.errors}건`;
        alert(msg);
        closeModal('worker-modal');
        resetWorkerExcelUpload();
        switchWorkerTab('manual');
    } catch (e) {
        alert('일괄 등록 실패: ' + e.message);
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
        alert('작업자가 등록되었습니다.');
    } catch (e) {
        alert('등록 실패: ' + e.message);
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
        alert('초기화 완료');
        loadSites();
        loadWorkers();
        loadStats();
        loadAlertHistory();
    } catch (e) {
        alert('초기화 실패: ' + e.message);
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

async function runSimulation() {
    const temp = document.getElementById('sim-temp').value;
    const humidity = document.getElementById('sim-humidity').value;
    const resultEl = document.getElementById('sim-result');
    resultEl.innerHTML = '<span style="color:var(--text-dim)">시뮬레이션 실행 중... (알림 발송 포함)</span>';

    try {
        const result = await api(`/api/monitor/simulate?temperature=${temp}&humidity=${humidity}`, { method: 'POST' });
        let html = `<div style="padding:10px;background:rgba(231,76,60,0.08);border-radius:8px;margin-top:8px">`;
        html += `<div style="font-weight:700;margin-bottom:4px">시뮬레이션 결과 (기온 ${temp}°C, 습도 ${humidity}%)</div>`;
        html += `<div>점검 현장: ${result.sites_checked}개</div>`;
        html += `<div>알림 발송: ${result.alerts_sent}건</div>`;
        if (result.errors > 0) html += `<div style="color:#e74c3c">실패: ${result.errors}건</div>`;
        html += `</div>`;
        resultEl.innerHTML = html;
        loadAlertHistory();
        loadStats();
    } catch (e) {
        resultEl.innerHTML = `<span style="color:#e74c3c">시뮬레이션 실패: ${e.message}</span>`;
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
