from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderItem:
    """
    Represents one line displayed inside a calendar day cell.
    """

    text: str
    color: str  # Tkinter fill color for the status circle.
    type: str

