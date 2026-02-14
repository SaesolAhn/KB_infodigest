"""Candlestick chart generator using pykrx."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


class PykrxChartService:
    """Generate domestic stock candlestick charts using pykrx OHLCV."""

    def __init__(self, default_period_days: int = 31):
        self.default_period_days = default_period_days

    def generate_candlestick_with_volume(
        self,
        code: str,
        title: Optional[str] = None,
        period_days: Optional[int] = None,
        font_name: Optional[str] = None,
        trend_labels: Optional[List[str]] = None,
        personal_series: Optional[List[float]] = None,
        institution_series: Optional[List[float]] = None,
        foreign_series: Optional[List[float]] = None,
    ) -> Optional[str]:
        """Create candlestick chart image file and return its path."""
        if not re.fullmatch(r"\d{6}", (code or "").strip()):
            return None

        days = period_days or self.default_period_days
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days)

        rows = self._fetch_ohlcv_rows(
            code=code,
            start_yyyymmdd=start_dt.strftime("%Y%m%d"),
            end_yyyymmdd=end_dt.strftime("%Y%m%d"),
        )
        normalized = self._normalize_ohlcv_rows(rows)
        if len(normalized) < 2:
            return None

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from matplotlib import font_manager
            from matplotlib.patches import Rectangle
        except Exception:
            return None

        resolved_font = self._resolve_font_name(font_name, font_manager)
        plt.rcParams["font.family"] = resolved_font
        plt.rcParams["axes.unicode_minus"] = False

        has_trend = self._has_trend_panel(
            trend_labels=trend_labels,
            personal_series=personal_series,
            institution_series=institution_series,
            foreign_series=foreign_series,
        )
        if has_trend:
            fig, (ax_price, ax_trend) = plt.subplots(
                nrows=2,
                ncols=1,
                figsize=(11, 8.6),
                gridspec_kw={"height_ratios": [2.8, 2.4]},
                constrained_layout=False,
            )
        else:
            fig, ax_price = plt.subplots(
                nrows=1,
                ncols=1,
                figsize=(11, 6),
                constrained_layout=False,
            )
            ax_trend = None

        fig.patch.set_facecolor("#FAFAFA")
        ax_price.set_facecolor("#FAFAFA")
        if ax_trend is not None:
            ax_trend.set_facecolor("#FAFAFA")

        x_values = list(range(len(normalized)))
        labels = [row["label"] for row in normalized]

        up_color = "#E3120B"
        down_color = "#005689"
        neutral_color = "#767676"

        # Candle + wick
        for i, row in enumerate(normalized):
            open_p = row["open"]
            high_p = row["high"]
            low_p = row["low"]
            close_p = row["close"]

            if close_p > open_p:
                color = up_color
            elif close_p < open_p:
                color = down_color
            else:
                color = neutral_color

            ax_price.vlines(i, low_p, high_p, color=color, linewidth=1.1, alpha=0.95)
            body_bottom = min(open_p, close_p)
            body_height = max(abs(close_p - open_p), max(close_p, open_p) * 0.0001)
            ax_price.add_patch(
                Rectangle(
                    (i - 0.32, body_bottom),
                    0.64,
                    body_height,
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.8,
                    alpha=0.95,
                )
            )

        # Economist-like heading accents
        fig.text(0.02, 0.955, "THE STOCK BRIEFING", fontsize=9, color=up_color, weight="bold")
        fig.add_artist(
            plt.Line2D(
                [0.02, 0.19],
                [0.948, 0.948],
                transform=fig.transFigure,
                color=up_color,
                linewidth=2.4,
            )
        )

        title_text = title or code
        fig.suptitle(
            f"{title_text} ({code}) - 1M",
            x=0.02,
            y=0.915,
            ha="left",
            fontsize=13,
            fontweight="bold",
            color="#1A1A1A",
        )

        ax_price.set_title(
            "Price (Candlestick)",
            loc="left",
            fontsize=10.8,
            color="#1A1A1A",
            fontweight="bold",
            pad=10,
        )

        self._style_axis(ax_price)
        ax_price.margins(x=0.01)

        tick_step = max(1, len(x_values) // 8)
        tick_positions = x_values[::tick_step]
        tick_labels = labels[::tick_step]
        ax_price.set_xticks(tick_positions)
        ax_price.set_xticklabels(tick_labels, rotation=35, ha="right", fontsize=8.5)

        if ax_trend is not None and trend_labels is not None:
            trend_x = list(range(len(trend_labels)))
            ax_trend.axhline(0, color="#888888", linewidth=1.0, alpha=0.7)

            if personal_series and len(personal_series) == len(trend_x):
                ax_trend.plot(trend_x, personal_series, label="개인", color="#E3120B", linewidth=1.7)
            if institution_series and len(institution_series) == len(trend_x):
                ax_trend.plot(trend_x, institution_series, label="기관", color="#767676", linewidth=1.7)
            if foreign_series and len(foreign_series) == len(trend_x):
                ax_trend.plot(trend_x, foreign_series, label="외국인", color="#005689", linewidth=1.7)

            ax_trend.set_title(
                "매매동향 (1M)",
                loc="left",
                fontsize=10.6,
                color="#1A1A1A",
                fontweight="bold",
                pad=8,
            )
            ax_trend.grid(alpha=0.18, color="#DDDDDD", linewidth=0.7)
            self._style_axis(ax_trend)
            ax_trend.legend(fontsize=9, loc="best")

            trend_tick_step = max(1, len(trend_x) // 8)
            trend_tick_positions = trend_x[::trend_tick_step]
            trend_tick_labels = [
                self._short_date_label(str(label))
                for label in trend_labels[::trend_tick_step]
            ]
            ax_trend.set_xticks(trend_tick_positions)
            ax_trend.set_xticklabels(trend_tick_labels, rotation=35, ha="right", fontsize=8.5)

        if ax_trend is not None:
            fig.subplots_adjust(top=0.82, bottom=0.10, left=0.08, right=0.98, hspace=0.30)
        else:
            fig.subplots_adjust(top=0.82, bottom=0.18, left=0.08, right=0.98)

        fig.text(0.98, 0.02, "Source: pykrx / KRX", ha="right", fontsize=7.5, color="#777777")

        tmp = tempfile.NamedTemporaryFile(suffix=".png", prefix="pykrx_candle_", delete=False)
        output_path = tmp.name
        tmp.close()

        fig.savefig(output_path, dpi=160, bbox_inches="tight")
        plt.close(fig)

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            return None
        return output_path

    def _fetch_ohlcv_rows(
        self,
        code: str,
        start_yyyymmdd: str,
        end_yyyymmdd: str,
    ) -> List[Dict[str, Any]]:
        """Fetch OHLCV rows from pykrx and convert to list dict format."""
        try:
            from pykrx import stock
        except Exception:
            return []

        try:
            df = stock.get_market_ohlcv_by_date(start_yyyymmdd, end_yyyymmdd, code)
        except Exception:
            return []

        if df is None or len(df) == 0:
            return []

        rows: List[Dict[str, Any]] = []
        for idx, series in df.iterrows():
            if hasattr(idx, "strftime"):
                label = idx.strftime("%Y-%m-%d")
            else:
                label = str(idx)
            row_dict = series.to_dict() if hasattr(series, "to_dict") else dict(series)
            row_dict["date"] = label
            rows.append(row_dict)
        return rows

    def _normalize_ohlcv_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize varied OHLCV key names to unified numeric rows."""
        normalized: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            open_v = self._to_float(self._pick(row, ("시가", "open", "Open")))
            high_v = self._to_float(self._pick(row, ("고가", "high", "High")))
            low_v = self._to_float(self._pick(row, ("저가", "low", "Low")))
            close_v = self._to_float(self._pick(row, ("종가", "close", "Close")))
            if None in (open_v, high_v, low_v, close_v):
                continue

            label_raw = str(self._pick(row, ("date", "일자", "날짜", "Date")) or "")
            label = self._short_date_label(label_raw)

            normalized.append(
                {
                    "label": label,
                    "open": open_v,
                    "high": high_v,
                    "low": low_v,
                    "close": close_v,
                }
            )

        return normalized

    def _pick(self, row: Dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in row:
                return row[key]
        return None

    def _to_float(self, value: Any) -> Optional[float]:
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

    def _short_date_label(self, raw: str) -> str:
        digits = re.sub(r"[^0-9]", "", raw)
        if len(digits) >= 8:
            return f"{digits[4:6]}-{digits[6:8]}"
        return raw

    def _resolve_font_name(self, preferred: Optional[str], font_manager) -> str:
        if preferred:
            return preferred

        candidates = [
            "Apple SD Gothic Neo",
            "AppleGothic",
            "NanumGothic",
            "NanumSquare",
            "Noto Sans CJK KR",
            "Noto Sans KR",
            "Malgun Gothic",
            "Arial Unicode MS",
            "DejaVu Sans",
        ]
        installed = {font.name for font in font_manager.fontManager.ttflist}
        for name in candidates:
            if name in installed:
                return name
        return "DejaVu Sans"

    def _style_axis(self, ax) -> None:
        ax.grid(False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#7D7D7D")
        ax.spines["bottom"].set_color("#7D7D7D")
        ax.spines["left"].set_linewidth(1.1)
        ax.spines["bottom"].set_linewidth(1.1)
        ax.tick_params(axis="both", colors="#2E2E2E", labelsize=8.5, width=0.9, length=4)

    def _has_trend_panel(
        self,
        trend_labels: Optional[List[str]],
        personal_series: Optional[List[float]],
        institution_series: Optional[List[float]],
        foreign_series: Optional[List[float]],
    ) -> bool:
        if not trend_labels or len(trend_labels) < 2:
            return False

        points = len(trend_labels)
        has_personal = personal_series is not None and len(personal_series) == points
        has_institution = institution_series is not None and len(institution_series) == points
        has_foreign = foreign_series is not None and len(foreign_series) == points
        return has_personal or has_institution or has_foreign
