"""선택적 주가 조회. FinanceDataReader 가 없으면 None 을 반환한다."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

try:  # 선택 의존성
    import FinanceDataReader as fdr
except ImportError:  # pragma: no cover
    fdr = None


@dataclass
class PriceInfo:
    last_close: float
    high_52w: float
    low_52w: float
    volatility_1y: float | None  # 연환산 %, 일간 수익률 표준편차 * sqrt(252)
    market_cap: float | None = None  # 원 (조회 가능한 경우)

    @property
    def drawdown_from_high(self) -> float:
        """52주 고점 대비 낙폭(%, 양수)."""
        return (1 - self.last_close / self.high_52w) * 100 if self.high_52w else 0.0


def price_info_from_closes(closes: list[float], market_cap: float | None = None) -> PriceInfo | None:
    closes = [c for c in closes if c and not math.isnan(c)]
    if len(closes) < 2:
        return None
    returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / max(len(returns) - 1, 1)
    return PriceInfo(
        last_close=closes[-1],
        high_52w=max(closes),
        low_52w=min(closes),
        volatility_1y=math.sqrt(var) * math.sqrt(252) * 100,
        market_cap=market_cap,
    )


def fetch_price_info(stock_code: str, today: date | None = None) -> PriceInfo | None:
    """최근 1년 종가 기반 지표. 라이브러리 미설치/조회 실패 시 None."""
    if fdr is None:
        return None
    end = today or date.today()
    try:
        df = fdr.DataReader(stock_code, (end - timedelta(days=365)).isoformat(), end.isoformat())
        info = price_info_from_closes(df["Close"].dropna().tolist())
    except Exception:
        return None
    if info is None:
        return None
    try:  # 시가총액은 best-effort (KRX 전체 목록 조회)
        listing = fdr.StockListing("KRX")
        row = listing[listing["Code"] == stock_code]
        if not row.empty:
            info.market_cap = float(row.iloc[0]["Marcap"])
    except Exception:
        pass
    return info
