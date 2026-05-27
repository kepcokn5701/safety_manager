"""
파일 업로드 API 라우터
- 사전신고정보 엑셀 업로드 → 파싱 → 작업현장 일괄 등록
- 작업자 엑셀 업로드 → 파싱 → 작업자 일괄 등록
"""

import re
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.models.database import get_db
from backend.services.excel_parser import parse_excel, parse_worker_excel
from backend.services.repository import WorkSiteRepository, WorkerRepository

router = APIRouter(prefix="/api/upload", tags=["파일 업로드"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


class SiteImportItem(BaseModel):
    name: str
    address: str = ""
    latitude: float
    longitude: float
    work_intensity: str = "moderate"


class BulkImportRequest(BaseModel):
    sites: list[SiteImportItem]


@router.post("/parse-excel")
async def upload_and_parse(file: UploadFile = File(...)):
    """
    엑셀 파일을 업로드하면 내용을 파싱하여 미리보기 반환.
    프론트엔드에서 확인 후 선택한 행만 작업현장으로 등록.
    """
    # 파일 검증
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일이 없습니다.")

    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("xls", "xlsx", "csv"):
        raise HTTPException(
            status_code=400,
            detail="지원 형식: .xls, .xlsx, .csv",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="파일 크기가 10MB를 초과합니다.")

    try:
        result = await parse_excel(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.post("/import-sites")
async def import_sites(
    data: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """파싱된 데이터에서 선택한 항목들을 작업현장으로 일괄 등록"""
    repo = WorkSiteRepository(db)
    created = []
    errors = []

    for item in data.sites:
        try:
            site = await repo.create(
                name=item.name,
                address=item.address,
                latitude=item.latitude,
                longitude=item.longitude,
                work_intensity=item.work_intensity,
                is_outdoor=True,
            )
            created.append({"id": site.id, "name": site.name})
        except Exception as e:
            errors.append({"name": item.name, "error": str(e)})

    return {
        "created": len(created),
        "errors": len(errors),
        "sites": created,
        "error_details": errors,
    }


# ── 작업자 엑셀 업로드 ──

class WorkerImportItem(BaseModel):
    name: str
    phone: str
    department: Optional[str] = ""
    team: Optional[str] = ""
    is_vulnerable: bool = False


class BulkWorkerImportRequest(BaseModel):
    workers: list[WorkerImportItem]


def _normalize_phone(raw: str) -> str:
    """전화번호를 010-XXXX-XXXX 형식으로 정규화"""
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) == 11 and digits.startswith("01"):
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    if len(digits) == 10 and digits.startswith("01"):
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return raw.strip()


@router.post("/parse-worker-excel")
async def upload_and_parse_workers(file: UploadFile = File(...)):
    """
    작업자 엑셀 파일을 업로드하면 내용을 파싱하여 미리보기 반환.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일이 없습니다.")

    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("xls", "xlsx", "csv"):
        raise HTTPException(
            status_code=400,
            detail="지원 형식: .xls, .xlsx, .csv",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="파일 크기가 10MB를 초과합니다.")

    try:
        result = await parse_worker_excel(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.post("/import-workers")
async def import_workers(
    data: BulkWorkerImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """파싱된 데이터에서 선택한 항목들을 작업자로 일괄 등록"""
    repo = WorkerRepository(db)
    created = []
    skipped = []
    errors = []

    for item in data.workers:
        phone = _normalize_phone(item.phone)
        if not re.match(r"^01[0-9]-?\d{3,4}-?\d{4}$", phone):
            errors.append({"name": item.name, "error": f"잘못된 전화번호 형식: {item.phone}"})
            continue

        try:
            existing = await repo.get_by_phone(phone)
            if existing:
                skipped.append({"name": item.name, "phone": phone, "reason": "이미 등록된 전화번호"})
                continue

            worker = await repo.create(
                name=item.name,
                phone=phone,
                department=item.department or None,
                team=item.team or None,
                is_vulnerable=item.is_vulnerable,
            )
            created.append({"id": worker.id, "name": worker.name})
        except Exception as e:
            errors.append({"name": item.name, "error": str(e)})

    return {
        "created": len(created),
        "skipped": len(skipped),
        "errors": len(errors),
        "workers": created,
        "skipped_details": skipped,
        "error_details": errors,
    }
