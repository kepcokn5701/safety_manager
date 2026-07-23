"""
사전신고정보 엑셀 파서
- .xls (HTML 형식 포함), .xlsx, .csv 지원
- 멀티시트 자동 병합 (사업소별 시트 지원)
- 컬럼 자동 매핑
"""

import io
import logging
import re
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# 전화번호 패턴
_PHONE_RE = re.compile(r"01[0-9][-.\s]?\d{3,4}[-.\s]?\d{4}")

# 작업예정일시 안의 날짜 패턴 (YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD)
_DATE_RE = re.compile(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})")


def parse_work_period(text: str) -> tuple[Optional[date], Optional[date]]:
    """
    사전신고 '작업예정일시' 문자열에서 작업 시작일/종료일을 추출.

    지원 형식:
      - '2026-06-02 08:00 ~ 2026-06-02 18:00'  → (2026-06-02, 2026-06-02)
      - '2026-07-24 ~ 2026-07-26'              → (2026-07-24, 2026-07-26)
      - '2026.07.25'                           → (2026-07-25, 2026-07-25)
      - '2026/7/5 ~ 2026/7/7'                  → (2026-07-05, 2026-07-07)

    문자열에서 인식된 날짜가 없으면 (None, None) 반환.
    첫 번째 날짜=시작일, 마지막 날짜=종료일 (단일 날짜면 시작=종료).
    """
    if not text or not isinstance(text, str):
        return None, None

    found: list[date] = []
    for m in _DATE_RE.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            found.append(date(y, mo, d))
        except ValueError:
            continue

    if not found:
        return None, None

    start = min(found)
    end = max(found)
    return start, end

# 사전신고정보에서 흔히 사용되는 컬럼명 매핑
COLUMN_MAP = {
    "name": [
        "공사명", "현장명", "작업명", "공사현장명", "사업명", "프로젝트명",
        "작업현장", "현장", "공사", "작업현장명",
        "공사/용역명",
    ],
    "address": [
        "작업장소(주소)", "공사장소(주소)", "현장주소", "소재지", "주소",
        "공사장소", "작업장소", "공사위치", "작업위치", "위치",
        "장소", "공사지역", "시공장소",
    ],
    "period": [
        "공사기간", "작업기간", "기간", "시공기간", "공기",
        "작업예정일시",
    ],
    "description": [
        "작업내용", "공사내용", "공종", "작업종류", "내용",
        "공사종류", "작업구분", "세부작업",
    ],
    "contractor": [
        "시공사", "시공업체", "업체명", "수급인", "하수급인",
        "협력업체", "도급업체", "시공회사", "협력회사",
    ],
    "manager": [
        "현장대리인", "안전관리자", "현장소장", "관리자", "담당자",
        "안전담당", "현장담당",
    ],
    "phone": [
        "연락처", "전화번호", "휴대폰", "핸드폰", "전화",
        "담당자연락처", "관리자연락처",
    ],
    "worker_count": [
        "근로자수", "작업인원", "인원", "투입인원", "인원수",
    ],
    "branch_office": [
        "2차사업소", "사업소", "지사", "소속사업소",
    ],
    "cancel_status": [
        "취소유/무", "취소유무", "취소 유/무",
    ],
}

# 작업자 엑셀 업로드용 컬럼명 매핑
WORKER_COLUMN_MAP = {
    "name": [
        "이름", "성명", "작업자명", "근로자명", "작업자", "근로자",
        "성함", "인원명", "이름(성명)",
    ],
    "phone": [
        "연락처", "전화번호", "휴대폰", "핸드폰", "전화",
        "휴대폰번호", "핸드폰번호", "연락처(휴대폰)", "HP",
    ],
    "department": [
        "부서", "소속", "소속부서", "부서명", "조직",
        "소속팀", "근무부서", "소속사",
    ],
    "team": [
        "작업반", "반", "조", "작업조", "공구", "팀",
        "작업팀", "반명", "조명", "팀명",
    ],
    "is_vulnerable": [
        "취약", "취약여부", "취약작업자", "고령", "기저질환",
        "고령여부", "65세이상",
    ],
}

# 파싱에서 제외할 시트명 패턴
_SKIP_SHEET_PATTERNS = [
    "분류리포트", "N2SF", "리포트", "설명", "목차", "표지", "요약",
]


def _match_column(col_name: str, column_map: dict | None = None) -> Optional[str]:
    """컬럼명을 표준 필드명으로 매핑 (정확 매칭 우선)"""
    if column_map is None:
        column_map = COLUMN_MAP
    col_clean = col_name.strip().replace(" ", "")

    # 1차: 정확 매칭 (키워드가 컬럼명과 일치)
    for field, keywords in column_map.items():
        for kw in keywords:
            if kw.replace(" ", "") == col_clean:
                return field

    # 2차: 컬럼명에 키워드 포함 (긴 키워드부터 매칭)
    for field, keywords in column_map.items():
        sorted_kws = sorted(keywords, key=len, reverse=True)
        for kw in sorted_kws:
            if kw.replace(" ", "") in col_clean:
                return field

    return None


