"""
파일 업로드 API 라우터
- 사전신고정보 엑셀 업로드 → 파싱 → 작업현장 일괄 등록
- 작업자 엑셀 업로드 → 파싱 → 작업자 일괄 등록
"""

import logging
import re
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.models.database import get_db
from backend.services.excel_parser import parse_excel, parse_worker_excel, extract_workers_from_site_data
from backend.services.geocoding import geocode_address
from backend.services.repository import WorkSiteRepository, WorkerRepository

logger = logging.getLogger(__name__)

_BRANCH_PATTERNS = [
    (r'합천(관내|지사)', '합천지사'), (r'진주(관내|지사|전력)', '진주지사'),
    (r'진해(지사|관내)', '진해지사'), (r'남해(지사|관내)', '남해지사'),
    (r'함양(관내|지사)', '함양지사'), (r'의령(지사|관내)', '의령지사'),
    (r'하동(관내|지사)', '하동지사'), (r'고성(관내|지사)', '고성지사'),
    (r'통영(전력|지사)', '통영지사'), (r'밀양(지사|관내)', '밀양지사'),
    (r'창녕(지사|관내)', '창녕지사'), (r'산청(지사|관내)', '산청지사'),
    (r'거제(지사|관내)', '거제지사'), (r'직할(관내)?', '직할'),
]
_ADDR_PATTERNS = [
    (r'창원시\s*진해구', '진해지사'), (r'합천군', '합천지사'),
    (r'진주시', '진주지사'), (r'남해군', '남해지사'),
    (r'함양군', '함양지사'), (r'의령군', '의령지사'),
    (r'하동군', '하동지사'), (r'고성군', '고성지사'),
    (r'통영시', '통영지사'), (r'밀양시', '밀양지사'),
    (r'창녕군', '창녕지사'), (r'산청군', '산청지사'),
    (r'거제시', '거제지사'), (r'사천시', '사천지사'),
    (r'함안군', '함안지사'), (r'창원시', '직할'),
]


def _detect_branch_office(name: str, address: str) -> str:
    for text in [name or '', address or '']:
        for pat, branch in _BRANCH_PATTERNS:
            if re.search(pat, text):
                return branch
    for pat, branch in _ADDR_PATTERNS:
        if re.search(pat, address or ''):
            return branch
    if '경남본부' in (name or ''):
        return '직할'
    return ''

