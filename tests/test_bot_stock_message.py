"""Tests for stock message formatting in bot."""

from bot import InfoDigestBot
from services.stock_info import StockChartData, StockInfo


def _make_bot() -> InfoDigestBot:
    """Create bot instance without running full constructor."""
    return InfoDigestBot.__new__(InfoDigestBot)


def _make_stock(deal_trends=None) -> StockInfo:
    return StockInfo(
        code="005930",
        name="삼성전자",
        market="KOSPI",
        current_price="60,000",
        change_value="+500",
        change_rate="+0.84%",
        change_direction="RISING",
        low_52w="50,000",
        high_52w="72,000",
        deal_trends=deal_trends or [],
    )


def test_format_stock_message_includes_latest_inflow_breakdown() -> None:
    bot = _make_bot()
    stock = _make_stock(
        deal_trends=[
            {"date": "20260212", "individual": "-700", "institution": "-300", "foreign": "1000"},
            {"date": "20260213", "individual": "300", "institution": "200", "foreign": "-500"},
        ]
    )

    message = bot._format_stock_message(stock)

    assert "*삼성전자*" in message
    assert "🧭 *수급(최근)*" in message
    assert "02/13 개인 300 · 기관 200 · 외국인 -500" in message
    assert "02/12 개인 -700 · 기관 -300 · 외국인 1000" not in message


def test_format_stock_message_omits_inflow_breakdown_without_trends() -> None:
    bot = _make_bot()
    stock = _make_stock(deal_trends=[])

    message = bot._format_stock_message(stock)

    assert "🧭 *수급(최근)*" not in message


def test_format_stock_message_includes_recent_news_and_reports() -> None:
    bot = _make_bot()
    stock = _make_stock()
    stock.recent_news = [
        {"title": "삼성전자, 차세대 패키징 투자 확대", "source": "연합뉴스", "date": "20260213"},
    ]
    stock.recent_reports = [
        {"title": "메모리 업황 회복 가시화", "source": "OO증권", "date": "20260212"},
    ]

    message = bot._format_stock_message(stock)

    assert "📰 *최근 뉴스*" in message
    assert "📑 *최근 리포트*" in message
    assert "삼성전자, 차세대 패키징 투자 확대" in message
    assert "메모리 업황 회복 가시화" in message


def test_domestic_with_trend_still_uses_pykrx_chart() -> None:
    bot = _make_bot()
    stock = _make_stock()
    stock.chart_data = StockChartData(
        trend_labels=["20260212", "20260213"],
        personal_series=[-700.0, 300.0],
        institution_series=[-300.0, 200.0],
        foreign_series=[1000.0, -500.0],
    )

    assert bot._should_use_pykrx_chart(stock) is True