def _should_skip_sheet(name: str) -> bool:
    for pat in _SKIP_SHEET_PATTERNS:
        if pat in name:
            return True
    return False


def _read_dataframes(file_content: bytes, filename: str, *, column_map: dict | None = None):
    """파일에서 DataFrame(들)을 읽어 반환. 멀티시트 지원."""
    import pandas as pd

    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    sheets = []  # list of (sheet_name, df)

    if ext == "csv":
        for enc in ["utf-8", "cp949", "euc-kr"]:
            try:
                df = pd.read_csv(io.BytesIO(file_content), encoding=enc)
                sheets.append(("Sheet1", df))
                break
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        else:
            raise ValueError("CSV 인코딩을 인식할 수 없습니다.")

    elif ext in ("xls", "xlsx"):
        try:
            xls = pd.ExcelFile(io.BytesIO(file_content))
            sheet_names = xls.sheet_names
            for sname in sheet_names:
                if _should_skip_sheet(sname):
                    continue
                try:
                    df = pd.read_excel(xls, sheet_name=sname)
                    if len(df) > 0:
                        sheets.append((sname, df))
                except Exception:
                    continue
        except Exception:
            # HTML 형식 .xls 대응
            for enc in ["utf-8", "cp949", "euc-kr"]:
                try:
                    text = file_content.decode(enc)
                    dfs = pd.read_html(io.StringIO(text))
                    if dfs:
                        sheets.append(("Sheet1", dfs[0]))
                        break
                except Exception:
                    continue
            else:
                raise ValueError(
                    "엑셀 파일을 읽을 수 없습니다. "
                    ".xlsx 형식으로 다시 저장해서 업로드해주세요."
                )
    else:
        raise ValueError(f"지원하지 않는 파일 형식입니다: .{ext}")

    if not sheets:
        raise ValueError("읽을 수 있는 데이터가 없습니다.")

    return sheets


async def parse_worker_excel(file_content: bytes, filename: str) -> dict:
    """작업자 엑셀 파싱 (작업자용 컬럼 매핑 사용)"""
    return await parse_excel(file_content, filename, column_map=WORKER_COLUMN_MAP)


async def parse_excel(file_content: bytes, filename: str, *, column_map: dict | None = None) -> dict:
    """
    엑셀/CSV 파일을 파싱하여 구조화된 데이터 반환.
    멀티시트인 경우 모든 시트를 병합.
    """
    import pandas as pd

    try:
        sheets = _read_dataframes(file_content, filename, column_map=column_map)

        all_rows = []
        final_columns = None
        final_mapped = None
        sheet_info = []

        for sname, df in sheets:
            df = df.dropna(how="all").dropna(axis=1, how="all")

            # 멀티인덱스 헤더 평탄화
            if len(df.columns) > 0 and isinstance(df.columns[0], tuple):
                df.columns = [
                    " ".join(str(x) for x in col if str(x) != "nan")
                    for col in df.columns
                ]

            columns = [str(c) for c in df.columns.tolist()]

            # 첫 시트 기준으로 컬럼 매핑 (모든 시트 동일 구조 가정)
            if final_columns is None:
                final_columns = columns
                mapped = {}
                used_cols = set()
                target_map = column_map or COLUMN_MAP

                for field, keywords in target_map.items():
                    best_col = None
                    best_score = 0
                    sorted_kws = sorted(keywords, key=len, reverse=True)
                    for col in columns:
                        if col in used_cols:
                            continue
                        col_clean = col.strip().replace(" ", "")
                        for kw in sorted_kws:
                            score = 0
                            kw_clean = kw.replace(" ", "")
                            if kw_clean == col_clean:
                                score = 100
                            elif kw_clean in col_clean:
                                score = len(kw)
                            if score > best_score:
                                best_score = score
                                best_col = col
                                break
                    if best_col:
                        mapped[best_col] = field
                        used_cols.add(best_col)

                final_mapped = mapped

            # 취소 컬럼 찾기
            cancel_col = None
            for col, field in (final_mapped or {}).items():
                if field == "cancel_status":
                    cancel_col = col
                    break
            # 매핑에 없을 때 직접 탐색
            if not cancel_col:
                for col in columns:
                    if "취소" in col and ("유" in col or "무" in col):
                        cancel_col = col
                        break

            # 사업소 컬럼 찾기
            branch_col = None
            for col, field in (final_mapped or {}).items():
                if field == "branch_office":
                    branch_col = col
                    break

            # 시트명이 사업소명인지 판단 (지사/처/부 등 포함)
            sheet_is_branch = bool(re.search(r"(지사|전력|관리|사업|본부)", sname))

            row_count = 0
            for _, row in df.iterrows():
                # 취소된 행 제외
                if cancel_col:
                    cancel_val = str(row.get(cancel_col, "")).strip()
                    if "취소" in cancel_val:
                        continue

                row_data = {}
                for col in columns:
                    val = row.get(col)
                    if pd.isna(val):
                        row_data[col] = ""
                    else:
                        row_data[col] = str(val).strip()

                # 시트명을 사업소 정보로 활용 (사업소 컬럼이 없는 경우)
                if not branch_col and sheet_is_branch:
                    row_data["__sheet_branch"] = sname

                # 멀티시트 구분을 위해 시트명 저장
                row_data["__sheet"] = sname

                all_rows.append(row_data)
                row_count += 1

            sheet_info.append({"name": sname, "rows": row_count})

        return {
            "columns": final_columns or [],
            "mapped_columns": final_mapped or {},
            "rows": all_rows,
            "total_rows": len(all_rows),
            "sheets": sheet_info,
            "multi_sheet": len(sheets) > 1,
        }

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"엑셀 파싱 실패: {e}", exc_info=True)
        raise ValueError(f"파일 처리 중 오류: {str(e)}")


