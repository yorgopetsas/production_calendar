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
    prod_color: str | None = None  # Optional second circle for production status.
    client_name: str = ""
    revisa_letters: str = ""
    revisa_modif: bool = False

