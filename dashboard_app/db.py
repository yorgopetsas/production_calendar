from __future__ import annotations

import re
from datetime import datetime, date
from typing import Dict, List

import pyodbc

from dashboard_app.settings import Settings
from dashboard_app.models import OrderItem


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\.]*$")


def _sanitize_identifier(identifier: str) -> str:
    """
    Basic safety to prevent accidental SQL injection via table/column names.
    We allow optional schema prefix (e.g., `dbo.Orders`) and plain identifiers.
    """
    if not _IDENTIFIER_RE.match(identifier):
        raise ValueError(f"Invalid SQL identifier: {identifier!r}")
    return identifier


def _to_date(val) -> date:
    if val is None:
        raise ValueError("Unexpected NULL date value.")
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    # pyodbc often returns datetime for datetime2; datetime is also a date.
    if hasattr(val, "date"):
        return val.date()
    # Fallback if driver returns string (e.g. "2026-01-07 00:00:00.000").
    s = str(val).strip()
    # Common SQL varchar formats we might see.
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    # Last resort: try ISO parser (handles some other variations).
    return datetime.fromisoformat(s).date()


def fetch_orders_by_date(
    settings: Settings,
    start_dt: datetime,
    end_dt: datetime,
) -> Dict[date, List[OrderItem]]:
    """
    Fetch orders whose delivery date overlaps the given [start_dt, end_dt) window.
    Returns: {date -> [order_id_str, ...]}
    """
    table = _sanitize_identifier(settings.orders_table)
    order_id_col = _sanitize_identifier(settings.order_id_field)
    delivery_date_col = _sanitize_identifier(settings.delivery_date_field)
    client_name_col = _sanitize_identifier("NomCli")
    order_type_col = _sanitize_identifier("TipPed")
    status_cols = [
        _sanitize_identifier("RevisaVen"),
        _sanitize_identifier("RevisaCom"),
        _sanitize_identifier("RevisaBoto"),
        _sanitize_identifier("RevisaProd"),
        _sanitize_identifier("RevisaTecnico"),
        _sanitize_identifier("RevisaAlm"),
    ]
    status_expr = ", ".join(status_cols)
    order_type = _sanitize_identifier("TipPed")

    # Note: identifiers can't be passed as SQL parameters; only values can.
    # If delivery_date_col is a varchar, converting in SQL avoids relying on implicit conversion rules.
    delivery_expr = f"TRY_CONVERT(datetime, {delivery_date_col})"
    sql = (
        f"SELECT {order_id_col}, {delivery_expr}, {client_name_col}, {order_type}, {status_expr} "
        f"FROM {table} "
        f"WHERE {delivery_expr} >= ? AND {delivery_expr} < ? AND CodSer = 'B' AND (TipPed = '1    ' OR TipPed = '2    ' OR TipPed = '3    ') "
        f"ORDER BY {delivery_expr}, {order_id_col}"
    )

    conn_str = (
        f"DRIVER={{{settings.db_driver}}};"
        f"SERVER={settings.db_server},{settings.db_port};"
        f"DATABASE={settings.db_name};"
        f"UID={settings.db_user};"
        f"PWD={settings.db_password};"
        f"TrustServerCertificate=yes;"
    )

    orders_by_day: Dict[date, List[OrderItem]] = {}
    with pyodbc.connect(conn_str, timeout=10) as conn:
        # Use a read-only, forward-only cursor for speed.
        cursor = conn.cursor()
        cursor.execute(sql, (start_dt, end_dt))
        for row in cursor.fetchall():
            order_id = row[0]
            delivery_dt = row[1]
            client_name = row[2]
            order_type = row[3]
            status_vals = row[4:]
            day = _to_date(delivery_dt)
            # Display format requested: `ORDER_ID - ClientName`.
            suffix = str(client_name).strip() if client_name is not None else ""
            text = f"{order_id} - {suffix}" if suffix else str(order_id)

            # Color rule:
            # - all True => green
            # - all False => red
            # - otherwise => yellow
            bools = [bool(v) for v in status_vals]
            if bools and all(bools):
                color = "#2ecc71"  # green
            elif bools and (not any(bools)):
                color = "#e74c3c"  # red
            else:
                color = "#f1c40f"  # yellow

            orders_by_day.setdefault(day, []).append(OrderItem(text=text, color=color, type=order_type))

    return orders_by_day

def fetch_order_revisa_fields(
    settings: Settings,
    order_id: str,
) -> Dict[str, object] | None:
    """
    Fetch the Revisa* flags for a single order id.
    Returns None if not found.
    """
    table = _sanitize_identifier(settings.orders_table)
    order_id_col = _sanitize_identifier(settings.order_id_field)

    revisa_cols = [
        "RevisaVen",
        "RevisaCom",
        "RevisaBoto",
        "RevisaProd",
        "RevisaTecnico",
        "RevisaAlm",
        "RevisaModif",
    ]
    revisa_cols_sanitized = [_sanitize_identifier(c) for c in revisa_cols]
    select_expr = ", ".join(revisa_cols_sanitized)

    sql = f"SELECT {select_expr} FROM {table} WHERE {order_id_col} = ?"

    conn_str = (
        f"DRIVER={{{settings.db_driver}}};"
        f"SERVER={settings.db_server},{settings.db_port};"
        f"DATABASE={settings.db_name};"
        f"UID={settings.db_user};"
        f"PWD={settings.db_password};"
        f"TrustServerCertificate=yes;"
    )

    with pyodbc.connect(conn_str, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, (order_id,))
        row = cursor.fetchone()
        if row is None:
            return None

        return {col: row[idx] for idx, col in enumerate(revisa_cols_sanitized)}

