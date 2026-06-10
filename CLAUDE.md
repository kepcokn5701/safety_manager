# KEPCO 폭염 안전관리 시스템 (Safety Manager)

## 프로젝트 개요

한국전력공사(KEPCO) 경남본부 안전재난부에서 운영하는 **옥외 공사현장 폭염 안전관리 시스템**입니다.
기상청 날씨 데이터를 기반으로 공사현장의 폭염 위험도를 모니터링하고, 작업자에게 SMS/웹푸시로 경보를 발송합니다.

## 기술 스택

| 영역 | 기술 |
|------|------|
| 백엔드 | FastAPI + SQLAlchemy (async) + APScheduler |
| DB | SQLite (로컬) / PostgreSQL (Vercel) |
| 프론트엔드 | Vanilla JS + CSS (PWA) |
| 외부 API | 기상청 단기예보, 카카오맵 Geocoding, NHN Cloud SMS |
| 알림 | 웹 푸시 (VAPID/pywebpush), SMS (NHN Cloud) |
| 배포 | 로컬 Windows (START.bat) / Vercel (서버리스) |

## 파일 구조

```
safety_manager/
├── backend/
│   ├── app.py                 # FastAPI 메인 (라우트, 스케줄러, SMS 자동발송)
│   ├── config.py              # .env 로드 + Settings
│   ├── dependencies.py        # DI (WeatherProvider, NotificationSender)
│   ├── models/
│   │   ├── database.py        # SQLAlchemy 엔진/세션
│   │   ├── models.py          # ORM (Worker, WorkSite, AlertLog, WeatherLog 등 7개 테이블)
│   │   └── schemas.py         # Pydantic 스키마
│   ├── routers/
│   │   ├── weather.py         # 날씨 조회/검증 (격자 캐시 병렬 조회)
│   │   ├── alerts.py          # 알림 이력/통계
│   │   ├── workers.py         # 작업자/현장 CRUD
│   │   ├── push.py            # 웹 푸시 구독/발송
│   │   └── upload.py          # 엑셀 업로드/파싱/일괄등록
│   ├── services/
│   │   ├── kma_provider.py    # 기상청 API (위경도→격자 변환 포함)
│   │   ├── weather_service.py # 체감온도(Heat Index) + WBGT 계산
│   │   ├── alert_service.py   # SmsSender(NHN Cloud) + KakaoAlimTalk + Console
│   │   ├── push_service.py    # 웹 푸시 발송 (VAPID)
│   │   ├── repository.py      # DB 접근 계층
│   │   ├── excel_parser.py    # 사전신고 엑셀 파싱
│   │   ├── geocoding.py       # 카카오맵 주소→좌표
│   │   └── vapid_manager.py   # VAPID 키 관리 (자동생성/DB저장)
│   └── scheduler/
│       └── monitor.py         # HeatWaveMonitor (15분 자동 + 수동 트리거)
├── frontend/
│   ├── index.html             # 메인 대시보드
│   ├── manual.html            # 사용 매뉴얼 (안전관리자용 + 개발자용 탭)
│   ├── js/app.js              # 전체 프론트 로직 (~3000줄)
│   ├── sw.js                  # Service Worker (PWA, 푸시)
│   ├── css/style.css          # 스타일
│   └── *.dat                  # HTML 백업 (보안SW 삭제 대응)
├── config/thresholds.json     # 폭염 단계 기준값 (31/33/35/38°C)
├── START.bat / STOP.bat       # 서버 실행/종료
├── INSTALL.bat / REPAIR.bat   # 설치/복구
├── .env.example               # 환경변수 템플릿
└── requirements.txt           # Python 의존성
```

## DB 스키마 (7개 테이블)

- **workers**: 작업자 (이름, 전화번호, 소속, 취약 여부)
- **work_sites**: 공사현장 (주소, 좌표, 사업소, 작업강도)
- **work_site_workers**: 현장↔작업자 M:N 매핑
- **weather_logs**: 날씨 기록 (기온, 습도, 풍속, 체감온도, WBGT, 단계)
- **alert_logs**: 알림 이력 (작업자별 발송 성공/실패)
- **push_subscriptions**: 웹 푸시 구독 (브라우저 엔드포인트)
- **system_settings**: 시스템 설정 (VAPID 키 등)

