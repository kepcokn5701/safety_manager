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
        // VAPID 공개키 가져오기 (서버가 자동 생성/관리)
        const { public_key } = await api('/api/push/vapid-key');
        if (!public_key) {
            alert('서버 설정 오류. 관리자에게 문의하세요.');
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

        // 서버에 구독 등록 (전화번호 입력 불필요)
        await api('/api/push/subscribe', {
            method: 'POST',
            body: JSON.stringify({ subscription: sub.toJSON() }),
        });

        state.pushSubscription = sub;
        updatePushButton(true);

    } catch (e) {
        console.error('푸시 구독 실패:', e);
        alert('알림 설정 실패: ' + e.message);
    }
}

async function unsubscribePush() {
    try {
        if (state.pushSubscription) {
            const endpoint = state.pushSubscription.endpoint;
            await state.pushSubscription.unsubscribe();
            // 서버에도 해제 알림
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

    const lat = parseFloat(document.getElementById('bulk-lat').value) || 37.5665;
    const lng = parseFloat(document.getElementById('bulk-lng').value) || 126.9780;
    const intensity = document.getElementById('bulk-intensity').value;

    const sites = checked.map(i => {
        const row = excelData.rows[i];
        return {
            name: row[nameCol] || `현장 ${i + 1}`,
            address: addrCol ? (row[addrCol] || '') : '',
            latitude: lat,
            longitude: lng,
            work_intensity: intensity,
        };
    }).filter(s => s.name.trim());

    if (sites.length === 0) {
        alert('등록할 유효한 현장이 없습니다.');
        return;
    }

    try {
        const result = await api('/api/upload/import-sites', {
            method: 'POST',
            body: JSON.stringify({ sites }),
        });
        alert(`등록 완료!\n성공: ${result.created}건${result.errors > 0 ? `\n실패: ${result.errors}건` : ''}`);
        closeModal('site-modal');
        resetExcelUpload();
        switchSiteTab('manual');
        loadSites();
    } catch (e) {
        alert('일괄 등록 실패: ' + e.message);
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
