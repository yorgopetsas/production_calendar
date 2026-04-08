import json
import os
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

from dashboard_app.secret_store import get_embedded_db_password

EMBEDDED_CONFIG = {
    "db_server": "192.168.1.226",
    "db_port": 1433,
    "db_name": "GESTICOM",
    "db_user": "gesticom",
    "db_driver": "ODBC Driver 17 for SQL Server",
    "orders_table": "dbo.CabPedCli",
    "order_id_field": "CodPed",
    "delivery_date_field": "FecSer",
    "window_title": "Calendario de Fabricacion",
    "default_sort_by": "client",
    "default_include_fully_served": False,
    "default_tip_filters": ["1", "2", "3"],
    "refresh_interval_seconds": 3600,
    "max_ids_per_day": 50,
    "week_starts_on": "mon",
    "cell_style": "light",
    "profiles": {
        "comercial": {
            "window_title": "Calendario Comercial",
            "delivery_date_field": "FecSer",
            "exe_name": "CalendarioComercial",
            "default_sort_by": "client",
            "default_include_fully_served": False,
            "default_tip_filters": ["1", "2", "3"],
        },
        "produccion": {
            "window_title": "Calendario de Fabricacion",
            "delivery_date_field": "FecSer",
            "exe_name": "CalendarioProduccion",
            "default_sort_by": "client",
            "default_include_fully_served": False,
            "default_tip_filters": ["1", "2", "3"],
        },
    },
}

@dataclass(frozen=True)
class Settings:
    db_server: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_driver: str

    orders_table: str
    order_id_field: str
    delivery_date_field: str
    window_title: str
    exe_name: str
    profile_name: str
    default_sort_by: str
    default_include_fully_served: bool
    default_tip_filters: Tuple[str, ...]

    refresh_interval_seconds: int
    max_ids_per_day: int

    week_starts_on: str
    cell_style: str


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing environment variable: {name}")
    # Avoid accidental trailing spaces/newlines when copied from terminal or setx.
    return val.strip()


def _resolve_db_password() -> str:
    # Prefer environment variable for local development/override.
    env_val = os.environ.get("DB_PASSWORD")
    if env_val and env_val.strip():
        return env_val.strip()

    embedded = get_embedded_db_password()
    if embedded:
        return embedded

    raise RuntimeError(
        "Missing DB password. Set DB_PASSWORD or configure embedded secret in dashboard_app/secret_store.py."
    )


def load_settings(config_path: Optional[str] = None) -> Settings:
    """
    Loads non-sensitive settings from `config.json` and reads the DB password from `DB_PASSWORD`.
    """
    if config_path is None:
        # In PyInstaller/frozen mode, read config next to the executable.
        # In source mode, read config from repo root (parent of dashboard_app/).
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            config_path = os.path.join(exe_dir, "config.json")
        else:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(repo_root, "config.json")

    if os.path.exists(config_path):
        try:
            # Use utf-8-sig to tolerate UTF-8 BOM, which commonly breaks json.load()
            # with "Expecting value: line 1 column 1".
            with open(config_path, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            # Don't print the file content (could include secrets). Provide a helpful pointer.
            raise RuntimeError(f"Invalid JSON in config file: {config_path}\n{e}") from e
    else:
        # One-file EXE mode: fallback to embedded defaults.
        raw = EMBEDDED_CONFIG

    profile_name = (os.environ.get("DASHBOARD_PROFILE", "") or "").strip().lower() or "produccion"
    profiles = raw.get("profiles") if isinstance(raw, dict) else None
    selected_profile = {}
    if isinstance(profiles, dict) and profile_name in profiles and isinstance(profiles[profile_name], dict):
        selected_profile = profiles[profile_name]
    merged = dict(raw)
    merged.pop("profiles", None)
    merged.update(selected_profile)

    db_password = _resolve_db_password()

    return Settings(
        db_server=str(merged["db_server"]).strip(),
        db_port=int(merged["db_port"]),
        db_name=str(merged["db_name"]).strip(),
        db_user=str(merged["db_user"]).strip(),
        db_password=db_password,
        db_driver=str(merged.get("db_driver", "ODBC Driver 17 for SQL Server")).strip(),
        orders_table=str(merged["orders_table"]).strip(),
        order_id_field=str(merged["order_id_field"]).strip(),
        delivery_date_field=str(merged["delivery_date_field"]).strip(),
        window_title=str(merged.get("window_title", "Calendario de Fabricacion")).strip(),
        exe_name=str(merged.get("exe_name", "CalendarioDeFabricacion")).strip(),
        profile_name=profile_name,
        default_sort_by=str(merged.get("default_sort_by", "client")).strip().lower(),
        default_include_fully_served=bool(merged.get("default_include_fully_served", False)),
        default_tip_filters=tuple(str(v).strip() for v in merged.get("default_tip_filters", ["1", "2", "3"])),
        refresh_interval_seconds=int(merged.get("refresh_interval_seconds", 3600)),
        max_ids_per_day=int(merged.get("max_ids_per_day", 50)),
        week_starts_on=str(merged.get("week_starts_on", "mon")).strip(),
        cell_style=str(merged.get("cell_style", "light")).strip(),
    )

