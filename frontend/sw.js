/**
 * Service Worker - 웹 푸시 알림 수신 처리
 * 브라우저가 꺼져 있어도 알림을 수신할 수 있게 해줌
 */

self.addEventListener('install', (event) => {
    console.log('[SW] Service Worker 설치됨');
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    console.log('[SW] Service Worker 활성화됨');
    event.waitUntil(self.clients.claim());
});

// 단계별 아이콘 매핑
const stageIconMap = {
    '관심': '/static/icons/alert-interest.svg',
    '주의': '/static/icons/alert-caution.svg',
    '경고': '/static/icons/alert-warning.svg',
    '위험': '/static/icons/alert-danger.svg',
};

// 푸시 알림 수신
self.addEventListener('push', (event) => {
    console.log('[SW] 푸시 알림 수신');

    let data = { title: 'KEPCO 안전관리', body: '알림이 도착했습니다.' };

    try {
        data = event.data.json();
    } catch (e) {
        data.body = event.data ? event.data.text() : data.body;
    }

    const stage = data.data?.stage;
    const icon = data.icon || stageIconMap[stage] || '/static/icons/icon-192.svg';

    const options = {
        body: data.body,
        icon: icon,
        badge: data.badge || '/static/icons/badge-72.svg',
        tag: data.tag || 'heat-alert',
        renotify: true,
        requireInteraction: stage === '위험',
        vibrate: stage === '위험'
            ? [300, 100, 300, 100, 300]
            : [200, 100, 200],
        actions: [
            { action: 'view', title: '대시보드 확인' },
            { action: 'dismiss', title: '닫기' },
        ],
        data: data.data || {},
    };

    event.waitUntil(
        Promise.all([
            self.registration.showNotification(data.title, options),
            // 열려 있는 앱 화면에 인앱 팝업 표시를 위해 메시지 전달
            self.clients.matchAll({ type: 'window', includeUncontrolled: true })
                .then(clients => {
                    const rawType = data.data?.type || 'worker_alert';
                    const msgType = rawType === 'admin_summary' ? 'ADMIN_SUMMARY' : rawType === 'notice' ? 'NOTICE' : 'PUSH_RECEIVED';
                    clients.forEach(client => {
                        client.postMessage({
                            type: msgType,
                            title: data.title,
                            body: data.body,
                            stage: data.data?.stage || stage,
                            temperature: data.data?.temperature,
                            site: data.data?.site,
                            site_id: data.data?.site_id,
                            actions: data.data?.actions,
                            sent_count: data.data?.sent_count,
                            total_count: data.data?.total_count,
                        });
                    });
                }),
        ])
    );
});

// 알림 클릭 처리
self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    if (event.action === 'dismiss') return;

    const url = event.notification.data?.url || '/';

    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then((clients) => {
                // 이미 열려있는 창이 있으면 포커스
                for (const client of clients) {
                    if (client.url.includes(self.location.origin)) {
                        return client.focus();
                    }
                }
                // 없으면 새 창 열기
                return self.clients.openWindow(url);
            })
    );
});
