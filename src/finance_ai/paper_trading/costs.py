"""Simulierte Handelskosten: Gebühren, Slippage und Steuern.

Die Standardwerte sind bewusst eher vorsichtig gewählt, weil Paper Trading ohne
Kosten den Vorsprung eines Agenten überschätzt.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CostModel:
    """Kosten pro Trade.

    - `fee_fixed` + `fee_rate` × Ordervolumen: Ordergebühr des Brokers.
    - `slippage_rate`: Käufe werden um diesen Anteil teurer, Verkäufe billiger
      ausgeführt als der Kurs. Bei kleinen Werten mit großem Spread sind 0,5 %
      eher noch optimistisch.
    - `tax_rate`: Steuer auf realisierte Gewinne. Standard: Abgeltungsteuer
      25 % plus Solidaritätszuschlag (5,5 % davon) = 26,375 %, ohne
      Kirchensteuer und ohne Sparerpauschbetrag.
    """

    fee_fixed: Decimal = Decimal("1")
    fee_rate: Decimal = Decimal("0")
    slippage_rate: Decimal = Decimal("0.005")
    tax_rate: Decimal = Decimal("0.26375")

    def __post_init__(self) -> None:
        for name in ("fee_fixed", "fee_rate", "slippage_rate", "tax_rate"):
            value = getattr(self, name)
            if isinstance(value, (float, bool)):
                raise TypeError(f"{name} als Decimal angeben, nicht {type(value).__name__}")
            value = Decimal(value)
            if not value.is_finite() or value < 0:
                raise ValueError(f"{name} darf nicht negativ sein")
            object.__setattr__(self, name, value)
        for name in ("fee_rate", "slippage_rate", "tax_rate"):
            if getattr(self, name) >= 1:
                raise ValueError(f"{name} muss unter 1 (100 %) liegen")

    def fee(self, gross: Decimal) -> Decimal:
        return self.fee_fixed + gross * self.fee_rate

    def buy_price(self, quote: Decimal) -> Decimal:
        return quote * (1 + self.slippage_rate)

    def sell_price(self, quote: Decimal) -> Decimal:
        return quote * (1 - self.slippage_rate)
