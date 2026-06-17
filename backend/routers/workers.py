"""
작업자 & 작업현장 관리 API 라우터
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.database import get_db
from backend.models.schemas import (
    WorkerCreate, WorkerResponse,
    WorkSiteCreate, WorkSiteResponse,
)
from backend.services.repository import WorkerRepository, WorkSiteRepository

router = APIRouter(prefix="/api", tags=["작업자/현장 관리"])


# ── 작업자 ──
@router.post("/workers", response_model=WorkerResponse, status_code=201)
async def create_worker(
    data: WorkerCreate,
    db: AsyncSession = Depends(get_db),
):
    """작업자 등록"""
    repo = WorkerRepository(db)
    existing = await repo.get_by_phone(data.phone)
    if existing:
        raise HTTPException(status_code=409, detail="이미 등록된 전화번호입니다.")
    worker = await repo.create(**data.model_dump())
    return worker


@router.get("/workers", response_model=list[WorkerResponse])
async def list_workers(db: AsyncSession = Depends(get_db)):
    """활성 작업자 목록 조회"""
    repo = WorkerRepository(db)
    return await repo.get_all_active()


@router.get("/workers/{worker_id}", response_model=WorkerResponse)
async def get_worker(worker_id: int, db: AsyncSession = Depends(get_db)):
    """작업자 상세 조회"""
    repo = WorkerRepository(db)
    worker = await repo.get_by_id(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="작업자를 찾을 수 없습니다.")
    return worker


@router.put("/workers/{worker_id}", response_model=WorkerResponse)
async def update_worker(
    worker_id: int,
    data: WorkerCreate,
    db: AsyncSession = Depends(get_db),
):
    """작업자 정보 수정"""
    repo = WorkerRepository(db)
    worker = await repo.update(worker_id, **data.model_dump())
    if not worker:
        raise HTTPException(status_code=404, detail="작업자를 찾을 수 없습니다.")
    return worker


@router.delete("/workers/{worker_id}")
async def deactivate_worker(
    worker_id: int, db: AsyncSession = Depends(get_db)
):
    """작업자 비활성화"""
    repo = WorkerRepository(db)
    success = await repo.deactivate(worker_id)
    if not success:
        raise HTTPException(status_code=404, detail="작업자를 찾을 수 없습니다.")
    return {"message": "작업자가 비활성화되었습니다."}


# ── 작업현장 ──
@router.post("/sites", response_model=WorkSiteResponse, status_code=201)
async def create_work_site(
    data: WorkSiteCreate,
    db: AsyncSession = Depends(get_db),
):
    """작업현장 등록"""
    repo = WorkSiteRepository(db)
    site = await repo.create(**data.model_dump())
    return site


@router.get("/sites", response_model=list[WorkSiteResponse])
async def list_work_sites(branch_office: str = "", db: AsyncSession = Depends(get_db)):
    """활성 작업현장 목록 조회"""
    repo = WorkSiteRepository(db)
    return await repo.get_all_active(branch_office=branch_office or None)


@router.get("/sites/{site_id}", response_model=WorkSiteResponse)
async def get_work_site(site_id: int, db: AsyncSession = Depends(get_db)):
    """작업현장 상세 조회"""
    repo = WorkSiteRepository(db)
    site = await repo.get_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="작업현장을 찾을 수 없습니다.")
    return site


# ── 작업현장-작업자 배정 ──
@router.post("/sites/{site_id}/workers/{worker_id}")
async def assign_worker_to_site(
    site_id: int,
    worker_id: int,
    db: AsyncSession = Depends(get_db),
):
    """작업자를 현장에 배정"""
    repo = WorkSiteRepository(db)
    site = await repo.get_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="작업현장을 찾을 수 없습니다.")
    await repo.assign_worker(site_id, worker_id)
    return {"message": f"작업자(ID:{worker_id})가 현장(ID:{site_id})에 배정되었습니다."}


@router.get("/sites/{site_id}/workers")
async def get_site_workers(
    site_id: int, db: AsyncSession = Depends(get_db)
):
    """현장에 배정된 작업자 목록"""
    repo = WorkSiteRepository(db)
    workers = await repo.get_workers(site_id)
    return [
        {
            "id": w.id,
            "name": w.name,
            "phone": w.phone,
            "department": w.department,
            "team": w.team,
            "is_vulnerable": w.is_vulnerable,
        }
        for w in workers
    ]


@router.delete("/sites/{site_id}/workers/{worker_id}")
async def remove_worker_from_site(
    site_id: int,
    worker_id: int,
    db: AsyncSession = Depends(get_db),
):
    """현장에서 작업자 제거"""
    repo = WorkSiteRepository(db)
    success = await repo.remove_worker(site_id, worker_id)
    if not success:
        raise HTTPException(status_code=404, detail="배정 정보를 찾을 수 없습니다.")
    return {"message": "작업자가 현장에서 제거되었습니다."}