## 주요 API 엔드포인트

### 날씨
- `GET /api/weather/status-all` - 전체 현장 날씨 (격자 캐시 병렬 조회)
- `GET /api/weather/cached/{site_id}` - DB 캐시 (API 호출 없음)
- `GET /api/weather/verify/{site_id}` - 계산 과정 검증

### SMS
- `POST /api/sms/send` - SMS 일괄 발송
- `POST /api/sms/test` - 테스트 발송
- `GET /api/sms/auto-schedule` - 자동 발송 스케줄 (10시/13시)

### 엑셀 업로드
- `POST /api/upload/parse-excel` - 엑셀 파싱 미리보기
- `POST /api/upload/import-sites` - 현장+작업자 일괄 등록 (자동 지오코딩)

### 시스템
- `POST /api/monitor/trigger` - 수동 알림 발송 (캐시된 날씨 사용)
- `POST /api/reset` - 데이터 초기화
- `GET /api/branch-offices` - 사업소 목록
- `GET /health` - DB 타입, 서버 상태

## 데이터 흐름

```
사전신고 엑셀 → 주소 → 카카오맵 Geocoding → WGS84 좌표
                                                    ↓
                                        Lambert 변환 → 기상청 격자 (nx, ny)
                                                    ↓
                                        기상청 API → 기온, 습도, 풍속
                                                    ↓
                                        Heat Index → 체감온도 → 폭염 단계 판정
                                                    ↓
                                        SMS / 웹 푸시 → 작업자에게 경보
```

## 폭염 단계 (config/thresholds.json)

| 단계 | 체감온도 | 조치 |
|------|---------|------|
| 관심 | 31°C+ | 수분 섭취 권고 |
| 주의 | 33°C+ | 2시간 작업/20분 휴식 |
| 경고 | 35°C+ | 무거운 작업 금지 |
| 위험 | 38°C+ | **옥외작업 즉시 중지** |

## 스케줄러 (로컬 서버만)

1. **15분마다**: 전체 현장 날씨 조회 → 단계 판정 → DB 저장
2. **매일 10시, 13시**: 폭염 단계별 SMS 자동 발송

## 사업소 구조

- **경남본부 (전체 관리)**: 모든 현장 열람, 초기화, 엑셀 등록 가능
- **각 지사 (담당 현장만)**: 로그인 시 선택한 사업소의 현장만 표시
- 사업소 목록: 경남본부직할, 진주/마산/거제/밀양/사천/통영/거창/창녕/합천/진해/하동/고성/산청/남해/함양/함안의령/진주전력/통영전력/함안전력지사

## 환경변수 (.env)

```
DATABASE_URL=sqlite+aiosqlite:///./safety_mgr.db
KMA_API_KEY=기상청_인증키
KAKAO_REST_API_KEY=카카오_REST_API키
VAPID_PUBLIC_KEY=웹푸시_공개키 (자동생성 가능)
VAPID_PRIVATE_KEY=웹푸시_비밀키
SMS_APP_KEY=NHN_Cloud_AppKey (선택)
SMS_SECRET_KEY=NHN_Cloud_SecretKey (선택)
SMS_SENDER_PHONE=발신번호 (선택)
NOTIFICATION_CHANNEL=web_push
WEATHER_CHECK_INTERVAL_MINUTES=15
```

## 로컬 실행

```bash
INSTALL.bat     # 최초 1회: venv + 패키지 + .env
START.bat       # 서버 시작 (포트 8000) + 브라우저 자동 열림
STOP.bat        # 서버 종료
```

## 보안 대응

- 사내 보안 소프트웨어가 .html 파일을 삭제하는 문제 → `.dat` 백업 + 자동 복원
- START.bat에서 매 실행 시 복원 체크
- REPAIR.bat으로 수동 복구 가능

## 알려진 제약사항

1. **인증 없음**: 사업소 선택은 localStorage 기반 (보안 미흡, 사내망 전제)
2. **Vercel 서버리스**: 스케줄러 미작동, DB 연결 불안정 → 로컬 서버 권장
3. **SMS 사업자 인증**: NHN Cloud SMS는 사업자 인증 필요 (법인카드)
4. **기상청 API**: 5km 격자 단위, 같은 격자 내 현장은 동일 날씨
