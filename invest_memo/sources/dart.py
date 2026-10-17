"""OpenDART 클라이언트 (https://opendart.fss.or.kr)."""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..cache import FileCache, cached
from . import SourceError, request_with_retry

BASE = "https://opendart.fss.or.kr/api"
ANNUAL_REPORT = "11011"  # 사업보고서

# 재무 항목 → (IFRS account_id 후보, account_nm 키워드 후보, 허용 sj_div)
ACCOUNT_RULES: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "revenue": (
        ("ifrs-full_Revenue", "ifrs_Revenue"),
        ("매출액", "수익(매출액)", "영업수익"),
        ("IS", "CIS"),
    ),
    "operating_income": (
        ("dart_OperatingIncomeLoss",),
        ("영업이익", "영업손익"),
        ("IS", "CIS"),
    ),
    "net_income": (
        ("ifrs-full_ProfitLoss", "ifrs_ProfitLoss"),
        ("당기순이익", "당기순손익", "분기순이익"),
        ("IS", "CIS"),
    ),
    "interest_expense": (
        ("ifrs-full_InterestExpense", "ifrs-full_FinanceCosts"),
        ("이자비용", "금융비용", "금융원가"),
        ("IS", "CIS"),
    ),
    "total_assets": (("ifrs-full_Assets", "ifrs_Assets"), ("자산총계",), ("BS",)),
    "total_liabilities": (("ifrs-full_Liabilities", "ifrs_Liabilities"), ("부채총계",), ("BS",)),
    "total_equity": (("ifrs-full_Equity", "ifrs_Equity"), ("자본총계",), ("BS",)),
    "current_assets": (("ifrs-full_CurrentAssets", "ifrs_CurrentAssets"), ("유동자산",), ("BS",)),
    "current_liabilities": (
        ("ifrs-full_CurrentLiabilities", "ifrs_CurrentLiabilities"),
        ("유동부채",),
        ("BS",),
    ),
    "paid_in_capital": (("ifrs-full_IssuedCapital", "ifrs_IssuedCapital"), ("자본금",), ("BS",)),
    "cfo": (
        ("ifrs-full_CashFlowsFromUsedInOperatingActivities",),
        ("영업활동현금흐름", "영업활동으로인한현금흐름"),
        ("CF",),
    ),
    "capex_ppe": (
        ("ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",),
        ("유형자산의취득",),
        ("CF",),
    ),
    "capex_intangible": (
        ("ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",),
        ("무형자산의취득",),
        ("CF",),
    ),
}
# 차입금은 여러 계정을 합산한다.
BORROWING_KEYWORDS = ("단기차입금", "장기차입금", "사채", "유동성장기부채", "유동성장기차입금")


@dataclass
class CorpInfo:
    corp_code: str
    corp_name: str
    stock_code: str


@dataclass
class Disclosure:
    date: str  # YYYY-MM-DD
    title: str
    filer: str
    rcept_no: str

    @property
    def url(self) -> str:
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={self.rcept_no}"


@dataclass
class Shareholder:
    name: str
    relation: str
    shares: float | None
    ratio: float | None  # %


@dataclass
class FinancialStatements:
    fs_div: str  # CFS(연결) / OFS(별도)
    years: dict[int, dict[str, float | None]] = field(default_factory=dict)


