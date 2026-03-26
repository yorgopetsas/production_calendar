import json
import os
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

from dashboard_app.secret_store import get_embedded_db_password

EMBEDDED_CONFIG = {
    "db_server": "192.168.1.1",
    "db_port": 1433,
    "db_name": "DB_NAME",
    "db_user": "DB_USER",
    "db_driver": "ODBC Driver 17 for SQL Server",
    "orders_table": "dbo.CabPedCli",
    "order_id_field": "CodPed",
    "delivery_date_field": "FecSer",
    "refresh_interval_seconds": 3600,
    "max_ids_per_day": 50,
    "week_starts_on": "mon",
    "cell_style": "light",
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

    db_password = _resolve_db_password()

    return Settings(
        db_server=str(raw["db_server"]).strip(),
        db_port=int(raw["db_port"]),
        db_name=str(raw["db_name"]).strip(),
        db_user=str(raw["db_user"]).strip(),
        db_password=db_password,
        db_driver=str(raw.get("db_driver", "ODBC Driver 17 for SQL Server")).strip(),
        orders_table=str(raw["orders_table"]).strip(),
        order_id_field=str(raw["order_id_field"]).strip(),
        delivery_date_field=str(raw["delivery_date_field"]).strip(),
        refresh_interval_seconds=int(raw.get("refresh_interval_seconds", 3600)),
        max_ids_per_day=int(raw.get("max_ids_per_day", 50)),
        week_starts_on=str(raw.get("week_starts_on", "mon")).strip(),
        cell_style=str(raw.get("cell_style", "light")).strip(),
    )

