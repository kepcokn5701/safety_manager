# KEPCO 폭염 안전관리 시스템 (Safety Manager)

> ## ⚠️ 정본은 이 폴더다 (2026-07-23 확인)
>
> `C:\Users\Administrator\Desktop\project\safety-manager` — **이 PC의 이 폴더가 정본이다.**
> 코드 수정은 여기서 한다.
>
> 과거에는 원격 개발PC(SSH 별명 `safetypc`, `10.193.5.157:10022`,
> `C:\Users\Admin\Desktop\project\safety_manager`)에서 개발했으나 **여기로 옮겨왔다.**
> 원격에 있는 것은 **옛 사본**이다. 거기서 고치라고 안내하지 말 것.
>
> **두 폴더는 git remote로 연결돼 있지 않다** (이 저장소는 remote가 없는 로컬 전용 git).
> 즉 자동 동기화가 없다 — 원격 사본을 건드리면 조용히 갈라진다. 건드리지 않는 게 원칙.

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
├── REPAIR.bat                 # .html 수동 복구
├── WATCHDOG.bat               # 상시구동 감시 (작업스케줄러가 3분마다 실행)
├── build.py / build.bat       # 포터블 배포판 빌드
├── runtime/python/            # 임베디드 Python (git 제외, 빌드 입력)
├── dist/                      # 빌드 산출물 (git 제외)
├── .env.example               # 환경변수 템플릿
└── requirements.txt           # Python 의존성
```

## 개발 / 배포 구조

이 저장소는 **개발용 소스**다. 운영자에게는 여기서 빌드한 포터블 zip을 전달한다.

| | 개발 (이 폴더) | 배포 (운영자 PC) |
|---|---|---|
| Python | `runtime/python/` | 동봉된 `python/` |
| 설치 | 불필요 | 불필요 (압축만 해제) |
| 실행 | `runtime\python\python.exe -m uvicorn backend.app:app --port 8000` | `START.bat` 더블클릭 |
| DB | 로컬 `safety_mgr.db` | 각자 보유 (배포판에 미포함) |

### 배포판 빌드

```bash
build.bat            # 버전 자동 (yyMMdd_v1)
build.bat 260723_v3  # 버전 직접 지정
```

`dist/safety_manager_portable_<버전>.zip` 생성 (약 40MB).
`__pycache__`, `*.pyc`, `*.bak` 등 개발 흔적은 자동 제외된다.

**`safety_mgr.db`는 일부러 빌드에 넣지 않는다.** 운영자가 기존 폴더에 덮어쓰기로
압축을 풀 때 등록된 현장/작업자 데이터가 날아가지 않게 하기 위함이다.
전달 시 "기존 폴더에 덮어쓰기로 해제"를 반드시 안내할 것.

주의: `.env`가 있으면 빌드에 포함된다 (실제 API 키가 배포판에 들어감).

### 배치 파일 규칙 (중요)

한글이 든 `.bat`은 **CP949 + CRLF**여야 cmd가 정상 파싱한다. 둘 중 하나만 틀려도
명령어가 중간부터 잘려 실행된다.

| 잘못 | 증상 |
|---|---|
| LF 줄바꿈 | `errorlevel` → `'orlevel'`, `--host 0.0.0.0` → `'.0.0'` |
| UTF-8 + `chcp 65001` | 괄호 블록 안 `echo`가 통째로 사라짐 (`'AI혁신팀에' is not recognized`) |

저장소의 `.bat`은 편집 편의상 UTF-8/LF로 둔다. **`build.py`가 빌드할 때 CP949 +
CRLF로 변환하고 `chcp 65001` → `chcp 949` 로 치환한다.** 따라서:

- 배포는 반드시 `build.bat`을 거친다. 개발 폴더의 `.bat`을 직접 압축해 보내지 말 것.
- `.bat` 동작 테스트도 `dist/` 산출물로 한다. 개발 폴더 것은 인코딩이 다르다.

배치에서 대기는 `timeout` 대신 `ping -n N 127.0.0.1 >nul` 을 쓴다. `timeout`은
표준입력이 리다이렉트된 환경에서 즉시 실패해 폴링 루프가 헛돈다.

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
START.bat       # 서버 시작 (포트 8000) + 브라우저 자동 열림
STOP.bat        # 서버 종료
```

`.env`는 최초 1회 `.env.example`을 복사해 작성한다. 패키지 설치는 불필요하다
(임베디드 런타임에 이미 포함).

## 보안 대응

사내 보안 소프트웨어가 `.html` 파일을 삭제한다. `.dat` 백업 + 다층 복원으로 대응:

| 시점 | 위치 |
|---|---|
| 서버 기동 전 | `START.bat` |
| 앱 시작 시 | `app.py` lifespan |
| **HTTP 요청 시** | **`app.py` `_file()`** |
| 3분마다 | `WATCHDOG.bat` (작업스케줄러 등록 시) |

**요청 시점 복원이 핵심이다.** 2026-07-23 운영자 PC에서, 서버가 떠 있는 동안
`index.html`이 삭제되어 `GET /`가 계속 500을 반환한 장애가 있었다. 당시 복원은
기동 시 1회뿐이라 재시작 전까지 자체 복구가 불가능했다. 현재는 `_file()`이
요청마다 존재를 확인해 `.dat`에서 복원하고, 응답을 디스크가 아닌 메모리에서
내보내므로 서빙 직전 삭제돼도 안전하다. `.html`/`.dat` 모두 없으면 500이 아닌
404를 반환한다.

수동 복구는 `REPAIR.bat`.

**`.dat`는 손으로 만들지 말 것.** `frontend/*.html`을 수정하면 짝이 되는 `.dat`도
같이 바뀌어야 하는데, 깜빡하면 보안SW가 지운 뒤 옛 내용으로 복원된다(실제로
`manual.dat`이 구버전으로 남아 있었다). `build.py`가 빌드마다 `.html`에서
`.dat`를 재생성하므로, 배포는 반드시 `build.bat`을 통해서 한다.

## 운영자 사용 절차

**`START.bat` 더블클릭 하나가 전부다.** 이 스크립트가 `.html` 복원 → 상시구동
등록(최초 1회 UAC) → 서버 기동 → 브라우저 열기를 모두 처리하며, 서버가 이미
떠 있으면 죽이지 않고 재사용하므로 몇 번을 눌러도 안전하다(멱등).

문제가 생기면 안내는 "START.bat을 한 번 더 누르세요"로 통일한다. 별도 설치
스크립트를 안내하지 말 것 — 운영자가 두 개를 실행해야 하는 구조는 실제로
누락을 낳았다(2026-07-23 상시구동 미등록).

## 알려진 제약사항

1. **인증 없음**: 사업소 선택은 localStorage 기반 (보안 미흡, 사내망 전제)
2. **Vercel 서버리스**: 스케줄러 미작동, DB 연결 불안정 → 로컬 서버 권장
3. **SMS 사업자 인증**: NHN Cloud SMS는 사업자 인증 필요 (법인카드)
4. **기상청 API**: 5km 격자 단위, 같은 격자 내 현장은 동일 날씨
