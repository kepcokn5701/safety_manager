"""
주소 → 좌표 변환(지오코딩) 서비스
- 카카오 Maps API 사용 (한국 주소 최적)
- developers.kakao.com 에서 REST API 키 발급 (무료)
"""

import logging
from dataclasses import dataclass

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

KAKAO_GEOCODE_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


@dataclass
class GeoResult:
    latitude: float
    longitude: float
    address: str  # 정제된 주소


async def geocode_address(address: str) -> GeoResult | None:
    """
    한국 주소를 위경도 좌표로 변환.
    1차: 주소 검색 → 2차: 키워드 검색 → 3차: 시/군/구 단위로 재시도
    """
    if not settings.kakao_rest_api_key:
        logger.warning("카카오 REST API 키 미설정 - 지오코딩 불가")
        return None

    headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1차: 주소 검색
        result = await _search_address(client, headers, address)
        if result:
            return result

        # 2차: 키워드 검색 (건물명, 현장명 등)
        result = await _search_keyword(client, headers, address)
        if result:
            return result

        # 3차: 시/군까지만으로 재시도 (도로명 제거)
        import re
        # "경상남도 창원시 성산구" 또는 "경상남도 통영시" 등
        for pattern in [
            r"(경상[남북]도\s+\S+[시군]\s+\S+[구읍면])",
            r"(경상[남북]도\s+\S+[시군])",
            r"(\S+[시군]\s+\S+[구읍면])",
            r"(\S+[시군])",
        ]:
            short = re.match(pattern, address)
            if short:
                result = await _search_keyword(client, headers, short.group(1))
                if result:
                    result.address = address
                    return result

    return None


async def _search_address(
    client: httpx.AsyncClient, headers: dict, query: str
) -> GeoResult | None:
    """카카오 주소 검색 API"""
    try:
        resp = await client.get(
            KAKAO_GEOCODE_URL,
            headers=headers,
            params={"query": query},
        )
        resp.raise_for_status()
        data = resp.json()

        docs = data.get("documents", [])
        if docs:
            doc = docs[0]
            return GeoResult(
                latitude=float(doc["y"]),
                longitude=float(doc["x"]),
                address=doc.get("address_name", query),
            )
    except Exception as e:
        logger.debug(f"주소 검색 실패 ({query}): {e}")
    return None


async def _search_keyword(
    client: httpx.AsyncClient, headers: dict, query: str
) -> GeoResult | None:
    """카카오 키워드 검색 API (건물명, 현장명 등)"""
    try:
        resp = await client.get(
            KAKAO_KEYWORD_URL,
            headers=headers,
            params={"query": query},
        )
        resp.raise_for_status()
        data = resp.json()

        docs = data.get("documents", [])
        if docs:
            doc = docs[0]
            return GeoResult(
                latitude=float(doc["y"]),
                longitude=float(doc["x"]),
                address=doc.get("address_name") or doc.get("road_address_name", query),
            )
    except Exception as e:
        logger.debug(f"키워드 검색 실패 ({query}): {e}")
    return None


async def geocode_batch(addresses: list[str]) -> dict[str, GeoResult | None]:
    """여러 주소를 일괄 지오코딩"""
    results = {}
    for addr in addresses:
        addr = addr.strip()
        if not addr:
            continue
        # 이미 변환된 주소는 캐시
        if addr in results:
            continue
        results[addr] = await geocode_address(addr)
    return results
