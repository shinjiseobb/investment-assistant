import io
import json
import logging
import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DART_TIMEOUT = 15

# 서버 메모리에 1회만 캐시되는 종목코드(6자리) -> DART 고유번호(8자리) 매핑
_CORP_CODE_MAP = {}


def _get_dart_api_key():
    key = os.getenv("DART_API_KEY", "").strip()
    if not key or key == "your_opendart_api_key_here" or len(key) < 10:
        return None
    return key


def _load_corp_code_map(api_key):
    """로컬 dart_corp_codes.json 캐시(0.002초)를 우선 읽고, 없을 때만 OpenDART corpCode.xml을 다운로드한다."""
    global _CORP_CODE_MAP
    if _CORP_CODE_MAP:
        return _CORP_CODE_MAP

    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dart_corp_codes.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                _CORP_CODE_MAP = json.load(f)
                logger.info("[DART] 로컬 고유번호 캐시(dart_corp_codes.json) 로드 완료 (%d개)", len(_CORP_CODE_MAP))
                return _CORP_CODE_MAP
        except Exception as e:
            logger.warning("[DART] 로컬 캐시 로드 실패, 원격 다운로드 시도: %s", e)

    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    logger.info("[DART] 고유번호(corpCode.xml) 매핑 목록 다운로드 시작")

    try:
        resp = requests.get(url, params={"crtfc_key": api_key}, timeout=DART_TIMEOUT)
        if resp.status_code != 200:
            logger.warning("[DART] corpCode.xml 응답 오류: status=%s", resp.status_code)
            return {}

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_name = zf.namelist()[0]
            with zf.open(xml_name) as xf:
                tree = ET.parse(xf)
                root = tree.getroot()
                mapping = {}
                for item in root.findall("list"):
                    stock_code = (item.findtext("stock_code") or "").strip()
                    corp_code = (item.findtext("corp_code") or "").strip()
                    if stock_code and corp_code:
                        mapping[stock_code] = corp_code
                _CORP_CODE_MAP = mapping
                logger.info("[DART] 고유번호 매핑 캐시 완료 (상장사 %d개)", len(_CORP_CODE_MAP))
                return _CORP_CODE_MAP
    except Exception as e:
        logger.error("[ERROR] DART corpCode.xml 파싱 실패: %s", e, exc_info=True)
        return {}


def _classify_report(report_nm):
    """공시 제목을 분석해 초보자용 분류와 신호등 배지 타입을 결정한다."""
    title = report_nm.strip()
    if any(k in title for k in ("잠정", "사업보고서", "반기보고서", "분기보고서", "매출액또는손익구조")):
        return "실적/보고서", "info", 1
    if any(k in title for k in ("자기주식", "배당", "소각")):
        return "주주환원", "positive", 1
    if any(k in title for k in ("유상증자", "무상증자", "전환사채", "신주인수권", "합병", "분할", "소송", "부도", "영업정지")):
        return "주요변동", "warning", 1
    if any(k in title for k in ("임원ㆍ주요주주", "기업설명회", "주주총회")):
        return "일반공시", "default", 3
    return "기타공시", "default", 2


def fetch_dart_disclosures(stock_code, days=90, limit=8):
    """최근 3개월간의 OpenDART 주요 전자공시 목록을 수집한다."""
    api_key = _get_dart_api_key()
    if not api_key:
        logger.info("[DART] DART_API_KEY 미설정으로 공시 조회를 건너뜁니다.")
        return [], None

    corp_map = _load_corp_code_map(api_key)
    corp_code = corp_map.get(str(stock_code).strip())
    if not corp_code:
        logger.info("[DART] 종목코드 %s에 해당하는 DART 고유번호가 없습니다.", stock_code)
        return [], None

    bgn_de = (datetime.today() - timedelta(days=days)).strftime("%Y%m%d")
    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "page_count": 40,
    }

    logger.info("[DART] 최근 %d일 공시 조회 시작 (stock_code=%s, corp_code=%s)", days, stock_code, corp_code)

    try:
        resp = requests.get(url, params=params, timeout=DART_TIMEOUT)
        data = resp.json()
    except Exception as e:
        logger.error("[ERROR] DART 공시 목록 조회 실패: %s", e, exc_info=True)
        return [], "OpenDART 공시 조회 중 네트워크 오류가 발생했습니다."

    status = data.get("status")
    if status == "013":
        # 조회된 데이터가 없음 (정상적인 빈 결과)
        return [], None
    if status != "000":
        msg = data.get("message", "알 수 없는 오류")
        logger.warning("[DART] API 응답 오류 (status=%s, msg=%s)", status, msg)
        return [], f"OpenDART 공시 조회 오류: {msg}"

    raw_list = data.get("list") or []
    prioritized = []
    for item in raw_list:
        report_nm = (item.get("report_nm") or "").strip()
        rcept_no = (item.get("rcept_no") or "").strip()
        rcept_dt = (item.get("rcept_dt") or "").strip()
        if not report_nm or not rcept_no:
            continue

        date_str = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:]}" if len(rcept_dt) == 8 else rcept_dt
        category, badge_type, priority = _classify_report(report_nm)

        prioritized.append({
            "priority": priority,
            "date": date_str,
            "title": report_nm,
            "category": category,
            "badge_type": badge_type,
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        })

    # 중요 공시(priority=1)를 우선 정렬하고 최신 날짜순 유지
    prioritized.sort(key=lambda x: (x["priority"], x["date"]), reverse=False)
    # priority 오름차순(1이 최우선), 같은 priority 내에서는 날짜 최신순(내림차순)
    prioritized.sort(key=lambda x: (x["priority"], -int(x["date"].replace("-", "") or 0)))

    disclosures = [
        {k: v for k, v in item.items() if k != "priority"}
        for item in prioritized[:limit]
    ]

    logger.info("[DART] 공시 수집 완료 (stock_code=%s, count=%d)", stock_code, len(disclosures))
    return disclosures, None
