"""KEPCO Safety Manager - 포터블 배포판 빌드 스크립트.

사용법:
    build.bat                 더블클릭 (버전 자동: yyMMdd_v1)
    build.bat 260723_v3       버전 직접 지정
    python build.py 260723_v3

산출물:
    dist/safety_manager_portable/            배포 폴더
    dist/safety_manager_portable_<버전>.zip  운영자 전달용

safety_mgr.db 는 의도적으로 제외한다. 운영자가 기존 폴더에 덮어쓰기로 압축을
풀 때 이미 등록된 현장/작업자 데이터가 날아가지 않게 하기 위함이다.
"""

import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
OUT = DIST / "safety_manager_portable"

# 배포에 포함할 소스 디렉터리
SRC_DIRS = ["backend", "frontend", "config"]

# 배포에 포함할 단일 파일 (없으면 조용히 건너뜀)
SRC_FILES = [
    "START.bat", "STOP.bat", "REPAIR.bat", "WATCHDOG.bat",
    "_setup_watchdog.bat",   # START.bat이 관리자 권한으로 호출 (내부용)
    "해제_상시구동.bat",
    "시작하기.txt", ".env.example",
]

# 개발 흔적 — 배포판에 들어가면 안 됨
IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", ".pytest_cache",
    "*.bak", "*.bak_claude", "*.tmp", "*.log",
)


def log(step: str, msg: str) -> None:
    print(f"  [{step}] {msg}", flush=True)


def to_crlf(raw: bytes) -> bytes:
    """cmd.exe는 배치 파일에 CRLF를 요구한다.

    LF만 있으면 파싱 위치가 어긋나 명령어가 중간부터 잘려 실행된다
    (errorlevel -> 'orlevel' is not recognized).
    """
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", b"\r\n")


def normalize_bat(path: Path) -> None:
    """배치 파일을 CP949 + CRLF로 맞춘다.

    UTF-8(chcp 65001) 배치는 한글이 3바이트라, 괄호 블록 안에 한글이 많으면
    cmd가 바이트/문자 오프셋을 잃고 줄 앞부분을 통째로 날린다. 실제로
    `echo AI혁신팀에 보내주세요.` 가 'AI혁신팀에' is not recognized 로 터졌다.
    한글 Windows 기본 코드페이지인 949로 저장하면 이 문제가 사라진다.
    """
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp949")  # 이미 변환된 파일
    text = text.replace("chcp 65001", "chcp 949")
    path.write_bytes(to_crlf(text.encode("cp949")))


def build(version: str) -> Path:
    runtime = ROOT / "runtime" / "python"
    if not (runtime / "python.exe").exists():
        raise SystemExit(
            f"[오류] {runtime / 'python.exe'} 가 없습니다.\n"
            "       임베디드 Python 런타임을 runtime/python/ 에 두고 다시 실행하세요.\n"
            "       (기존 배포판의 python 폴더를 통째로 복사하면 됩니다)"
        )

    zip_path = DIST / f"safety_manager_portable_{version}.zip"

    # 이전 산출물 정리
    if OUT.exists():
        try:
            shutil.rmtree(OUT)
        except PermissionError as e:
            raise SystemExit(
                f"[오류] 이전 빌드 폴더를 지울 수 없습니다: {e.filename}\n"
                "       dist 폴더에서 실행 중인 서버나 열려 있는 창을 닫고 다시 시도하세요.\n"
                "       (dist\\safety_manager_portable\\STOP.bat 실행 또는 검은 창 닫기)"
            ) from e
    zip_path.unlink(missing_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    log("1/5", "소스 복사...")
    for name in SRC_DIRS:
        shutil.copytree(ROOT / name, OUT / name, ignore=IGNORE)

    # .dat 백업을 .html 원본에서 다시 만든다.
    # 손으로 관리하면 .html만 고치고 .dat를 깜빡했을 때, 보안SW가 .html을 지운 뒤
    # 옛날 내용으로 복원되는 사고가 난다. 빌드 때마다 강제로 맞춘다.
    log("1/5", "화면 백업(.dat) 동기화...")
    synced = 0
    for html in sorted((OUT / "frontend").glob("*.html")):
        shutil.copy2(html, html.with_suffix(".dat"))
        synced += 1
    log("1/5", f"  {synced}개 .dat 재생성")

    log("2/5", "실행 스크립트 및 문서 복사...")
    for name in SRC_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, OUT / name)

    log("2/5", "배치 파일 인코딩/줄바꿈 정규화...")
    for path in sorted(OUT.glob("*.bat")):
        normalize_bat(path)
    for path in sorted(OUT.glob("*.txt")):
        raw = path.read_bytes()
        path.write_bytes(to_crlf(raw))
    log("2/5", f"  .bat {len(list(OUT.glob('*.bat')))}개 CP949+CRLF 변환")

    log("3/5", "Python 런타임 복사 (약 120MB, 시간이 걸립니다)...")
    shutil.copytree(runtime, OUT / "python", ignore=IGNORE)

    log("4/5", "환경설정(.env) 처리...")
    env = ROOT / ".env"
    if env.exists():
        shutil.copy2(env, OUT / ".env")
        log("4/5", "  .env 포함됨  <-- 실제 API 키가 배포판에 들어갑니다")
    else:
        log("4/5", "  .env 없음. 운영자가 .env.example 을 복사해 작성해야 합니다.")

    log("5/5", "압축...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(OUT.rglob("*")):
            if path.is_file():
                # zip 안에서 safety_manager_portable/ 로 시작하도록
                zf.write(path, path.relative_to(DIST))

    return zip_path


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%y%m%d_v1")

    print()
    print("  " + "=" * 44)
    print(f"   포터블 배포판 빌드  [버전: {version}]")
    print("  " + "=" * 44)
    print()

    zip_path = build(version)

    files = sum(1 for p in OUT.rglob("*") if p.is_file())
    size_mb = zip_path.stat().st_size / 1024 / 1024

    print()
    print("  " + "=" * 44)
    print("   빌드 완료")
    print("  " + "=" * 44)
    print(f"   폴더 : {OUT.relative_to(ROOT)}  ({files:,}개 파일)")
    print(f"   ZIP  : {zip_path.relative_to(ROOT)}  ({size_mb:.1f} MB)")
    print()
    print("   [운영자 전달 시 안내사항]")
    print("    - 기존 폴더에 '덮어쓰기'로 압축을 푸세요.")
    print("      safety_mgr.db 를 포함하지 않으므로 기존 데이터는 보존됩니다.")
    print("    - 해제 후 START.bat 더블클릭. 이것 하나면 끝입니다.")
    print("      (24시간 자동 감시는 최초 1회 UAC [예] 클릭으로 자동 등록)")
    print("  " + "=" * 44)
    print()


if __name__ == "__main__":
    main()
