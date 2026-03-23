import json
import os
from dataclasses import dataclass
from typing import Optional, Tuple


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
    return val


def load_settings(config_path: Optional[str] = None) -> Settings:
    """
    Loads non-sensitive settings from `config.json` and reads the DB password from `DB_PASSWORD`.
    """
    if config_path is None:
        # Load config relative to the repo root (parent of `dashboard_app/`), not CWD.
        # This prevents confusing errors when running `python -m ...` from another directory.
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(repo_root, "config.json")

    if not os.path.exists(config_path):
        raise RuntimeError(
            f"Missing config file: {config_path}\n"
            "Create it based on `config.example.json` (and set DB_PASSWORD in your environment)."
        )

    try:
        # Use utf-8-sig to tolerate UTF-8 BOM, which commonly breaks json.load()
        # with "Expecting value: line 1 column 1".
        with open(config_path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        # Don't print the file content (could include secrets). Provide a helpful pointer.
        raise RuntimeError(f"Invalid JSON in config file: {config_path}\n{e}") from e

    db_password = _require_env("DB_PASSWORD")

    return Settings(
        db_server=raw["db_server"],
        db_port=int(raw["db_port"]),
        db_name=raw["db_name"],
        db_user=raw["db_user"],
        db_password=db_password,
        db_driver=raw.get("db_driver", "ODBC Driver 17 for SQL Server"),
        orders_table=raw["orders_table"],
        order_id_field=raw["order_id_field"],
        delivery_date_field=raw["delivery_date_field"],
        refresh_interval_seconds=int(raw.get("refresh_interval_seconds", 3600)),
        max_ids_per_day=int(raw.get("max_ids_per_day", 50)),
        week_starts_on=raw.get("week_starts_on", "mon"),
        cell_style=raw.get("cell_style", "light"),
    )