router = APIRouter(prefix="/api/upload", tags=["파일 업로드"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


class WorkerRef(BaseModel):
    name: str
    phone: str
    role: str = "worker"  # manager(현장책임자) / worker(작업자)


class SiteImportItem(BaseModel):
    name: str
    address: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    work_intensity: str = "moderate"
    branch_office: str = ""  # 담당 사업소
    workers: list[WorkerRef] = []  # 해당 현장에 배정할 작업자


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

    # 사전신고정보에서 작업자 자동 추출
    workers = extract_workers_from_site_data(result["rows"], result["columns"])
    result["extracted_workers"] = workers
    result["extracted_workers_count"] = len(workers)

    return result


class GeocodingRequest(BaseModel):
    address: str


@router.post("/geocode")
async def geocode_single(data: GeocodingRequest):
    """단일 주소 → 좌표 변환"""
    result = await geocode_address(data.address)
    if not result:
        raise HTTPException(status_code=404, detail="주소를 찾을 수 없습니다.")
    return {
        "latitude": result.latitude,
        "longitude": result.longitude,
        "address": result.address,
    }


@router.post("/import-sites")
async def import_sites(
    data: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """파싱된 데이터에서 선택한 항목들을 작업현장으로 일괄 등록.
    동일 이름의 현장이 이미 있으면 작업자 역할만 업데이트.
    좌표가 0이고 주소가 있으면 자동 지오코딩.
    """
    site_repo = WorkSiteRepository(db)
    worker_repo = WorkerRepository(db)
    created = []
    updated = []
    errors = []
    geocoded_count = 0
    workers_created = 0
    workers_assigned = 0
    roles_updated = 0

    for item in data.sites:
        # 동일 이름의 기존 현장이 있는지 확인
        existing_site = await site_repo.get_by_name(item.name)
        if existing_site:
            # 기존 현장 → 작업자 role만 업데이트
            for w in item.workers:
                phone = _normalize_phone(w.phone)
                if not re.match(r"^01[0-9]-?\d{3,4}-?\d{4}$", phone):
                    continue
                try:
                    worker = await worker_repo.get_by_phone(phone)
                    if worker:
                        role = w.role if hasattr(w, 'role') else "worker"
                        did_update = await site_repo.update_worker_role(existing_site.id, worker.id, role)
                        if did_update:
                            roles_updated += 1
                except Exception:
                    pass
            updated.append({"id": existing_site.id, "name": existing_site.name})
            continue

        lat, lng = item.latitude, item.longitude

        # 좌표가 없고 주소가 있으면 지오코딩 시도
        geo_failed = False
        if (lat == 0 or lng == 0) and item.address:
            geo = await geocode_address(item.address)
            if geo:
                lat, lng = geo.latitude, geo.longitude
                geocoded_count += 1
            else:
                geo_failed = True
                logger.warning(f"지오코딩 실패 (주소로 등록): {item.name} - {item.address}")

        try:
            site = await site_repo.create(
                name=item.name,
                address=item.address,
                latitude=lat,
                longitude=lng,
                work_intensity=item.work_intensity,
                branch_office=item.branch_office or _detect_branch_office(item.name, item.address) or None,
                is_outdoor=True,
            )
            created.append({"id": site.id, "name": site.name})

            # 작업자 등록 + 현장 배정 (role 포함)
            for w in item.workers:
                phone = _normalize_phone(w.phone)
                if not re.match(r"^01[0-9]-?\d{3,4}-?\d{4}$", phone):
                    continue
                try:
                    existing = await worker_repo.get_by_phone(phone)
                    if not existing:
                        existing = await worker_repo.create(
                            name=w.name, phone=phone,
                        )
                        workers_created += 1
                    role = w.role if hasattr(w, 'role') else "worker"
                    await site_repo.assign_worker(site.id, existing.id, role=role)
                    workers_assigned += 1
                except Exception:
                    pass

        except Exception as e:
            errors.append({"name": item.name, "error": str(e)})

    return {
        "created": len(created),
        "updated": len(updated),
        "roles_updated": roles_updated,
        "geocoded": geocoded_count,
        "workers_created": workers_created,
        "workers_assigned": workers_assigned,
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
        if not item.name or not item.name.strip():
            errors.append({"name": "(빈값)", "error": "이름 누락", "phone": item.phone})
            continue

        phone = _normalize_phone(item.phone)
        if not item.phone or not item.phone.strip():
            errors.append({"name": item.name, "error": "연락처 누락"})
            continue
        if not re.match(r"^01[0-9]-?\d{3,4}-?\d{4}$", phone):
            errors.append({"name": item.name, "error": f"연락처 형식 오류: {item.phone} (올바른 형식: 010-XXXX-XXXX)"})
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


@router.post("/update-roles")
async def update_roles_from_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """엑셀 재업로드로 기존 작업자의 역할(현장책임자/작업자) 일괄 갱신.
    전화번호 매칭으로 기존 DB의 role을 업데이트합니다.
    """
    from sqlalchemy import text as sql_text

    if not file.filename:
        raise HTTPException(status_code=400, detail="파일이 없습니다.")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="파일 크기가 10MB를 초과합니다.")

    try:
        result = await parse_excel(content, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    workers = extract_workers_from_site_data(result["rows"], result["columns"])
    if not workers:
        return {"updated": 0, "message": "엑셀에서 작업자를 찾을 수 없습니다."}

    updated = 0
    for w in workers:
        phone = _normalize_phone(w["phone"])
        role = w.get("role", "worker")
        res = await db.execute(
            sql_text("""
                UPDATE work_site_workers SET role = :role
                WHERE worker_id IN (SELECT id FROM workers WHERE phone = :phone)
            """),
            {"role": role, "phone": phone},
        )
        updated += res.rowcount

    await db.commit()
    manager_count = sum(1 for w in workers if w.get("role") == "manager")
    worker_count = sum(1 for w in workers if w.get("role") != "manager")

    return {
        "updated": updated,
        "manager_count": manager_count,
        "worker_count": worker_count,
        "message": f"역할 갱신 완료: 현장책임자 {manager_count}명, 작업자 {worker_count}명",
    }
