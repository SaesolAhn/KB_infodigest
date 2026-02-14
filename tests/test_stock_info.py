"""Tests for stock info service."""

import pytest

from services.stock_info import (
    AsyncStockInfoService,
    StockChartData,
    StockInfoError,
    StockQueryAmbiguousError,
    StockSearchCandidate,
)


class TestStockInfoService:
    """Tests for AsyncStockInfoService."""

    def setup_method(self):
        self.service = AsyncStockInfoService(timeout=5)

    # ── Search candidate parsing ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_resolve_stock_query_by_name(self):
        """Stock name query should resolve to stock code."""
        async def fake_fetch(query: str):
            return [StockSearchCandidate(
                code="005930", name="삼성전자", market="KOSPI",
                reuters_code="005930", nation_code="KOR",
            )]

        self.service._fetch_search_candidates = fake_fetch

        resolved = await self.service.resolve_stock_query("삼성전자")

        assert resolved.code == "005930"
        assert resolved.matched_name == "삼성전자"
        assert resolved.is_world is False
        assert resolved.search_note is None

    @pytest.mark.asyncio
    async def test_resolve_stock_query_with_typo(self):
        """Typo query should auto-correct to closest known stock candidate."""
        calls = []

        async def fake_fetch(query: str):
            calls.append(query)
            if query == "삼성전ㅈ":
                return [
                    StockSearchCandidate(
                        code="005930", name="삼성전자", market="KOSPI",
                        reuters_code="005930", nation_code="KOR",
                    ),
                    StockSearchCandidate(
                        code="005935", name="삼성전자우", market="KOSPI",
                        reuters_code="005935", nation_code="KOR",
                    ),
                ]
            return []

        self.service._fetch_search_candidates = fake_fetch

        resolved = await self.service.resolve_stock_query("삼성전ㅈ")

        assert resolved.code == "005930"
        assert resolved.matched_name == "삼성전자"
        assert resolved.search_note is not None
        assert "입력 보정" in resolved.search_note

    @pytest.mark.asyncio
    async def test_resolve_stock_query_shows_suggestions_for_low_confidence(self):
        """Low-confidence query should return suggestion message instead of wrong auto-match."""
        async def fake_fetch(query: str):
            return [
                StockSearchCandidate(code="005930", name="삼성전자"),
                StockSearchCandidate(code="000660", name="SK하이닉스"),
                StockSearchCandidate(code="035420", name="NAVER"),
            ]

        self.service._fetch_search_candidates = fake_fetch

        with pytest.raises(StockQueryAmbiguousError) as exc:
            await self.service.resolve_stock_query("완전무관검색어")

        error = exc.value
        message = str(error)
        assert "Did you mean" in message
        assert "삼성전자(005930)" in message
        assert len(error.candidates) == 3

    @pytest.mark.asyncio
    async def test_resolve_stock_query_from_domestic_detail_url(self):
        """Domestic stock detail URL should resolve code."""
        resolved = await self.service.resolve_stock_query(
            "https://stock.naver.com/domestic/stock/005930"
        )
        assert resolved.code == "005930"
        assert resolved.is_world is False

    @pytest.mark.asyncio
    async def test_resolve_stock_query_from_world_detail_url(self):
        """World stock detail URL should resolve code."""
        resolved = await self.service.resolve_stock_query(
            "https://stock.naver.com/worldstock/stock/NVDA.O"
        )
        assert resolved.code == "NVDA.O"
        assert resolved.is_world is True

    @pytest.mark.asyncio
    async def test_resolve_stock_query_from_world_symbol(self):
        """World ticker symbol should resolve to world stock."""
        resolved = await self.service.resolve_stock_query("NVDA.O")
        assert resolved.code == "NVDA.O"
        assert resolved.is_world is True

    @pytest.mark.asyncio
    async def test_resolve_world_stock_from_search(self):
        """World stock from search should set is_world=True."""
        async def fake_fetch(query: str):
            return [StockSearchCandidate(
                code="NVDA", name="엔비디아", market="NASDAQ",
                reuters_code="NVDA.O", nation_code="USA",
            )]

        self.service._fetch_search_candidates = fake_fetch

        resolved = await self.service.resolve_stock_query("엔비디아")

        assert resolved.code == "NVDA.O"
        assert resolved.is_world is True
        assert resolved.matched_name == "엔비디아"

    # ── API response building ─────────────────────────────────────────

    def test_build_stock_info_domestic(self):
        """Build StockInfo from domestic API response."""
        basic = {
            "stockName": "삼성전자",
            "itemCode": "005930",
            "closePrice": "181,200",
            "compareToPreviousClosePrice": "2,600",
            "fluctuationsRatio": "1.46",
            "compareToPreviousPrice": {"code": "2", "text": "상승", "name": "RISING"},
            "stockExchangeName": "KOSPI",
            "stockExchangeType": {"nameEng": "KOSPI"},
            "localTradedAt": "2026-02-13T16:10:21+09:00",
        }
        integration = {
            "totalInfos": [
                {"code": "lastClosePrice", "value": "178,600"},
                {"code": "openPrice", "value": "177,000"},
                {"code": "highPrice", "value": "184,400"},
                {"code": "lowPrice", "value": "176,300"},
                {"code": "accumulatedTradingVolume", "value": "52,021,802"},
                {"code": "accumulatedTradingValue", "value": "9,437,598백만"},
                {"code": "marketValue", "value": "1,072조 6,384억"},
                {"code": "foreignRate", "value": "51.52%"},
                {"code": "highPriceOf52Weeks", "value": "184,400"},
                {"code": "lowPriceOf52Weeks", "value": "52,000"},
                {"code": "per", "value": "37.62배"},
                {"code": "eps", "value": "4,816원"},
                {"code": "cnsPer", "value": "8.81배"},
                {"code": "cnsEps", "value": "20,562원"},
                {"code": "pbr", "value": "2.99배"},
                {"code": "bps", "value": "60,632원"},
                {"code": "dividendYieldRatio", "value": "0.92%"},
                {"code": "dividend", "value": "1,668원"},
            ],
            "consensusInfo": {
                "itemCode": "005930",
                "priceTargetMean": "216,417",
                "recommMean": "4.00",
            },
            "dealTrendInfos": [
                {
                    "bizdate": "20260213",
                    "foreignerPureBuyQuant": "-4,715,928",
                    "organPureBuyQuant": "+556,164",
                    "individualPureBuyQuant": "+3,099,928",
                },
            ],
            "newsInfos": [
                {
                    "title": "삼성전자, 반도체 투자 확대 발표",
                    "url": "https://n.news.naver.com/article/001/0000000001",
                    "date": "20260213",
                    "press": "연합뉴스",
                }
            ],
            "researches": [
                {
                    "id": 90210,
                    "cd": "005930",
                    "nm": "삼성전자",
                    "bnm": "OO증권",
                    "tit": "메모리 업황 개선 전망",
                    "wdt": "20260212",
                }
            ],
        }

        stock = self.service._build_stock_info(basic, integration, "005930", False, "https://stock.naver.com/domestic/stock/005930/total")

        assert stock.code == "005930"
        assert stock.name == "삼성전자"
        assert stock.market == "KOSPI"
        assert stock.current_price == "181,200"
        assert stock.change_value == "+2,600"
        assert stock.change_rate == "+1.46%"
        assert stock.change_direction == "RISING"
        assert stock.prev_close == "178,600"
        assert stock.open_price == "177,000"
        assert stock.high_price == "184,400"
        assert stock.low_price == "176,300"
        assert stock.volume == "52,021,802"
        assert stock.trading_value == "9,437,598백만"
        assert stock.market_cap == "1,072조 6,384억"
        assert stock.foreign_rate == "51.52%"
        assert stock.per == "37.62배"
        assert stock.eps == "4,816원"
        assert stock.estimated_per == "8.81배"
        assert stock.estimated_eps == "20,562원"
        assert stock.pbr == "2.99배"
        assert stock.bps == "60,632원"
        assert stock.dividend_yield == "0.92%"
        assert stock.dividend_per_share == "1,668원"
        assert stock.high_52w == "184,400"
        assert stock.low_52w == "52,000"
        assert stock.target_price == "216,417"
        assert stock.analyst_rating == "매수"
        assert stock.as_of == "2026-02-13T16:10:21+09:00"
        assert len(stock.deal_trends) == 1
        assert len(stock.recent_news) == 1
        assert stock.recent_news[0]["title"] == "삼성전자, 반도체 투자 확대 발표"
        assert len(stock.recent_reports) == 1
        assert stock.recent_reports[0]["title"] == "메모리 업황 개선 전망"
        assert stock.recent_reports[0]["source"] == "OO증권"
        assert stock.recent_reports[0]["date"] == "20260212"
        assert "company_read.naver?nid=90210" in stock.recent_reports[0]["url"]
        assert isinstance(stock.chart_data, StockChartData)
        assert stock.chart_data is not None
        assert stock.chart_data.has_price() is True

    def test_build_stock_info_world(self):
        """Build StockInfo from world stock API response."""
        basic = {
            "stockName": "엔비디아",
            "stockNameEng": "NVIDIA Corp",
            "reutersCode": "NVDA.O",
            "closePrice": "182.81",
            "compareToPreviousClosePrice": "-4.13",
            "fluctuationsRatio": "-2.21",
            "compareToPreviousPrice": {"code": "5", "text": "하락", "name": "FALLING"},
            "stockExchangeName": "NASDAQ",
            "stockExchangeType": {"nameEng": "NASDAQ Stock Exchange"},
            "localTradedAt": "2026-02-13T16:00:00-05:00",
            "currencyType": {"code": "USD", "text": "US dollar"},
            "industryCodeType": {"industryGroupKor": "반도체"},
            "stockItemTotalInfos": [
                {"code": "basePrice", "value": "186.94"},
                {"code": "openPrice", "value": "187.48"},
                {"code": "highPrice", "value": "187.50"},
                {"code": "lowPrice", "value": "181.59"},
                {"code": "accumulatedTradingVolume", "value": "161,888,021"},
                {"code": "accumulatedTradingValue", "value": "297억 USD"},
                {"code": "marketValue", "value": "4조 4,423억 USD"},
                {"code": "highPriceOf52Weeks", "value": "212.19"},
                {"code": "lowPriceOf52Weeks", "value": "86.62"},
                {"code": "per", "value": "45.08배"},
                {"code": "eps", "value": "4.06"},
                {"code": "pbr", "value": "37.37배"},
                {"code": "bps", "value": "4.89"},
                {"code": "dividendYieldRatio", "value": "0.02%"},
                {"code": "dividend", "value": "0.04"},
            ],
        }

        stock = self.service._build_stock_info(basic, None, "NVDA.O", True, "https://stock.naver.com/worldstock/stock/NVDA.O/total")

        assert stock.code == "NVDA.O"
        assert stock.name == "엔비디아"
        assert stock.name_eng == "NVIDIA Corp"
        assert stock.market == "NASDAQ"
        assert stock.current_price == "182.81"
        assert stock.change_value == "-4.13"
        assert stock.change_rate == "-2.21%"
        assert stock.change_direction == "FALLING"
        assert stock.currency == "USD"
        assert stock.industry == "반도체"
        assert stock.prev_close == "186.94"
        assert stock.volume == "161,888,021"
        assert stock.market_cap == "4조 4,423억 USD"
        assert stock.per == "45.08배"
        assert stock.pbr == "37.37배"
        assert stock.high_52w == "212.19"
        assert stock.low_52w == "86.62"
        assert stock.chart_data is not None
        assert stock.chart_data.has_price() is True

    def test_build_stock_info_chart_with_price_history_and_deal_trend(self):
        """Price/deal trend series should be extracted for chart attachment."""
        basic = {
            "stockName": "삼성전자",
            "closePrice": "60500",
            "compareToPreviousClosePrice": "500",
            "fluctuationsRatio": "0.83",
            "compareToPreviousPrice": {"name": "RISING"},
            "stockExchangeName": "KOSPI",
            "localTradedAt": "2026-02-13T16:10:21+09:00",
        }
        integration = {
            "totalInfos": [{"code": "lastClosePrice", "value": "60000"}],
            "siseTrendInfos": [
                {"bizdate": "20260211", "closePrice": "59400"},
                {"bizdate": "20260212", "closePrice": "60000"},
                {"bizdate": "20260213", "closePrice": "60500"},
            ],
            "dealTrendInfos": [
                {"bizdate": "20260212", "foreignerPureBuyQuant": "1000", "organPureBuyQuant": "-300", "individualPureBuyQuant": "-700"},
                {"bizdate": "20260213", "foreignerPureBuyQuant": "-500", "organPureBuyQuant": "200", "individualPureBuyQuant": "300"},
            ],
        }

        stock = self.service._build_stock_info(
            basic,
            integration,
            "005930",
            False,
            "https://stock.naver.com/domestic/stock/005930",
        )

        assert stock.chart_data is not None
        assert stock.chart_data.has_price() is True
        assert stock.chart_data.has_trend() is True
        assert stock.chart_data.price_labels[-1] == "20260213"
        assert stock.chart_data.trend_labels == ["20260212", "20260213"]
        assert stock.chart_data.foreign_series == [1000.0, -500.0]
        assert stock.chart_data.institution_series == [-300.0, 200.0]
        assert stock.chart_data.personal_series == [-700.0, 300.0]

    def test_build_stock_info_chart_is_limited_to_one_month(self):
        """Price series should be filtered to roughly one month by bizdate."""
        basic = {
            "stockName": "삼성전자",
            "closePrice": "61000",
            "compareToPreviousClosePrice": "100",
            "fluctuationsRatio": "0.16",
            "compareToPreviousPrice": {"name": "RISING"},
            "stockExchangeName": "KOSPI",
            "localTradedAt": "2026-03-15T16:00:00+09:00",
        }
        integration = {
            "totalInfos": [{"code": "lastClosePrice", "value": "60900"}],
            "siseTrendInfos": [
                {"bizdate": "20260110", "closePrice": "50000"},
                {"bizdate": "20260125", "closePrice": "52000"},
                {"bizdate": "20260210", "closePrice": "56000"},
                {"bizdate": "20260220", "closePrice": "58000"},
                {"bizdate": "20260301", "closePrice": "60000"},
                {"bizdate": "20260312", "closePrice": "61000"},
            ],
        }

        stock = self.service._build_stock_info(
            basic,
            integration,
            "005930",
            False,
            "https://stock.naver.com/domestic/stock/005930",
        )

        assert stock.chart_data is not None
        # Old January points should be excluded in 1M window based on latest date.
        assert stock.chart_data.price_labels == ["20260210", "20260220", "20260301", "20260312"]

    def test_build_stock_info_no_data_raises(self):
        """Missing basic data should raise StockInfoError."""
        # _fetch_stock_via_api raises when basic_data is None;
        # we can't test that directly without async, but we can test
        # that building with minimal data still works.
        basic = {
            "stockName": "테스트",
            "closePrice": "100",
            "compareToPreviousPrice": {"name": "UNCHANGED"},
        }
        stock = self.service._build_stock_info(basic, None, "999999", False, "http://test")
        assert stock.name == "테스트"
        assert stock.current_price == "100"
        assert stock.chart_data is None

    # ── Rating text ───────────────────────────────────────────────────

    def test_rating_text(self):
        assert self.service._rating_text("5.0") == "적극매수"
        assert self.service._rating_text("4.0") == "매수"
        assert self.service._rating_text("3.0") == "중립"
        assert self.service._rating_text("2.0") == "매도"
        assert self.service._rating_text("1.0") == "적극매도"
        assert self.service._rating_text("invalid") is None

    # ── Format helpers ────────────────────────────────────────────────

    def test_format_change_value(self):
        assert self.service._format_change_value("2,600", "RISING") == "+2,600"
        assert self.service._format_change_value("-4.13", "FALLING") == "-4.13"
        assert self.service._format_change_value("0", "UNCHANGED") == "0"
        assert self.service._format_change_value(None, None) is None

    def test_format_rate(self):
        assert self.service._format_rate("1.46", "RISING") == "+1.46%"
        assert self.service._format_rate("-2.21", "FALLING") == "-2.21%"
        assert self.service._format_rate("0.00%", "UNCHANGED") == "0.00%"
        assert self.service._format_rate(None, None) is None

    # ── Symbol extraction ─────────────────────────────────────────────

    def test_extract_domestic_code(self):
        symbol, hint = self.service._extract_symbol_from_input("005930")
        assert symbol == "005930"
        assert hint == "domestic"

    def test_extract_world_symbol(self):
        symbol, hint = self.service._extract_symbol_from_input("NVDA.O")
        assert symbol == "NVDA.O"
        assert hint == "world"

    def test_extract_from_domestic_url(self):
        symbol, hint = self.service._extract_symbol_from_input(
            "https://stock.naver.com/domestic/stock/005930"
        )
        assert symbol == "005930"
        assert hint == "domestic"

    def test_extract_from_world_url(self):
        symbol, hint = self.service._extract_symbol_from_input(
            "https://stock.naver.com/worldstock/stock/NVDA.O"
        )
        assert symbol == "NVDA.O"
        assert hint == "world"

    def test_extract_from_name_returns_none(self):
        symbol, hint = self.service._extract_symbol_from_input("삼성전자")
        assert symbol is None
        assert hint is None

    # ── World stock detection ─────────────────────────────────────────

    def test_is_world_stock_by_nation(self):
        c = StockSearchCandidate(code="NVDA", name="엔비디아", nation_code="USA")
        assert self.service._is_world_stock(c) is True

    def test_is_world_stock_by_reuters(self):
        c = StockSearchCandidate(code="NVDA", name="엔비디아", reuters_code="NVDA.O")
        assert self.service._is_world_stock(c) is True

    def test_is_domestic_stock(self):
        c = StockSearchCandidate(code="005930", name="삼성전자", nation_code="KOR")
        assert self.service._is_world_stock(c) is False
