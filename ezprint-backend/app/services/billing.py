"""Pricing calculation.

Ported/simplified from the logic that used to live in
`shared/file_processor.py::calculate_billing`. Business rules:

    - Per page rate depends on (color mode, single/double sided)
    - In "Color" mode, only pages actually containing color are billed at the
      color rate; the rest fall through to the BW rate. This keeps billing
      fair when a mostly-BW document has a few color pages.
    - Multiply by `copies`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PricingRates:
    bw_single: float = 2.0
    bw_double: float = 1.5
    color_single: float = 10.0
    color_double: float = 8.0


@dataclass(frozen=True)
class JobBillingInputs:
    total_pages: int
    color_pages: int
    copies: int = 1
    color_mode: str = "Black & White"   # "Color" or "Black & White"
    print_side: str = "Single"          # "Single" or "Double"


def calculate_amount(rates: PricingRates, inputs: JobBillingInputs) -> float:
    total_pages = max(0, inputs.total_pages)
    color_pages = max(0, min(inputs.color_pages, total_pages))
    bw_pages = max(0, total_pages - color_pages)
    copies = max(1, inputs.copies)

    double_sided = inputs.print_side.lower().startswith("double")
    bw_rate = rates.bw_double if double_sided else rates.bw_single
    color_rate = rates.color_double if double_sided else rates.color_single

    if inputs.color_mode.lower().startswith("color"):
        per_copy = (color_pages * color_rate) + (bw_pages * bw_rate)
    else:
        per_copy = total_pages * bw_rate

    return round(per_copy * copies, 2)
