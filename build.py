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
    "설치_상시구동.bat", "해제_상시구동.bat",
    "시작하기.txt", ".env.example",
]

# 개발 흔적 — 배포판에 들어가면 안 됨
IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", ".pytest_cache",
    "*.bak", "*.bak_claude", "*.tmp", "*.log",
)


def log(step: str, msg: str) -> None:
    print(f"  [{step}] {msg}", flush=True)


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
        shutil.rmtree(OUT)
    zip_path.unlink(missing_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    log("1/5", "소스 복사...")
    for name in SRC_DIRS:
        shutil.copytree(ROOT / name, OUT / name, ignore=IGNORE)

    log("2/5", "실행 스크립트 및 문서 복사...")
    for name in SRC_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, OUT / name)

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
    print("    - 해제 후 START.bat 실행.")
    print("    - 최초 1회 설치_상시구동.bat 도 실행하세요 (서버 자동 감시/재시작).")
    print("  " + "=" * 44)
    print()


if __name__ == "__main__":
    main()
