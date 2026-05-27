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

// 푸시 알림 수신
self.addEventListener('push', (event) => {
    console.log('[SW] 푸시 알림 수신');

    let data = { title: 'KEPCO 안전관리', body: '알림이 도착했습니다.' };

    try {
        data = event.data.json();
    } catch (e) {
        data.body = event.data ? event.data.text() : data.body;
    }

    const stageColors = {
        '관심': '#FFC107',
        '주의': '#FF9800',
        '경고': '#FF5722',
        '위험': '#D32F2F',
    };

    const options = {
        body: data.body,
        icon: data.icon || '/static/icon-192.png',
        badge: data.badge || '/static/badge-72.png',
        tag: data.tag || 'heat-alert',
        renotify: true,
        requireInteraction: data.data?.stage === '위험',
        vibrate: data.data?.stage === '위험'
            ? [300, 100, 300, 100, 300]
            : [200, 100, 200],
        actions: [
            { action: 'view', title: '대시보드 확인' },
            { action: 'dismiss', title: '닫기' },
        ],
        data: data.data || {},
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options)
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
