"""
Naver Stock information service.
Fetches stock data via Naver's JSON APIs (m.stock.naver.com / api.stock.naver.com).
"""

import re
from datetime import date, datetime, timedelta
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from utils.validators import is_naver_stock_url, is_web_url


class StockInfoError(Exception):
    """Raised when stock info fetch or parsing fails."""
    pass


@dataclass
class StockChartData:
    """Chart-ready series for price and investor deal trends."""
    price_labels: List[str] = field(default_factory=list)
    price_series: List[float] = field(default_factory=list)
    trend_labels: List[str] = field(default_factory=list)
    personal_series: List[float] = field(default_factory=list)
    foreign_series: List[float] = field(default_factory=list)
    institution_series: List[float] = field(default_factory=list)

    def has_price(self) -> bool:
        return len(self.price_series) >= 2

    def has_trend(self) -> bool:
        return any([
            len(self.personal_series) >= 2,
            len(self.foreign_series) >= 2,
            len(self.institution_series) >= 2,
        ])

    def has_any(self) -> bool:
        return self.has_price() or self.has_trend()


@dataclass
class StockSearchCandidate:
    """Candidate stock resolved from search endpoints."""
    code: str
    name: str
    market: Optional[str] = None
    reuters_code: Optional[str] = None
    nation_code: Optional[str] = None


class StockQueryAmbiguousError(ValueError):
    """Raised when stock query has multiple low-confidence candidates."""

    def __init__(self, query: str, candidates: List[StockSearchCandidate]):
        self.query = query
        self.candidates = candidates[:3]
        suggestions = ", ".join([f"{item.name}({item.code})" for item in self.candidates])
        super().__init__(
            f"No confident match for '{query}'. Did you mean: {suggestions} ?"
        )


@dataclass
class StockResolution:
    """Resolution result for a stock query input."""
    code: str
    reuters_code: Optional[str] = None
    is_world: bool = False
    matched_name: Optional[str] = None
    market: Optional[str] = None
    search_note: Optional[str] = None


@dataclass
class StockInfo:
    """Parsed stock information used for Telegram response rendering."""
    code: str
    name: str
    name_eng: Optional[str] = None
    market: Optional[str] = None
    current_price: Optional[str] = None
    change_value: Optional[str] = None
    change_rate: Optional[str] = None
    change_direction: Optional[str] = None
    prev_close: Optional[str] = None
    open_price: Optional[str] = None
    high_price: Optional[str] = None
    low_price: Optional[str] = None
    volume: Optional[str] = None
    trading_value: Optional[str] = None
    market_cap: Optional[str] = None
    foreign_rate: Optional[str] = None
    per: Optional[str] = None
    eps: Optional[str] = None
    estimated_per: Optional[str] = None
    estimated_eps: Optional[str] = None
    pbr: Optional[str] = None
    bps: Optional[str] = None
    dividend_yield: Optional[str] = None
    dividend_per_share: Optional[str] = None
    high_52w: Optional[str] = None
    low_52w: Optional[str] = None
    target_price: Optional[str] = None
    analyst_rating: Optional[str] = None
    industry: Optional[str] = None
    currency: Optional[str] = None
    as_of: Optional[str] = None
    source_url: Optional[str] = None
    requested_query: Optional[str] = None
    search_note: Optional[str] = None
    deal_trends: Optional[List[Dict[str, str]]] = field(default_factory=list)
    recent_news: Optional[List[Dict[str, str]]] = field(default_factory=list)
    recent_reports: Optional[List[Dict[str, str]]] = field(default_factory=list)
    chart_data: Optional[StockChartData] = None


