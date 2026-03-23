import os
import threading
import tkinter as tk
from tkinter import messagebox
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from dashboard_app.db import fetch_orders_by_date, fetch_order_revisa_fields
from dashboard_app.settings import load_settings
from dashboard_app.calendar_grid import CalendarGrid
from dashboard_app.models import OrderItem


class OrdersDashboardApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Orders Delivery Dashboard")

        self.settings = load_settings()
        self.grid = CalendarGrid(
            root,
            week_starts_on=self.settings.week_starts_on,
            cell_style=self.settings.cell_style,
        )

        top_bar = tk.Frame(root)
        top_bar.pack(fill="x")

        self.status_var = tk.StringVar(value="Ready.")
        status_label = tk.Label(top_bar, textvariable=self.status_var, anchor="w")
        status_label.pack(side="left", padx=8, pady=6)

        refresh_btn = tk.Button(top_bar, text="Refresh now", command=self.refresh_now)
        refresh_btn.pack(side="right", padx=8)

        controls = tk.Frame(root)
        controls.pack(fill="x")

        self._view_mode = "month"  # "month" or "week"
        self._anchor_date: date = date.today().replace(day=1)  # month-first-day when in month mode

        prev_btn = tk.Button(controls, text="<", command=lambda: self.shift_view(-1))
        prev_btn.pack(side="left", padx=8, pady=4)
        next_btn = tk.Button(controls, text=">", command=lambda: self.shift_view(1))
        next_btn.pack(side="right", padx=8, pady=4)

        self.toggle_view_btn = tk.Button(controls, text="Week view", command=self.toggle_view_mode)
        self.toggle_view_btn.pack(side="left", padx=8, pady=4)

        paned = tk.PanedWindow(root, orient="vertical", sashrelief="raised", sashwidth=4)
        paned.pack(fill="both", expand=True)
        paned.add(self.grid, stretch="always")

        order_panel = self._build_order_panel(paned)
        paned.add(order_panel)

        self._display_lock = threading.Lock()
        self._refresh_in_progress = False
        self._next_refresh_after_id = None

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.grid.set_month(self._anchor_date)
        self.refresh_now()

    def on_close(self):
        # Nothing special; Tk will exit.
        self.root.destroy()

    def toggle_view_mode(self):
        if self._view_mode == "month":
            self._view_mode = "week"
            # Keep anchor inside the week (use first day of the currently displayed month).
            self.grid.set_week(self._anchor_date)
            self.toggle_view_btn.config(text="Month view")
        else:
            self._view_mode = "month"
            self._anchor_date = date(self._anchor_date.year, self._anchor_date.month, 1)
            self.grid.set_month(self._anchor_date)
            self.toggle_view_btn.config(text="Week view")
        self.refresh_now()

    def shift_view(self, delta: int):
        """
        Move the visible window:
        - month mode: +/- 1 month
        - week mode: +/- 1 week
        """
        if self._view_mode == "month":
            y, m = self._anchor_date.year, self._anchor_date.month
            if delta == -1:
                if m == 1:
                    y -= 1
                    m = 12
                else:
                    m -= 1
            else:
                if m == 12:
                    y += 1
                    m = 1
                else:
                    m += 1
            self._anchor_date = date(y, m, 1)
            self.grid.set_month(self._anchor_date)
        else:
            self._anchor_date = self._anchor_date + timedelta(days=7 * delta)
            self.grid.set_week(self._anchor_date)
        self.refresh_now()

    def _build_order_panel(self, parent: tk.Widget) -> tk.Frame:
        panel = tk.Frame(parent)
        panel.configure(padx=10, pady=8)

        title = tk.Label(panel, text="Order lookup (Revisa fields)", font=("Segoe UI", 12, "bold"))
        title.pack(anchor="w")

        input_row = tk.Frame(panel)
        input_row.pack(fill="x", pady=(6, 6))

        tk.Label(input_row, text="Order ID:", width=10, anchor="w").pack(side="left")
        self.order_id_entry = tk.Entry(input_row)
        self.order_id_entry.pack(side="left", fill="x", expand=True)

        lookup_btn = tk.Button(input_row, text="Lookup", command=self.lookup_order)
        lookup_btn.pack(side="left", padx=(6, 0))

        fields = [
            "RevisaVen",
            "RevisaCom",
            "RevisaBoto",
            "RevisaProd",
            "RevisaTecnico",
            "RevisaAlm",
            "RevisaModif",
        ]
        self.order_field_vars: Dict[str, tk.StringVar] = {f: tk.StringVar(value="") for f in fields}

        grid = tk.Frame(panel)
        grid.pack(fill="x", pady=(8, 0))
        for i, f in enumerate(fields):
            tk.Label(grid, text=f + ":", width=16, anchor="w").grid(row=i, column=0, sticky="w", pady=2)
            tk.Label(grid, textvariable=self.order_field_vars[f]).grid(row=i, column=1, sticky="w", pady=2)

        self.order_status_var = tk.StringVar(value="")
        status_lbl = tk.Label(panel, textvariable=self.order_status_var, fg="#666666")
        status_lbl.pack(anchor="w", pady=(8, 0))
        return panel

    def lookup_order(self):
        order_id = self.order_id_entry.get().strip()
        if not order_id:
            messagebox.showwarning("Missing input", "Please enter an Order ID.")
            return

        self.order_status_var.set("Looking up...")
        self.status_var.set("Looking up order...")

        def worker():
            try:
                result = fetch_order_revisa_fields(self.settings, order_id=order_id)
                self.root.after(0, self._show_order_lookup_result, result)
            except Exception as e:
                self.root.after(0, self._show_order_lookup_error, e)

        threading.Thread(target=worker, daemon=True).start()

    def _show_order_lookup_result(self, result: Optional[Dict[str, object]]):
        if not result:
            self.order_status_var.set("Not found.")
            for v in self.order_field_vars.values():
                v.set("")
            self.status_var.set("Ready.")
            return

        def fmt(val: object) -> str:
            if val is None:
                return "NULL"
            return "True" if bool(val) else "False"

        for field, var in self.order_field_vars.items():
            var.set(fmt(result.get(field)))

        self.order_status_var.set("OK")
        self.status_var.set("Ready.")

    def _show_order_lookup_error(self, err: Exception):
        self.order_status_var.set("Error.")
        self.status_var.set("Error while looking up order.")
        messagebox.showerror("Database error", str(err))

    def schedule_next_refresh(self):
        # Refresh hourly in the background; UI updates happen on the main thread.
        if self._next_refresh_after_id is not None:
            try:
                self.root.after_cancel(self._next_refresh_after_id)
            except tk.TclError:
                pass
        self._next_refresh_after_id = self.root.after(
            int(self.settings.refresh_interval_seconds * 1000), self.refresh_now
        )

    def refresh_now(self):
        if self._refresh_in_progress:
            return
        if self._next_refresh_after_id is not None:
            try:
                self.root.after_cancel(self._next_refresh_after_id)
            except tk.TclError:
                pass
            self._next_refresh_after_id = None

        self._refresh_in_progress = True
        self.status_var.set("Refreshing from database...")

        # Determine the calendar date window we need to query.
        start_dt, end_dt = self.grid.query_range_datetimes()

        def worker():
            try:
                orders_by_day = fetch_orders_by_date(
                    settings=self.settings,
                    start_dt=start_dt,
                    end_dt=end_dt,
                )
                self.root.after(0, self.update_ui, orders_by_day)
            except Exception as e:
                self.root.after(0, self.show_error, e)
            finally:
                self._refresh_in_progress = False

        threading.Thread(target=worker, daemon=True).start()

    def update_ui(self, orders_by_day: Dict[date, List[OrderItem]]):
        self.grid.render_orders(orders_by_day, max_ids_per_day=self.settings.max_ids_per_day)
        self.status_var.set(f"Last refresh: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.schedule_next_refresh()

    def show_error(self, err: Exception):
        self.status_var.set("Error while refreshing.")
        messagebox.showerror("Database error", str(err))
        self.schedule_next_refresh()


def main():
    root = tk.Tk()
    # Reasonable default size for 7 columns x 6 rows.
    root.geometry("1050x780")
    OrdersDashboardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

