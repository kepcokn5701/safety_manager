"""
사전신고정보 엑셀 파서
- .xls (HTML 형식 포함), .xlsx, .csv 지원
- 컬럼 자동 매핑
"""

import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 사전신고정보에서 흔히 사용되는 컬럼명 매핑
COLUMN_MAP = {
    "name": [
        "공사명", "현장명", "작업명", "공사현장명", "사업명", "프로젝트명",
        "작업현장", "현장", "공사", "작업현장명",
    ],
    "address": [
        "공사장소", "작업장소", "주소", "소재지", "현장주소", "위치",
        "공사위치", "작업위치", "장소", "공사지역", "시공장소",
    ],
    "period": [
        "공사기간", "작업기간", "기간", "시공기간", "공기",
    ],
    "description": [
        "작업내용", "공사내용", "공종", "작업종류", "내용",
        "공사종류", "작업구분", "세부작업",
    ],
    "contractor": [
        "시공사", "시공업체", "업체명", "수급인", "하수급인",
        "협력업체", "도급업체", "시공회사",
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


def _match_column(col_name: str, column_map: dict | None = None) -> Optional[str]:
    """컬럼명을 표준 필드명으로 매핑"""
    if column_map is None:
        column_map = COLUMN_MAP
    col_clean = col_name.strip().replace(" ", "")
    for field, keywords in column_map.items():
        for kw in keywords:
            if kw in col_clean or col_clean in kw:
                return field
    return None


async def parse_worker_excel(file_content: bytes, filename: str) -> dict:
    """작업자 엑셀 파싱 (작업자용 컬럼 매핑 사용)"""
    return await parse_excel(file_content, filename, column_map=WORKER_COLUMN_MAP)


async def parse_excel(file_content: bytes, filename: str, *, column_map: dict | None = None) -> dict:
    """
    엑셀/CSV 파일을 파싱하여 구조화된 데이터 반환

    Returns:
        {
            "columns": ["원본컬럼1", ...],
            "mapped_columns": {"원본컬럼1": "name", ...},
            "rows": [{...}, ...],
            "total_rows": int
        }
    """
    import pandas as pd

    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    try:
        if ext == "csv":
            # CSV: 인코딩 자동 감지
            for enc in ["utf-8", "cp949", "euc-kr"]:
                try:
                    df = pd.read_csv(io.BytesIO(file_content), encoding=enc)
                    break
                except (UnicodeDecodeError, pd.errors.ParserError):
                    continue
            else:
                raise ValueError("CSV 인코딩을 인식할 수 없습니다.")

        elif ext in ("xls", "xlsx"):
            # XLS/XLSX 시도
            try:
                df = pd.read_excel(io.BytesIO(file_content), engine=None)
            except Exception:
                # HTML 형식 .xls 대응
                for enc in ["utf-8", "cp949", "euc-kr"]:
                    try:
                        text = file_content.decode(enc)
                        dfs = pd.read_html(io.StringIO(text))
                        if dfs:
                            df = dfs[0]
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

        # 빈 행/열 제거
        df = df.dropna(how="all").dropna(axis=1, how="all")

        # 멀티인덱스 헤더 평탄화
        if isinstance(df.columns[0], tuple):
            df.columns = [
                " ".join(str(x) for x in col if str(x) != "nan")
                for col in df.columns
            ]

        # 컬럼 매핑
        columns = [str(c) for c in df.columns.tolist()]
        mapped = {}
        for col in columns:
            field = _match_column(col, column_map)
            if field and field not in mapped.values():
                mapped[col] = field

        # 행 데이터 변환
        rows = []
        for _, row in df.iterrows():
            row_data = {}
            for col in columns:
                val = row.get(col)
                if pd.isna(val):
                    row_data[col] = ""
                else:
                    row_data[col] = str(val).strip()
            rows.append(row_data)

        return {
            "columns": columns,
            "mapped_columns": mapped,
            "rows": rows,
            "total_rows": len(rows),
        }

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"엑셀 파싱 실패: {e}", exc_info=True)
        raise ValueError(f"파일 처리 중 오류: {str(e)}")
