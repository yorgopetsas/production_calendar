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


def _odbc_escape(value: str) -> str:
    """
    Escape ODBC connection-string values.
    Braced values allow special chars like ';' and spaces.
    """
    s = str(value).replace("}", "}}")
    return "{" + s + "}"


def _candidate_drivers(preferred: str) -> List[str]:
    # Try preferred first, then common SQL Server ODBC drivers.
    candidates = [preferred, "ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]
    # Preserve order while removing duplicates.
    out: List[str] = []
    seen = set()
    for d in candidates:
        if d and d not in seen:
            out.append(d)
            seen.add(d)
    return out


def _connect_sql(settings: Settings, timeout: int = 10):
    installed = set(pyodbc.drivers())
    tried: List[str] = []
    for drv in _candidate_drivers(settings.db_driver):
        if drv not in installed:
            continue
        tried.append(drv)
        conn_str = (
            f"DRIVER={_odbc_escape(drv)};"
            f"SERVER={settings.db_server},{settings.db_port};"
            f"DATABASE={_odbc_escape(settings.db_name)};"
            f"UID={_odbc_escape(settings.db_user)};"
            f"PWD={_odbc_escape(settings.db_password)};"
            f"TrustServerCertificate=yes;"
        )
        try:
            return pyodbc.connect(conn_str, timeout=timeout)
        except pyodbc.Error:
            # Try next candidate driver.
            continue

    available = ", ".join(sorted(installed)) if installed else "(none)"
    raise RuntimeError(
        "Unable to connect with available SQL Server ODBC drivers. "
        f"Tried: {tried or _candidate_drivers(settings.db_driver)}. "
        f"Installed drivers: {available}."
    )


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
    include_fully_served: bool = False,
    tip_ped_values: List[str] | None = None,
) -> Dict[date, List[OrderItem]]:
    """
    Fetch orders whose delivery date overlaps the given [start_dt, end_dt) window.
    Returns: {date -> [order_id_str, ...]}

    include_fully_served: when False, restrict to CabPedCli rows with TotalServido = 0
    ("Servidos: No"). When True, no TotalServido restriction ("Servidos: Todos").
    """
    table = _sanitize_identifier(settings.orders_table)
    order_id_col = _sanitize_identifier(settings.order_id_field)
    delivery_date_col = _sanitize_identifier(settings.delivery_date_field)
    client_name_col = _sanitize_identifier("NomCli")
    order_type_col = _sanitize_identifier("TipPed")
    cod_eje_col = _sanitize_identifier("CodEje")
    status_cols = [
        _sanitize_identifier("RevisaVen"),
        _sanitize_identifier("RevisaCom"),
        _sanitize_identifier("RevisaBoto"),
        _sanitize_identifier("RevisaProd"),
        _sanitize_identifier("RevisaTecnico"),
        _sanitize_identifier("RevisaAlm"),
        _sanitize_identifier("RevisaModif"),
    ]
    status_expr = ", ".join(status_cols)
    prod_table = _sanitize_identifier("dbo.OrdProdCab")
    total_servido_col = _sanitize_identifier("TotalServido")

    # Step 1: fetch calendar orders from CabPedCli.
    delivery_expr = f"TRY_CONVERT(datetime, {delivery_date_col})"
    # Keep FecSer (delivery date) as the primary window, but allow CodEje from
    # the visible years and their previous years so we include orders created
    # last year with delivery date in the current year.
    visible_years = {start_dt.year, (end_dt - datetime.resolution).year}
    cod_eje_years = sorted(visible_years | {y - 1 for y in visible_years})
    years_where = f"{cod_eje_col} IN ({','.join('?' for _ in cod_eje_years)})"
    years_params = cod_eje_years

    if not tip_ped_values:
        tip_ped_values = ["1", "2", "3"]
    else:
        # Previous behavior (kept commented): always include TipPed=4 as well.
        # tip_ped_values = list(dict.fromkeys([*tip_ped_values, "4"]))
        tip_ped_values = list(dict.fromkeys(tip_ped_values))
    tip_placeholders = ",".join("?" for _ in tip_ped_values)

    # When include_fully_served is False, only orders with TotalServido = 0 (CabPedCli).
    # When True, do not restrict by TotalServido ("Servidos: Todos" in the UI).
    servidos_where = ""
    if not include_fully_served:
        servidos_where = f"  AND ISNULL({total_servido_col}, 0) = 0\n"

    sql_orders = (
        f"SELECT {order_id_col}, {delivery_expr}, {client_name_col}, {order_type_col}, {status_expr} "
        f"FROM {table} "
        f"WHERE {delivery_expr} >= ? AND {delivery_expr} < ? "
        f"  AND LTRIM(RTRIM(CAST(CodSer AS varchar(20)))) = 'B' "
        f"  AND LTRIM(RTRIM(CAST(TipPed AS varchar(20)))) IN ({tip_placeholders}) "
        f"  AND {years_where} "
        f"{servidos_where}"
        f"ORDER BY {delivery_expr}, {client_name_col}, {order_id_col}"
    )

    orders_by_day: Dict[date, List[OrderItem]] = {}
    with _connect_sql(settings, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute(sql_orders, [start_dt, end_dt, *tip_ped_values, *years_params])
        order_rows = cursor.fetchall()
        if not order_rows:
            return orders_by_day

        # Previous "No Albaranados" / line-based filter (ComPedCli): kept commented for reference.
        # fully_served_order_ids: set[int] = set()
        # if not include_fully_served:
        #     comped_table = _sanitize_identifier("dbo.ComPedCli")
        #     order_ids_for_comped: List[int] = []
        #     for r in order_rows:
        #         try:
        #             order_ids_for_comped.append(int(r[0]))
        #         except Exception:
        #             continue
        #     order_ids_for_comped = sorted(set(order_ids_for_comped))
        #     if order_ids_for_comped:
        #         placeholders = ",".join("?" for _ in order_ids_for_comped)
        #         sql_comped = (
        #             f"SELECT CodPed, "
        #             f"       COUNT(*) AS total_lines, "
        #             f"       SUM(CASE WHEN (ISNULL(Cantidad,0) - ISNULL(Servidos,0)) > 0 THEN 1 ELSE 0 END) AS pending_lines "
        #             f"FROM {comped_table} "
        #             f"WHERE CodPed IN ({placeholders}) "
        #             f"  AND LTRIM(RTRIM(CAST(CodSer AS varchar(20)))) = 'B' "
        #             f"GROUP BY CodPed"
        #         )
        #         cursor.execute(sql_comped, order_ids_for_comped)
        #         for cr in cursor.fetchall():
        #             try:
        #                 cod_ped = int(cr[0])
        #                 total_lines = int(cr[1] or 0)
        #                 pending_lines = int(cr[2] or 0)
        #             except Exception:
        #                 continue
        #             if total_lines > 0 and pending_lines == 0:
        #                 fully_served_order_ids.add(cod_ped)

        # Step 2: fetch production counts from OrdProdCab for ALL listed orders.
        order_ids_numeric: List[int] = []
        for r in order_rows:
            try:
                order_ids_numeric.append(int(r[0]))
            except Exception:
                continue
        order_ids_numeric = sorted(set(order_ids_numeric))

        prod_counts: Dict[int, tuple[int, int, int]] = {}
        if order_ids_numeric:
            placeholders = ",".join("?" for _ in order_ids_numeric)
            sql_prod = (
                f"SELECT p.CodPed, COUNT(*) AS total_prod, "
                f"       SUM(CASE WHEN TRY_CONVERT(int, p.Estado) = 0 THEN 1 ELSE 0 END) AS estado_0_count, "
                f"       SUM(CASE WHEN TRY_CONVERT(int, p.Estado) = 2 THEN 1 ELSE 0 END) AS estado_2_count "
                f"FROM {prod_table} p "
                f"WHERE p.CodPed IN ({placeholders}) "
                f"GROUP BY p.CodPed"
            )
            cursor.execute(sql_prod, order_ids_numeric)
            for pr in cursor.fetchall():
                cod_ped = int(pr[0])
                prod_counts[cod_ped] = (int(pr[1] or 0), int(pr[2] or 0), int(pr[3] or 0))

        for row in order_rows:
            order_id = row[0]
            try:
                oid_check = int(order_id)
            except Exception:
                oid_check = None
            # Previous exclusion when ComPedCli indicated fully served (see commented block above).
            # if (not include_fully_served) and oid_check is not None and oid_check in fully_served_order_ids:
            #     continue

            delivery_dt = row[1]
            client_name = row[2]
            order_type = row[3]
            status_vals = row[4:10]
            revisa_modif_val = row[10]
            day = _to_date(delivery_dt)
            # Display format requested: `ORDER_ID - ClientName`.
            suffix = str(client_name).strip() if client_name is not None else ""
            text = f"{order_id} - {suffix}" if suffix else str(order_id)

            order_type_raw = str(order_type).strip() if order_type is not None else ""
            if order_type_raw.startswith("1"):
                order_type_tag = "COM"
            elif order_type_raw.startswith("2"):
                order_type_tag = "MAN"
            elif order_type_raw.startswith("3"):
                order_type_tag = "BOT"
            else:
                order_type_tag = order_type_raw

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

            # Build summary letters for selected Revisa fields:
            # Ventas/Comercial/Botoneras/Produccion/Almacen => V/C/B/P/A
            # Fixed-width 5-slot pattern so company names align in UI.
            # Order: Ventas/Comercial/Botoneras/Produccion/Almacen => V/C/B/P/A
            v = "V" if len(bools) >= 1 and bools[0] else "-"
            c = "C" if len(bools) >= 2 and bools[1] else "-"
            b = "B" if len(bools) >= 3 and bools[2] else "-"
            p = "P" if len(bools) >= 4 and bools[3] else "-"
            a = "A" if len(bools) >= 6 and bools[5] else "-"
            revisa_letters = f"{v}/{c}/{b}/{p}/{a}"

            # Production-order color (second light), from OrdProdCab by CodPed.
            # - if all related production orders are Estado=0 -> green
            # - if all related production orders are Estado=2 -> red
            # - otherwise -> yellow
            # If there are no production orders, no second light is shown.
            prod_color = None
            try:
                oid_num = int(order_id)
            except Exception:
                oid_num = None
            total_prod, estado_0_count, estado_2_count = (0, 0, 0)
            if oid_num is not None:
                total_prod, estado_0_count, estado_2_count = prod_counts.get(oid_num, (0, 0, 0))
            if total_prod > 0:
                if estado_0_count == total_prod:
                    prod_color = "#2ecc71"
                elif estado_2_count == total_prod:
                    prod_color = "#e74c3c"
                else:
                    prod_color = "#f1c40f"
            # Keep orders without production rows visible; they render without dot.

            revisa_modif = False
            try:
                revisa_modif = int(revisa_modif_val or 0) == 1
            except Exception:
                revisa_modif = bool(revisa_modif_val)

            orders_by_day.setdefault(day, []).append(
                OrderItem(
                    text=text,
                    color=color,
                    type=order_type_tag,
                    prod_color=prod_color,
                    client_name=suffix,
                    revisa_letters=revisa_letters,
                    revisa_modif=revisa_modif,
                )
            )

    # Final per-day ordering: group by client name, then by display text.
    for day, items in orders_by_day.items():
        items.sort(key=lambda x: ((x.client_name or "").lower(), x.text.lower()))

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

    prod_table = _sanitize_identifier("dbo.OrdProdCab")
    # Production-order counts must be based on the clicked order id parameter.
    sql = (
        f"SELECT {select_expr}, "
        f"       (SELECT COUNT(*) FROM {prod_table} p WHERE p.CodPed = TRY_CONVERT(numeric(18,0), ?)) AS prod_total, "
        f"       (SELECT COUNT(*) FROM {prod_table} p WHERE p.CodPed = TRY_CONVERT(numeric(18,0), ?) AND LTRIM(RTRIM(CAST(p.Estado AS varchar(50)))) = '2') AS prod_estado2 "
        f"FROM {table} WHERE {order_id_col} = ?"
    )

    with _connect_sql(settings, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, (order_id, order_id, order_id))
        row = cursor.fetchone()
        if row is None:
            return None

        out = {col: row[idx] for idx, col in enumerate(revisa_cols_sanitized)}
        out["_prod_total"] = row[len(revisa_cols_sanitized)] or 0
        out["_prod_estado2"] = row[len(revisa_cols_sanitized) + 1] or 0
        return out


def fetch_order_item_rows(
    settings: Settings,
    order_id: str,
) -> List[Dict[str, object]]:
    """
    Fetch row-level data for an order, including product description.
    Source requested by user: CabPedCli by CodPed, then Articulos by CodArt.
    Implemented as one LEFT JOIN for efficiency.
    """
    cab_table = _sanitize_identifier(settings.orders_table)  # usually dbo.CabPedCli
    art_table = _sanitize_identifier("dbo.Articulos")
    order_id_col = _sanitize_identifier(settings.order_id_field)  # usually CodPed
    codart_col = _sanitize_identifier("CodArt")
    obs_col = _sanitize_identifier("Obs")
    estado_col = _sanitize_identifier("Estado")
    desart_col = _sanitize_identifier("DesArt")

    # As requested:
    # - row list comes from OrdProdCab (filtered by CodPed)
    # - product name (DesArt) comes from Articulos by CodArt
    prod_table = _sanitize_identifier("dbo.OrdProdCab")
    sql = (
        f"SELECT p.{codart_col}, p.{obs_col}, p.{estado_col}, a.{desart_col} "
        f"FROM {prod_table} p "
        f"LEFT JOIN {art_table} a ON a.{codart_col} = p.{codart_col} "
        f"WHERE p.{order_id_col} = TRY_CONVERT(numeric(18,0), ?) "
        f"ORDER BY p.{codart_col}"
    )

    rows: List[Dict[str, object]] = []
    with _connect_sql(settings, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, (order_id,))
        for r in cursor.fetchall():
            rows.append(
                {
                    "CodArt": r[0],
                    "Obs": r[1],
                    "Estado": r[2],
                    "DesArt": r[3],
                }
            )
    return rows