def parse_amount(text: str | None) -> float | None:
    """'1,234' / '-1,234' / '-' / '' → float | None."""
    if text is None:
        return None
    cleaned = text.replace(",", "").replace(" ", "").strip()
    if cleaned in ("", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _norm(name: str) -> str:
    return "".join((name or "").split())


def _pick(rows: list[dict], ids, names, divs, column: str) -> float | None:
    """account_id 우선, 실패 시 account_nm 키워드로 한 행을 골라 column 값을 반환."""
    rows = [r for r in rows if r.get("sj_div") in divs]
    for account_id in ids:
        for r in rows:
            if r.get("account_id") == account_id:
                value = parse_amount(r.get(column))
                if value is not None:
                    return value
    for keyword in names:
        for r in rows:
            if keyword in _norm(r.get("account_nm", "")):
                value = parse_amount(r.get(column))
                if value is not None:
                    return value
    return None


def extract_years(rows: list[dict], year: int) -> dict[int, dict[str, float | None]]:
    """fnlttSinglAcntAll 의 list 를 {사업연도: {항목: 금액}} 으로 변환한다."""
    columns = {year: "thstrm_amount", year - 1: "frmtrm_amount", year - 2: "bfefrmtrm_amount"}
    result: dict[int, dict[str, float | None]] = {}
    for y, col in columns.items():
        items: dict[str, float | None] = {
            key: _pick(rows, ids, names, divs, col) for key, (ids, names, divs) in ACCOUNT_RULES.items()
        }
        borrowings = [
            parse_amount(r.get(col))
            for r in rows
            if r.get("sj_div") == "BS" and any(k in _norm(r.get("account_nm", "")) for k in BORROWING_KEYWORDS)
        ]
        borrowings = [b for b in borrowings if b is not None]
        items["borrowings"] = sum(borrowings) if borrowings else None
        capex = [v for v in (items.pop("capex_ppe"), items.pop("capex_intangible")) if v is not None]
        items["capex"] = sum(abs(v) for v in capex) if capex else None
        if any(v is not None for v in items.values()):
            result[y] = items
    return result


class DartClient:
    def __init__(self, api_key: str, cache: FileCache | None = None):
        self.api_key = api_key
        self.cache = cache

    # --- 내부 -----------------------------------------------------------
    def _json(self, endpoint: str, **params) -> dict:
        """JSON 엔드포인트 호출. status 000 정상, 013 데이터 없음(빈 dict)."""
        params["crtfc_key"] = self.api_key
        key = "dart:" + endpoint + ":" + "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "crtfc_key")

        def fetch():
            body = request_with_retry(f"{BASE}/{endpoint}.json", params).json()
            status = body.get("status")
            if status == "013":
                return {"status": "013", "list": []}
            if status != "000":
                raise SourceError(f"DART {endpoint}: [{status}] {body.get('message')}")
            return body

        body = cached(self.cache, key, fetch)
        return {} if body.get("status") == "013" else body

    # --- 공개 API -------------------------------------------------------
    def find_corp(self, stock_code: str) -> CorpInfo:
        """종목코드(6자리) → corp_code. corpCode.xml 은 XML 이 든 zip 파일이다."""

        def fetch():
            resp = request_with_retry(f"{BASE}/corpCode.xml", {"crtfc_key": self.api_key}, timeout=60)
            try:
                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    xml_bytes = zf.read(zf.namelist()[0])
            except zipfile.BadZipFile:
                # 오류 시에는 zip 이 아닌 XML(<result><status>..)이 온다.
                raise SourceError("DART corpCode.xml: zip 이 아닌 응답 (API 키 확인 필요)")
            mapping = {}
            for item in ET.fromstring(xml_bytes).iter("list"):
                code = (item.findtext("stock_code") or "").strip()
                if code:
                    mapping[code] = {
                        "corp_code": (item.findtext("corp_code") or "").strip(),
                        "corp_name": (item.findtext("corp_name") or "").strip(),
                    }
            return mapping

        mapping = cached(self.cache, "dart:corpcode", fetch)
        hit = mapping.get(stock_code)
        if not hit:
            raise SourceError(f"DART 에서 종목코드 {stock_code} 를 찾을 수 없습니다.")
        return CorpInfo(hit["corp_code"], hit["corp_name"], stock_code)

    def company(self, corp_code: str) -> dict:
        return self._json("company", corp_code=corp_code)

    def financials(self, corp_code: str, year: int) -> FinancialStatements:
        """연결(CFS) 우선, 데이터 없으면 별도(OFS)."""
        for fs_div in ("CFS", "OFS"):
            body = self._json(
                "fnlttSinglAcntAll",
                corp_code=corp_code,
                bsns_year=year,
                reprt_code=ANNUAL_REPORT,
                fs_div=fs_div,
            )
            years = extract_years(body.get("list", []), year)
            if years:
                return FinancialStatements(fs_div, years)
        raise SourceError(f"DART: {year}년 사업보고서 재무제표 없음")

    def disclosures(self, corp_code: str, days: int = 90, today: date | None = None) -> list[Disclosure]:
        end = today or date.today()
        body = self._json(
            "list",
            corp_code=corp_code,
            bgn_de=(end - timedelta(days=days)).strftime("%Y%m%d"),
            end_de=end.strftime("%Y%m%d"),
            page_count=100,
        )
        out = []
        for r in body.get("list", []):
            d = r.get("rcept_dt", "")
            out.append(
                Disclosure(
                    date=f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d,
                    title=(r.get("report_nm") or "").strip(),
                    filer=r.get("flr_nm", ""),
                    rcept_no=r.get("rcept_no", ""),
                )
            )
        return out

    def major_shareholders(self, corp_code: str, year: int) -> list[Shareholder]:
        body = self._json("hyslrSttus", corp_code=corp_code, bsns_year=year, reprt_code=ANNUAL_REPORT)
        out = []
        for r in body.get("list", []):
            if r.get("stock_knd") not in (None, "", "보통주"):
                continue
            out.append(
                Shareholder(
                    name=r.get("nm", ""),
                    relation=r.get("relate", ""),
                    shares=parse_amount(r.get("trmend_posesn_stock_co")),
                    ratio=parse_amount(r.get("trmend_posesn_stock_qota_rt")),
                )
            )
        out.sort(key=lambda s: s.ratio or 0, reverse=True)
        return out[:5]
