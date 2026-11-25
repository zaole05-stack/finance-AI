from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finance_ai.core.models import (
    MAIN_PORTFOLIO,
    Order,
    Position,
    Side,
    Signal,
    shadow_portfolio,
)

T0 = datetime(2026, 11, 25, 14, 30, tzinfo=UTC)


def make_signal(**overrides) -> Signal:
    values = dict(
        expert="insider",
        ticker="abcd",
        side=Side.BUY,
        source_url="https://www.sec.gov/Archives/edgar/data/1/form4.xml",
        summary="CEO kauft 10.000 Aktien",
        observed_at=T0,
        created_at=T0 + timedelta(minutes=5),
    )
    values.update(overrides)
    return Signal(**values)


def make_order(**overrides) -> Order:
    values = dict(
        portfolio=MAIN_PORTFOLIO,
        ticker="ABCD",
        side=Side.BUY,
        quantity=Decimal("10"),
        created_at=T0,
        signal_ids=("s1",),
        rationale="Insider-Kauf",
    )
    values.update(overrides)
    return Order(**values)


class TestSignal:
    def test_normalizes_ticker_and_side(self):
        signal = make_signal(ticker="  abcd ", side="buy")
        assert signal.ticker == "ABCD"
        assert signal.side is Side.BUY

    def test_generates_unique_ids(self):
        assert make_signal().id != make_signal().id

    def test_is_immutable(self):
        with pytest.raises(FrozenInstanceError):
            make_signal().ticker = "XYZ"

    @pytest.mark.parametrize(
        "url", ["", "keine-url", "ftp://example.com/x", "https://", "javascript:alert(1)"]
    )
    def test_requires_http_source_url(self, url):
        with pytest.raises(ValueError, match="Quellenlink"):
            make_signal(source_url=url)

    @pytest.mark.parametrize("field", ["expert", "ticker", "summary"])
    def test_rejects_empty_text(self, field):
        with pytest.raises(ValueError):
            make_signal(**{field: "   "})

    def test_rejects_unknown_side(self):
        with pytest.raises(ValueError):
            make_signal(side="hold")

    def test_requires_timezone(self):
        with pytest.raises(ValueError, match="Zeitzone"):
            make_signal(observed_at=datetime(2026, 11, 25, 14, 30))

    def test_created_before_observed_is_rejected(self):
        with pytest.raises(ValueError, match="observed_at"):
            make_signal(created_at=T0 - timedelta(seconds=1))

    def test_accepts_other_timezones(self):
        cet = timezone(timedelta(hours=1))
        signal = make_signal(observed_at=T0.astimezone(cet), created_at=T0)
        assert signal.created_at == signal.observed_at

    @pytest.mark.parametrize("confidence", [-0.1, 1.1, True])
    def test_confidence_range(self, confidence):
        with pytest.raises(ValueError, match="confidence"):
            make_signal(confidence=confidence)

    @pytest.mark.parametrize("confidence", [0.0, 1.0])
    def test_confidence_bounds_allowed(self, confidence):
        assert make_signal(confidence=confidence).confidence == confidence


class TestOrder:
    def test_converts_quantity_and_signal_ids(self):
        order = make_order(quantity="2.5", signal_ids=["s1", "s2"])
        assert order.quantity == Decimal("2.5")
        assert order.signal_ids == ("s1", "s2")

    def test_requires_at_least_one_signal(self):
        with pytest.raises(ValueError, match="mindestens ein Signal"):
            make_order(signal_ids=())

    def test_rejects_duplicate_signal_ids(self):
        with pytest.raises(ValueError, match="doppelte"):
            make_order(signal_ids=("s1", "s1"))

    @pytest.mark.parametrize("quantity", [0, "-1", "NaN", "Infinity", "abc"])
    def test_rejects_invalid_quantity(self, quantity):
        with pytest.raises(ValueError):
            make_order(quantity=quantity)

    def test_rejects_float_quantity(self):
        with pytest.raises(TypeError, match="float"):
            make_order(quantity=0.1)

    def test_requires_rationale(self):
        with pytest.raises(ValueError):
            make_order(rationale="")

    def test_replace_revalidates(self):
        with pytest.raises(ValueError):
            replace(make_order(), quantity=Decimal("0"))


class TestPosition:
    def test_cost_basis(self):
        position = Position("main", "abcd", Decimal("3"), Decimal("10.50"))
        assert position.ticker == "ABCD"
        assert position.cost_basis == Decimal("31.50")

    def test_rejects_non_positive_values(self):
        with pytest.raises(ValueError):
            Position("main", "ABCD", Decimal("0"), Decimal("1"))
        with pytest.raises(ValueError):
            Position("main", "ABCD", Decimal("1"), Decimal("-1"))


def test_shadow_portfolio_name():
    assert shadow_portfolio("insider") == "shadow:insider"
    with pytest.raises(ValueError):
        shadow_portfolio(" ")