# ── 사전신고정보에서 작업자 자동 추출 ──

# 작업자 정보가 포함될 수 있는 컬럼명 키워드
_WORKER_SOURCE_KEYWORDS = [
    "현장책임자", "책임자", "작업자명단", "작업자", "안전담당자",
    "안전담당", "감독자", "작업반장", "관리자", "담당자",
]

_MANAGER_KEYWORDS = ["책임자", "관리자", "담당자", "감독자", "소장"]


def _detect_role(source_col: str) -> str:
    col_clean = source_col.replace(" ", "")
    for kw in _MANAGER_KEYWORDS:
        if kw in col_clean:
            return "manager"
    return "worker"


def _extract_name_phone_pairs(text: str) -> list[dict]:
    """텍스트에서 (이름, 전화번호) 쌍을 추출.
    지원 형식:
      - '김진호 010-5701-0001'
      - '010-5701-0001' (전화번호만)
      - '(박성진/010-5701-0002), (이동규/010-5701-0003)'
      - '안전담당자 정해원 010-5701-0004'
    """
    if not text or not isinstance(text, str):
        return []

    results = []
    phones = list(_PHONE_RE.finditer(text))
    if not phones:
        return []

    for match in phones:
        phone = match.group().strip()
        before = text[:match.start()].strip()

        # (이름/전화번호) 형식
        paren_match = re.search(r"\(?([가-힣]{2,5})\s*/?\s*$", before)
        if paren_match:
            name = paren_match.group(1)
        else:
            # '직책 이름 전화번호' 또는 '이름 전화번호' 형식
            words = re.findall(r"[가-힣]{2,5}", before)
            name = words[-1] if words else ""

        # 전화번호 정규화
        digits = re.sub(r"[^0-9]", "", phone)
        if len(digits) == 11:
            phone = f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"

        # 전화번호만 있고 이름이 없는 경우도 포함
        results.append({"name": name or "(미확인)", "phone": phone})

        # 다음 이름 추출을 위해 이미 처리된 부분 제거
        text = text[match.end():]
        phones = list(_PHONE_RE.finditer(text))
        if not phones:
            break

    return results


def extract_workers_from_site_data(rows: list[dict], columns: list[str]) -> list[dict]:
    """사전신고정보의 행 데이터에서 작업자 정보를 자동 추출.

    Returns:
        [{"name": "김진호", "phone": "010-5701-0001", "source": "현장책임자",
          "role": "manager", "site_name": "...", "row_index": 0, "branch_office": ""}, ...]
    """
    # 작업자 정보가 있을 수 있는 컬럼 찾기
    worker_cols = []
    for col in columns:
        col_clean = col.strip().replace(" ", "")
        for kw in _WORKER_SOURCE_KEYWORDS:
            if kw in col_clean:
                worker_cols.append(col)
                break

    if not worker_cols:
        return []

    # 현장명 컬럼 찾기
    site_name_col = None
    for col in columns:
        field = _match_column(col)
        if field == "name":
            site_name_col = col
            break

    # 사업소 컬럼 찾기
    branch_col = None
    for col in columns:
        field = _match_column(col)
        if field == "branch_office":
            branch_col = col
            break

    # 모든 행에서 작업자 추출 (현장별 그룹핑, 동일 행 내 중복만 제거)
    all_workers = []

    for row_idx, row in enumerate(rows):
        site_name = row.get(site_name_col, "") if site_name_col else ""
        # 사업소: 컬럼 > 시트명 > 빈값
        branch_office = ""
        if branch_col:
            branch_office = row.get(branch_col, "")
        if not branch_office:
            branch_office = row.get("__sheet_branch", "")
        row_phones = set()

        for col in worker_cols:
            text = row.get(col, "")
            if not text or text.strip() in ("--", "-", "미대상", "미대상(배치제외)"):
                continue
            pairs = _extract_name_phone_pairs(text)
            for p in pairs:
                if p["phone"] in row_phones:
                    continue
                row_phones.add(p["phone"])
                all_workers.append({
                    "name": p["name"],
                    "phone": p["phone"],
                    "source": col,
                    "role": _detect_role(col),
                    "site_name": site_name,
                    "row_index": row_idx,
                    "branch_office": branch_office,
                })

    return all_workers