class AsyncStockInfoService:
    """Async stock info service using Naver's JSON APIs."""

    # Search API (new front-api endpoint)
    SEARCH_URL = "https://m.stock.naver.com/front-api/search/autoComplete?query={query}&target=stock"

    # Domestic stock APIs (m.stock.naver.com)
    DOMESTIC_BASIC_API = "https://m.stock.naver.com/api/stock/{code}/basic"
    DOMESTIC_INTEGRATION_API = "https://m.stock.naver.com/api/stock/{code}/integration"

    # World stock APIs (api.stock.naver.com)
    WORLD_BASIC_API = "https://api.stock.naver.com/stock/{code}/basic"
    WORLD_INTEGRATION_API = "https://api.stock.naver.com/stock/{code}/integration"

    # Detail page URLs (for source link)
    DOMESTIC_DETAIL_URL = "https://stock.naver.com/domestic/stock/{symbol}"
    WORLD_DETAIL_URL = "https://stock.naver.com/worldstock/stock/{symbol}"

    DOMESTIC_CODE_PATTERN = re.compile(r"^A?(\d{6})$", re.IGNORECASE)
    WORLD_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{1,12}(?:\.[A-Z0-9]{1,8})+$", re.IGNORECASE)

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36"
                }
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    # ── Public entry point ──────────────────────────────────────────────

    async def get_stock_info(self, query: str) -> StockInfo:
        """Fetch stock info from code, name, or URL."""
        cleaned_query = query.strip() if query else ""
        resolution = await self.resolve_stock_query(cleaned_query)

        stock = await self._fetch_stock_via_api(resolution)
        stock.requested_query = cleaned_query
        stock.search_note = resolution.search_note

        if resolution.matched_name and (not stock.name or stock.name.startswith("Stock ")):
            stock.name = resolution.matched_name
        if resolution.market and not stock.market:
            stock.market = resolution.market

        return stock

    # ── Query resolution ────────────────────────────────────────────────

    async def resolve_stock_query(self, query: str) -> StockResolution:
        """Resolve query to a stock code, with typo-aware name search."""
        if not query:
            raise ValueError(
                "Input is empty. Usage: /stock <stock name | 6-digit code | stock.naver.com URL>"
            )

        direct_symbol, source_hint = self._extract_symbol_from_input(query)
        if direct_symbol:
            is_world = source_hint == "world"
            return StockResolution(
                code=direct_symbol,
                reuters_code=direct_symbol if is_world else None,
                is_world=is_world,
            )

        candidates = await self._fetch_search_candidates(query)

        if not candidates:
            fallback_query = self._build_fallback_query(query)
            if fallback_query and fallback_query != query:
                candidates = await self._fetch_search_candidates(fallback_query)

        if not candidates:
            raise ValueError(
                f"No listed stock found for '{query}'. "
                "Try stock name, 6-digit code, world ticker (e.g. NVDA.O), or stock.naver.com URL."
            )

        best = self._pick_best_candidate(query, candidates)
        if best is None:
            raise StockQueryAmbiguousError(query, candidates)

        note = None
        normalized_query = self._normalize_text(query)
        normalized_name = self._normalize_text(best.name)

        if normalized_query and normalized_name and normalized_query != normalized_name:
            note = f"입력 보정: '{query}' -> '{best.name}' ({best.code})"

        is_world = self._is_world_stock(best)

        return StockResolution(
            code=best.reuters_code or best.code,
            reuters_code=best.reuters_code,
            is_world=is_world,
            matched_name=best.name,
            market=best.market,
            search_note=note,
        )

    # ── API data fetching ───────────────────────────────────────────────

    async def _fetch_stock_via_api(self, resolution: StockResolution) -> StockInfo:
        """Fetch stock data from Naver JSON APIs."""
        code = resolution.code
        is_world = resolution.is_world

        if is_world:
            basic_url = self.WORLD_BASIC_API.format(code=code)
            integration_url = self.WORLD_INTEGRATION_API.format(code=code)
            source_url = self.WORLD_DETAIL_URL.format(symbol=code)
        else:
            basic_url = self.DOMESTIC_BASIC_API.format(code=code)
            integration_url = self.DOMESTIC_INTEGRATION_API.format(code=code)
            source_url = self.DOMESTIC_DETAIL_URL.format(symbol=code)

        basic_data = await self._fetch_json(basic_url)
        if not basic_data:
            raise StockInfoError(f"Failed to fetch stock basic data for '{code}'")

        integration_data = await self._fetch_json(integration_url)

        return self._build_stock_info(basic_data, integration_data, code, is_world, source_url)

    async def _fetch_json(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch and parse JSON from a URL. Returns None on failure."""
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return None

    def _build_stock_info(
        self,
        basic: Dict[str, Any],
        integration: Optional[Dict[str, Any]],
        code: str,
        is_world: bool,
        source_url: str,
    ) -> StockInfo:
        """Build StockInfo from API responses."""
        # Extract totalInfos as a code->value lookup
        total_infos = self._parse_total_infos(basic, integration, is_world)

        # Basic fields
        name = basic.get("stockName") or f"Stock {code}"
        name_eng = basic.get("stockNameEng")

        exchange_type = basic.get("stockExchangeType") or {}
        market = basic.get("stockExchangeName") or exchange_type.get("nameEng") or exchange_type.get("nameKor")

        # Price from basic API
        current_price = basic.get("closePrice")
        change_value = basic.get("compareToPreviousClosePrice")
        change_rate = basic.get("fluctuationsRatio")
        change_dir_obj = basic.get("compareToPreviousPrice") or {}
        change_direction = change_dir_obj.get("name")  # RISING / FALLING / UNCHANGED

        as_of = basic.get("localTradedAt")
        currency_obj = basic.get("currencyType") or {}
        currency = currency_obj.get("code")

        # Industry
        industry_obj = basic.get("industryCodeType") or {}
        industry = industry_obj.get("industryGroupKor")

        # From totalInfos
        prev_close = total_infos.get("lastClosePrice") or total_infos.get("basePrice")
        open_price = total_infos.get("openPrice")
        high_price = total_infos.get("highPrice")
        low_price = total_infos.get("lowPrice")
        volume = total_infos.get("accumulatedTradingVolume")
        trading_value = total_infos.get("accumulatedTradingValue")
        market_cap = total_infos.get("marketValue")
        foreign_rate = total_infos.get("foreignRate")
        per = total_infos.get("per")
        eps = total_infos.get("eps")
        estimated_per = total_infos.get("cnsPer")
        estimated_eps = total_infos.get("cnsEps")
        pbr = total_infos.get("pbr")
        bps = total_infos.get("bps")
        dividend_yield = total_infos.get("dividendYieldRatio")
        dividend_per_share = total_infos.get("dividend")
        high_52w = total_infos.get("highPriceOf52Weeks")
        low_52w = total_infos.get("lowPriceOf52Weeks")

        # Consensus / target price
        target_price = None
        analyst_rating = None
        if integration:
            consensus = integration.get("consensusInfo")
            if consensus and isinstance(consensus, dict):
                target_price = consensus.get("priceTargetMean")
                rating_val = consensus.get("recommMean")
                if rating_val:
                    analyst_rating = self._rating_text(rating_val)

        # Deal trend (investor flow)
        deal_trends: List[Dict[str, str]] = []
        if integration:
            raw_trends = integration.get("dealTrendInfos") or []
            for trend in raw_trends[:30]:
                deal_trends.append({
                    "date": trend.get("bizdate", ""),
                    "foreign": trend.get("foreignerPureBuyQuant", ""),
                    "institution": trend.get("organPureBuyQuant", ""),
                    "individual": trend.get("individualPureBuyQuant", ""),
                })

        recent_news = self._extract_recent_items(
            integration=integration,
            list_keys=(
                "newsInfos",
                "newsInfoList",
                "recentNewsInfos",
                "newsItems",
                "stockNewsInfos",
            ),
        )
        recent_reports = self._extract_recent_items(
            integration=integration,
            list_keys=(
                "researches",
                "reports",
                "researchInfos",
                "reportInfos",
                "recentReportInfos",
                "consensusReportInfos",
                "investmentOpinionInfos",
            ),
        )

        chart_data = self._build_chart_data(
            basic=basic,
            integration=integration,
            prev_close=prev_close,
            current_price=current_price,
            deal_trends=deal_trends,
        )

        # Format change with sign
        formatted_change = self._format_change_value(change_value, change_direction)
        formatted_rate = self._format_rate(change_rate, change_direction)

        return StockInfo(
            code=code,
            name=name,
            name_eng=name_eng,
            market=market,
            current_price=current_price,
            change_value=formatted_change,
            change_rate=formatted_rate,
            change_direction=change_direction,
            prev_close=prev_close,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            volume=volume,
            trading_value=trading_value,
            market_cap=market_cap,
            foreign_rate=foreign_rate,
            per=per,
            eps=eps,
            estimated_per=estimated_per,
            estimated_eps=estimated_eps,
            pbr=pbr,
            bps=bps,
            dividend_yield=dividend_yield,
            dividend_per_share=dividend_per_share,
            high_52w=high_52w,
            low_52w=low_52w,
            target_price=target_price,
            analyst_rating=analyst_rating,
            industry=industry,
            currency=currency,
            as_of=as_of,
            source_url=source_url,
            deal_trends=deal_trends,
            recent_news=recent_news,
            recent_reports=recent_reports,
            chart_data=chart_data,
        )

    def _build_chart_data(
        self,
        basic: Dict[str, Any],
        integration: Optional[Dict[str, Any]],
        prev_close: Optional[str],
        current_price: Optional[str],
        deal_trends: List[Dict[str, str]],
    ) -> Optional[StockChartData]:
        """Build chart series for price + investor deal trends."""
        price_labels, price_series = self._extract_price_series(integration)
        if not price_series:
            fallback_series: List[float] = []
            fallback_labels: List[str] = []
            prev_close_num = self._to_float(prev_close)
            current_num = self._to_float(current_price or basic.get("closePrice"))
            if prev_close_num is not None:
                fallback_labels.append("전일")
                fallback_series.append(prev_close_num)
            if current_num is not None:
                fallback_labels.append("현재")
                fallback_series.append(current_num)
            if len(fallback_series) >= 2:
                price_labels, price_series = fallback_labels, fallback_series

        trend_labels, personal, foreign, institution = self._extract_trend_series(deal_trends)

        chart = StockChartData(
            price_labels=price_labels,
            price_series=price_series,
            trend_labels=trend_labels,
            personal_series=personal,
            foreign_series=foreign,
            institution_series=institution,
        )

        return chart if chart.has_any() else None

    def _extract_price_series(
        self,
        integration: Optional[Dict[str, Any]],
    ) -> Tuple[List[str], List[float]]:
        """
        Extract price history from integration payload when available.

        The API schema can vary by market/type, so this scans known list fields.
        """
        if not integration:
            return [], []

        candidate_lists: List[List[Any]] = []
        for key in (
            "siseTrendInfos",
            "priceTrendInfos",
            "priceInfos",
            "chartInfos",
            "closePriceInfos",
            "stockPriceInfos",
            "dailyPriceInfos",
        ):
            value = integration.get(key)
            if isinstance(value, list):
                candidate_lists.append(value)

        for rows in candidate_lists:
            labels: List[str] = []
            values: List[float] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                label = self._pick_first_text(
                    row,
                    ("bizdate", "date", "localTradedAt", "tradeDate", "tradedAt", "time"),
                )
                raw_price = self._pick_first_text(
                    row,
                    ("closePrice", "price", "tradePrice", "lastPrice", "value", "close", "stckClpr"),
                )
                price_num = self._to_float(raw_price)
                if price_num is None:
                    continue
                labels.append(label or str(len(labels) + 1))
                values.append(price_num)

            if len(values) >= 2:
                filtered = self._limit_series_to_one_month(labels, [values])
                if filtered is not None:
                    return filtered[0], filtered[1][0]

                # Fallback: roughly one month of trading sessions
                return labels[-22:], values[-22:]

        return [], []

    def _extract_trend_series(
        self,
        deal_trends: List[Dict[str, str]],
    ) -> Tuple[List[str], List[float], List[float], List[float]]:
        """Extract investor deal-trend series from normalized deal trend rows."""
        labels: List[str] = []
        personal: List[float] = []
        foreign: List[float] = []
        institution: List[float] = []

        for row in deal_trends:
            label = row.get("date") or str(len(labels) + 1)
            p_val = self._to_float(row.get("individual"))
            f_val = self._to_float(row.get("foreign"))
            i_val = self._to_float(row.get("institution"))
            if p_val is None and f_val is None and i_val is None:
                continue

            labels.append(label)
            personal.append(p_val if p_val is not None else 0.0)
            foreign.append(f_val if f_val is not None else 0.0)
            institution.append(i_val if i_val is not None else 0.0)

        filtered = self._limit_series_to_one_month(
            labels,
            [personal, foreign, institution],
        )
        if filtered is not None:
            return filtered[0], filtered[1][0], filtered[1][1], filtered[1][2]

        # Fallback: roughly one month of trading sessions
        return labels[-22:], personal[-22:], foreign[-22:], institution[-22:]

    def _pick_first_text(self, source: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[str]:
        """Pick first non-empty text value from candidate keys."""
        for key in keys:
            value = source.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _to_float(self, value: Any) -> Optional[float]:
        """Convert mixed numeric string values to float safely."""
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        cleaned = re.sub(r"[^0-9+\-.]", "", text)
        if cleaned in ("", "+", "-", ".", "+.", "-."):
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _limit_series_to_one_month(
        self,
        labels: List[str],
        series_list: List[List[float]],
    ) -> Optional[Tuple[List[str], List[List[float]]]]:
        """
        Restrict aligned series to the latest one-month window by parsed date labels.

        Returns None if labels cannot be date-parsed reliably.
        """
        if not labels:
            return None
        if any(len(series) != len(labels) for series in series_list):
            return None

        parsed_dates = [self._parse_series_date(label) for label in labels]
        dated_indices = [idx for idx, dt in enumerate(parsed_dates) if dt is not None]
        if len(dated_indices) < 2:
            return None

        latest_date = max(parsed_dates[idx] for idx in dated_indices if parsed_dates[idx] is not None)
        cutoff = latest_date - timedelta(days=30)
        keep_indices = [
            idx for idx in dated_indices
            if parsed_dates[idx] is not None and parsed_dates[idx] >= cutoff
        ]
        if len(keep_indices) < 2:
            keep_indices = dated_indices[-22:]

        kept_labels = [labels[idx] for idx in keep_indices]
        kept_series = [[series[idx] for idx in keep_indices] for series in series_list]
        return kept_labels, kept_series

    def _parse_series_date(self, raw: str) -> Optional[date]:
        """Parse common API date formats used by Naver stock payloads."""
        text = str(raw).strip()
        if not text:
            return None

        digits = re.sub(r"[^0-9]", "", text)
        try:
            if len(digits) == 8:
                return datetime.strptime(digits, "%Y%m%d").date()
            if len(digits) == 14:
                return datetime.strptime(digits, "%Y%m%d%H%M%S").date()
            if len(digits) == 12:
                return datetime.strptime(digits, "%Y%m%d%H%M").date()
        except ValueError:
            return None

        # ISO-like fallback
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None

    def _parse_total_infos(
        self,
        basic: Dict[str, Any],
        integration: Optional[Dict[str, Any]],
        is_world: bool,
    ) -> Dict[str, str]:
        """Extract totalInfos from API response into code->value dict."""
        lookup: Dict[str, str] = {}

        # Domestic: integration.totalInfos, World: basic.stockItemTotalInfos
        info_list = []
        if is_world:
            info_list = basic.get("stockItemTotalInfos") or []
        if integration:
            info_list = integration.get("totalInfos") or info_list

        for item in info_list:
            if not isinstance(item, dict):
                continue
            item_code = item.get("code", "")
            item_value = item.get("value", "")
            if item_code and item_value:
                lookup[item_code] = str(item_value)

        return lookup

    def _extract_recent_items(
        self,
        integration: Optional[Dict[str, Any]],
        list_keys: Tuple[str, ...],
        limit: int = 3,
    ) -> List[Dict[str, str]]:
        """
        Best-effort extraction for news/report-style item lists from integration.

        Returns up to `limit` items with keys: title, url, date, source.
        """
        if not integration:
            return []

        title_keys = (
            "title",
            "newsTitle",
            "articleTitle",
            "reportTitle",
            "researchTitle",
            "tit",
            "ttl",
            "subject",
            "name",
            "reportName",
        )
        url_keys = (
            "url",
            "linkUrl",
            "newsUrl",
            "articleUrl",
            "reportUrl",
            "researchUrl",
            "mobileUrl",
            "link",
        )
        date_keys = (
            "bizdate",
            "date",
            "pubDate",
            "publishedAt",
            "researchDate",
            "createdAt",
            "localTradedAt",
            "wdt",
        )
        source_keys = (
            "press",
            "media",
            "provider",
            "broker",
            "securitiesCompany",
            "companyName",
            "source",
            "bnm",
        )

        items: List[Dict[str, str]] = []
        seen_titles: set[str] = set()

        for list_key in list_keys:
            rows = integration.get(list_key)
            if not isinstance(rows, list):
                continue

            for row in rows:
                if not isinstance(row, dict):
                    continue

                title = self._pick_first_text(row, title_keys)
                if not title:
                    continue

                normalized_title = re.sub(r"\s+", " ", title).strip().lower()
                if normalized_title in seen_titles:
                    continue
                seen_titles.add(normalized_title)

                item_url = self._pick_first_text(row, url_keys) or ""
                if not item_url:
                    report_id = self._pick_first_text(row, ("id", "nid"))
                    if report_id and list_key in ("researches", "reports"):
                        item_url = f"https://finance.naver.com/research/company_read.naver?nid={report_id}"

                items.append(
                    {
                        "title": title,
                        "url": item_url,
                        "date": self._pick_first_text(row, date_keys) or "",
                        "source": self._pick_first_text(row, source_keys) or "",
                    }
                )

                if len(items) >= limit:
                    return items

        return items

    def _format_change_value(self, change_value: Optional[str], direction: Optional[str]) -> Optional[str]:
        """Format change value with sign prefix."""
        if not change_value:
            return None
        raw = str(change_value).strip()
        if not raw or raw == "0":
            return "0"
        if raw.startswith(("+", "-")):
            return raw
        if direction == "FALLING":
            return f"-{raw}"
        if direction == "RISING":
            return f"+{raw}"
        return raw

    def _format_rate(self, rate: Optional[str], direction: Optional[str]) -> Optional[str]:
        """Format rate with sign and % suffix."""
        if not rate:
            return None
        raw = str(rate).strip()
        if not raw:
            return None
        # Add sign if missing
        if not raw.startswith(("+", "-")):
            if direction == "FALLING":
                raw = f"-{raw}"
            elif direction == "RISING":
                raw = f"+{raw}"
        # Add % if missing
        if not raw.endswith("%"):
            raw = f"{raw}%"
        return raw

    def _rating_text(self, rating_val: Any) -> Optional[str]:
        """Convert numeric analyst rating to text."""
        try:
            val = float(str(rating_val))
        except (ValueError, TypeError):
            return None
        if val >= 4.5:
            return "적극매수"
        if val >= 3.5:
            return "매수"
        if val >= 2.5:
            return "중립"
        if val >= 1.5:
            return "매도"
        return "적극매도"

    # ── Search ──────────────────────────────────────────────────────────

    async def _fetch_search_candidates(self, query: str) -> List[StockSearchCandidate]:
        """Fetch search candidates from Naver front-api."""
        encoded = quote_plus(query.strip())
        url = self.SEARCH_URL.format(query=encoded)

        try:
            response = await self.http_client.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return []

        if not isinstance(data, dict):
            return []

        result = data.get("result") or {}
        items = result.get("items") or []

        candidates: List[StockSearchCandidate] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "")).strip()
            name = str(item.get("name", "")).strip()
            if not code or not name:
                continue

            reuters_code = item.get("reutersCode")
            market = item.get("typeCode") or item.get("typeName")
            nation = item.get("nationCode")

            candidates.append(StockSearchCandidate(
                code=code,
                name=name,
                market=market,
                reuters_code=reuters_code,
                nation_code=nation,
            ))

        return self._dedupe_candidates(candidates)

    # ── Symbol extraction from input ────────────────────────────────────

    def _extract_symbol_from_input(self, query: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract domestic/world stock symbol from raw input."""
        raw = query.strip()

        direct = self._normalize_stock_identifier(raw)
        if direct:
            source_hint = "world" if self._is_world_symbol(direct) else "domestic"
            return direct, source_hint

        domestic_match = re.search(r"\b(\d{6})\b", raw)
        if domestic_match and not is_web_url(raw):
            return domestic_match.group(1), "domestic"

        if not is_web_url(raw) or not is_naver_stock_url(raw):
            return None, None

        parsed = urlparse(raw)
        path = unquote(parsed.path)

        world_path = re.search(r"/worldstock/stock/([^/?#]+)", path, re.IGNORECASE)
        if world_path:
            symbol = self._normalize_stock_identifier(world_path.group(1))
            if symbol:
                return symbol, "world"

        domestic_path = re.search(r"/domestic/stock/([^/?#]+)", path, re.IGNORECASE)
        if domestic_path:
            symbol = self._normalize_stock_identifier(domestic_path.group(1))
            if symbol:
                hint = "world" if self._is_world_symbol(symbol) else "domestic"
                return symbol, hint

        legacy_domestic_path = re.search(r"/domestic/(\d{6})(?:/|$)", path, re.IGNORECASE)
        if legacy_domestic_path:
            return legacy_domestic_path.group(1), "domestic"

        query_dict = parse_qs(parsed.query)
        query_code_values = query_dict.get("code", [])
        if query_code_values:
            symbol = self._normalize_stock_identifier(query_code_values[0].strip())
            if symbol:
                hint = "world" if self._is_world_symbol(symbol) else "domestic"
                return symbol, hint

        return None, None

    # ── Candidate matching ──────────────────────────────────────────────

    def _pick_best_candidate(
        self,
        query: str,
        candidates: List[StockSearchCandidate],
    ) -> Optional[StockSearchCandidate]:
        """Pick best matching candidate with typo-aware fuzzy scoring."""
        if not candidates:
            return None

        # If the search API returns results, the first result is usually best
        # (Naver already does relevance ranking). Trust it for exact/close matches.
        first = candidates[0]
        normalized_query = self._normalize_text(query)
        first_name = self._normalize_text(first.name)

        if normalized_query == first_name:
            return first

        if first_name.startswith(normalized_query):
            return first

        # Score all candidates
        ranked: List[Tuple[float, StockSearchCandidate]] = []
        for candidate in candidates:
            score = self._score_candidate(normalized_query, candidate)
            ranked.append((score, candidate))

        ranked.sort(key=lambda item: item[0], reverse=True)
        best_score, best_candidate = ranked[0]

        if len(ranked) == 1 and best_score >= 0.50:
            return best_candidate

        if best_score >= 0.55:
            return best_candidate

        return None

    def _score_candidate(self, normalized_query: str, candidate: StockSearchCandidate) -> float:
        """Score candidate relevance to normalized query."""
        name = self._normalize_text(candidate.name)
        code = candidate.code.lower()

        if normalized_query == code:
            return 1.4
        if normalized_query and normalized_query == name:
            return 1.3
        if normalized_query and name.startswith(normalized_query):
            return 1.05
        if normalized_query and normalized_query in name:
            return 0.98

        ratio = SequenceMatcher(None, normalized_query, name).ratio() if normalized_query else 0.0
        length_penalty = abs(len(name) - len(normalized_query)) * 0.02
        return max(0.0, ratio - length_penalty)

    def _build_fallback_query(self, query: str) -> Optional[str]:
        """Build fallback query for typo recovery."""
        normalized = self._normalize_text(query)
        if len(normalized) < 2:
            return None
        return normalized[:2]

    def _dedupe_candidates(
        self,
        candidates: Iterable[StockSearchCandidate]
    ) -> List[StockSearchCandidate]:
        """Deduplicate candidates by code while preserving order."""
        seen = set()
        unique: List[StockSearchCandidate] = []
        for candidate in candidates:
            key = candidate.reuters_code or candidate.code
            if key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique

    # ── Helpers ──────────────────────────────────────────────────────────

    def _is_world_stock(self, candidate: StockSearchCandidate) -> bool:
        """Determine if candidate is a world stock."""
        if candidate.nation_code and candidate.nation_code != "KOR":
            return True
        if candidate.reuters_code and self._is_world_symbol(candidate.reuters_code):
            return True
        market = (candidate.market or "").upper()
        return self._is_world_market_text(market)

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"[^0-9a-zA-Z가-힣]", "", value).lower()

    def _normalize_stock_identifier(self, value: str) -> Optional[str]:
        cleaned = value.strip().upper()
        domestic_match = self.DOMESTIC_CODE_PATTERN.fullmatch(cleaned)
        if domestic_match:
            return domestic_match.group(1)
        world_match = self.WORLD_SYMBOL_PATTERN.fullmatch(cleaned)
        if world_match:
            return cleaned
        return None

    def _is_world_symbol(self, symbol: str) -> bool:
        return bool(self.WORLD_SYMBOL_PATTERN.fullmatch(symbol.strip().upper()))

    def _is_world_market_text(self, market_text: str) -> bool:
        if not market_text:
            return False
        world_keywords = ("NASDAQ", "NYSE", "AMEX", "US", "WORLD", "GLOBAL", "해외",
                          "나스닥", "뉴욕")
        return any(keyword in market_text for keyword in world_keywords)
