# Orders Delivery Dashboard (Python, desktop)

This is a minimal Windows desktop app that connects to a SQL Server database and shows a calendar month grid.
Each day cell lists `OrderID`s whose `DeliveryDate` falls on that date.

It refreshes automatically once per hour (and you can also click `Refresh now`).

## 1) Install prerequisites

1. Install Python 3.10+.
2. Install the SQL Server ODBC driver: **ODBC Driver 17 for SQL Server** (Microsoft).
3. Install dependencies:
   - `pip install -r requirements.txt`

## 2) Configure database connection

1. Copy `config.example.json` to `config.json`.
2. Edit `config.json`:
   - `db_name`
   - `orders_table`
   - `order_id_field`
   - `delivery_date_field`

3. Set the DB password as an environment variable (do not put it in git/code):
   - PowerShell:
     - `$env:DB_PASSWORD="YOUR_PASSWORD"`

## 3) Run

From the workspace root (`dashboard`):

```powershell
python -m dashboard_app
```

## 4) Build Windows EXE

1. Ensure `dashboard_app/secret_store.py` has your generated encrypted values.
2. Build:

```powershell
.\build_exe.ps1
```

3. Deliver the following to office PCs:
   - `dist\DashboardPedidos.exe`
   - `dist\config.json`

4. On target PCs, install:
   - Microsoft ODBC Driver 17 for SQL Server
   - Microsoft Visual C++ Redistributable (if missing)
