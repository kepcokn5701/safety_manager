"""
Pydantic 스키마 (API 요청/응답 모델)
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, model_validator
from backend.utils.masking import mask_phone


# ── 작업자 ──
class WorkerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["홍길동"])
    phone: str = Field(..., pattern=r"^01[0-9]-?\d{3,4}-?\d{4}$", examples=["010-1234-5678"])
    department: Optional[str] = Field(None, examples=["배전건설부"])
    team: Optional[str] = Field(None, examples=["1공구 3반"])
    is_vulnerable: bool = False


class WorkerResponse(BaseModel):
    id: int
    name: str
    phone: str
    department: Optional[str]
    team: Optional[str]
    is_vulnerable: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _mask_phone(self):
        self.phone = mask_phone(self.phone)
        return self


# ── 작업현장 ──
class WorkSiteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, examples=["강남변전소 증설공사"])
    address: Optional[str] = Field(None, examples=["서울시 강남구 역삼동 123"])
    latitude: float = Field(..., ge=33.0, le=39.0, examples=[37.5665])
    longitude: float = Field(..., ge=124.0, le=132.0, examples=[126.9780])
    work_intensity: str = Field("moderate", examples=["heavy"])
    branch_office: Optional[str] = Field(None, examples=["통영전력지사"])
    is_outdoor: bool = True


class WorkSiteResponse(BaseModel):
    id: int
    name: str
    address: Optional[str]
    branch_office: Optional[str]
    latitude: float
    longitude: float
    work_intensity: str
    is_outdoor: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 날씨 데이터 ──
class WeatherData(BaseModel):
    temperature: float = Field(..., description="기온 (°C)")
    humidity: float = Field(..., description="상대습도 (%)")
    wind_speed: float = Field(..., description="풍속 (m/s)")
    apparent_temperature: float = Field(..., description="체감온도 (°C)")
    wbgt_estimated: float = Field(..., description="WBGT 추정값 (°C)")


class HeatStageInfo(BaseModel):
    stage_key: str = Field(..., description="단계 키")
    stage_name: str = Field(..., description="단계명 (관심/주의/경고/위험)")
    color: str = Field(..., description="단계 색상")
    actions: list[str] = Field(..., description="조치사항 목록")
    rest_guideline: str = Field(..., description="휴식 가이드라인")
    work_restriction: str = Field(..., description="작업 제한사항")


class WeatherStatusResponse(BaseModel):
    work_site_id: int
    work_site_name: str
    weather: WeatherData
    stage: Optional[HeatStageInfo]
    wbgt_work_recommendation: Optional[str] = Field(
        None, description="WBGT 기반 작업강도별 권고사항"
    )
    checked_at: datetime


# ── 알림 ──
class AlertLogResponse(BaseModel):
    id: int
    worker_name: str
    work_site_name: str
    stage: str
    apparent_temperature: Optional[float]
    wbgt_estimated: Optional[float]
    message: Optional[str]
    channel: str
    status: str
    sent_at: datetime

    model_config = {"from_attributes": True}
