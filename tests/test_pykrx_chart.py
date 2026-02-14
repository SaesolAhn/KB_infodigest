"""Tests for pykrx candlestick chart module."""

import os

from services.pykrx_chart import PykrxChartService


class TestPykrxChartService:
    """Tests for pykrx-based chart generation."""

    def test_generate_candle_chart_with_volume(self):
        """Should generate non-empty chart image from normalized OHLCV rows."""
        service = PykrxChartService(default_period_days=31)

        def fake_fetch(code: str, start_yyyymmdd: str, end_yyyymmdd: str):
            _ = (code, start_yyyymmdd, end_yyyymmdd)
            return [
                {"date": "2026-01-10", "시가": "60,000", "고가": "61,000", "저가": "59,500", "종가": "60,500", "거래량": "1,500,000"},
                {"date": "2026-01-13", "시가": "60,500", "고가": "62,000", "저가": "60,200", "종가": "61,900", "거래량": "2,100,000"},
                {"date": "2026-01-14", "시가": "61,900", "고가": "62,200", "저가": "60,900", "종가": "61,100", "거래량": "1,700,000"},
                {"date": "2026-01-15", "시가": "61,100", "고가": "63,100", "저가": "61,000", "종가": "62,800", "거래량": "2,600,000"},
            ]

        service._fetch_ohlcv_rows = fake_fetch  # type: ignore[method-assign]

        output = service.generate_candlestick_with_volume(
            code="005930",
            title="SamsungElec",
            font_name="DejaVu Sans",
        )

        assert output is not None
        assert os.path.exists(output)
        assert os.path.getsize(output) > 0

        os.remove(output)

    def test_generate_candle_chart_with_trend_panel(self):
        """Should render a chart image with trend subplot inputs."""
        service = PykrxChartService(default_period_days=31)

        def fake_fetch(code: str, start_yyyymmdd: str, end_yyyymmdd: str):
            _ = (code, start_yyyymmdd, end_yyyymmdd)
            return [
                {"date": "2026-01-10", "시가": "60,000", "고가": "61,000", "저가": "59,500", "종가": "60,500"},
                {"date": "2026-01-13", "시가": "60,500", "고가": "62,000", "저가": "60,200", "종가": "61,900"},
                {"date": "2026-01-14", "시가": "61,900", "고가": "62,200", "저가": "60,900", "종가": "61,100"},
                {"date": "2026-01-15", "시가": "61,100", "고가": "63,100", "저가": "61,000", "종가": "62,800"},
            ]

        service._fetch_ohlcv_rows = fake_fetch  # type: ignore[method-assign]

        output = service.generate_candlestick_with_volume(
            code="005930",
            title="SamsungElec",
            font_name="DejaVu Sans",
            trend_labels=["20260110", "20260113", "20260114", "20260115"],
            personal_series=[-100.0, 50.0, 30.0, -10.0],
            institution_series=[20.0, -10.0, 0.0, 40.0],
            foreign_series=[80.0, -40.0, -30.0, -30.0],
        )

        assert output is not None
        assert os.path.exists(output)
        assert os.path.getsize(output) > 0

        os.remove(output)

    def test_returns_none_for_non_domestic_code(self):
        """World symbol should not generate pykrx domestic candle chart."""
        service = PykrxChartService(default_period_days=31)
        output = service.generate_candlestick_with_volume("NVDA.O", title="엔비디아")
        assert output is None

    def test_returns_none_for_too_few_rows(self):
        """Requires at least 2 OHLCV rows."""
        service = PykrxChartService(default_period_days=31)

        def fake_fetch(code: str, start_yyyymmdd: str, end_yyyymmdd: str):
            _ = (code, start_yyyymmdd, end_yyyymmdd)
            return [
                {"date": "2026-01-10", "시가": "60,000", "고가": "61,000", "저가": "59,500", "종가": "60,500", "거래량": "1,500,000"},
            ]

        service._fetch_ohlcv_rows = fake_fetch  # type: ignore[method-assign]

        output = service.generate_candlestick_with_volume("005930", title="삼성전자")
        assert output is None
