"""
SQLAlchemy ORM 모델
- 작업자, 작업현장, 알림이력 관리
"""

from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, Enum,
)
from sqlalchemy.orm import relationship
import enum

from backend.models.database import Base


class WorkIntensity(str, enum.Enum):
    LIGHT = "light"
    MODERATE = "moderate"
    HEAVY = "heavy"
    VERY_HEAVY = "very_heavy"


class AlertStage(str, enum.Enum):
    INTEREST = "stage_1_interest"
    CAUTION = "stage_2_caution"
    WARNING = "stage_3_warning"
    DANGER = "stage_4_danger"


class AlertStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class SmsType(str, enum.Enum):
    MOCK = "mock"
    REAL = "real"
    AUTO = "auto"


# ── 작업자 ──
class Worker(Base):
    __tablename__ = "workers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False, unique=True)
    department = Column(String(100))  # 소속 부서
    team = Column(String(100))       # 작업반
    is_vulnerable = Column(Boolean, default=False)  # 취약 작업자 여부
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    work_sites = relationship("WorkSiteWorker", back_populates="worker")
    alert_logs = relationship("AlertLog", back_populates="worker")


# ── 작업현장 ──
class WorkSite(Base):
    __tablename__ = "work_sites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)         # 현장명
    address = Column(String(500))                       # 주소
    branch_office = Column(String(100))                 # 담당 사업소 (ex: 통영전력지사)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    work_intensity = Column(
        Enum(WorkIntensity), default=WorkIntensity.MODERATE
    )
    is_outdoor = Column(Boolean, default=True)          # 옥외작업 여부
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workers = relationship("WorkSiteWorker", back_populates="work_site")
    weather_logs = relationship("WeatherLog", back_populates="work_site")


# ── 작업현장-작업자 매핑 ──
class WorkSiteWorker(Base):
    __tablename__ = "work_site_workers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    work_site_id = Column(Integer, ForeignKey("work_sites.id"), nullable=False)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    role = Column(String(20), default="worker")  # manager(현장책임자) / worker(작업자)
    assigned_at = Column(DateTime, default=datetime.utcnow)

    work_site = relationship("WorkSite", back_populates="workers")
    worker = relationship("Worker", back_populates="work_sites")


# ── 날씨 기록 ──
class WeatherLog(Base):
    __tablename__ = "weather_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    work_site_id = Column(Integer, ForeignKey("work_sites.id"), nullable=False)
    temperature = Column(Float)          # 기온 (°C)
    humidity = Column(Float)             # 상대습도 (%)
    wind_speed = Column(Float)           # 풍속 (m/s)
    apparent_temperature = Column(Float) # 체감온도 (°C)
    wbgt_estimated = Column(Float)       # WBGT 추정값 (°C)
    stage = Column(Enum(AlertStage), nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)

    work_site = relationship("WorkSite", back_populates="weather_logs")


# ── 알림 이력 ──
class AlertLog(Base):
    __tablename__ = "alert_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    work_site_id = Column(Integer, ForeignKey("work_sites.id"), nullable=False)
    stage = Column(Enum(AlertStage), nullable=False)
    apparent_temperature = Column(Float)
    wbgt_estimated = Column(Float)
    message = Column(Text)
    channel = Column(String(50), default="kakao_alimtalk")  # 발송 채널
    status = Column(Enum(AlertStatus), default=AlertStatus.PENDING)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)

    worker = relationship("Worker", back_populates="alert_logs")


# ── 푸시 구독 ──
class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    endpoint = Column(String(500), nullable=False, unique=True)
    subscription_json = Column(Text, nullable=False)  # 전체 subscription 객체
    subscriber_type = Column(String(20), default="admin")
    site_id = Column(Integer, nullable=True)  # 하위 호환
    created_at = Column(DateTime, default=datetime.utcnow)


# ── 시스템 설정 (VAPID 키 등 영구 보관) ──
class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), nullable=False, unique=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SmsLog(Base):
    __tablename__ = "sms_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sms_type = Column(Enum(SmsType), nullable=False)
    recipient_phone = Column(String(20), nullable=False)
    recipient_name = Column(String(100), default="")
    site_name = Column(String(200), default="")
    stage = Column(String(50), default="")
    message_preview = Column(String(100), default="")
    full_message = Column(Text, default="")
    status = Column(String(10), nullable=False)  # sent / failed
    error_message = Column(Text, nullable=True)
    cost = Column(Float, default=30.0)  # LMS 건당 30원
    sent_at = Column(DateTime, default=datetime.utcnow)


class SmsFixedRecipient(Base):
    __tablename__ = "sms_fixed_recipients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    role = Column(String(50), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
