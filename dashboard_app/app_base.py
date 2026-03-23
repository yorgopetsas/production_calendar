import threading
import tkinter as tk
from tkinter import messagebox
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from dashboard_app.calendar_grid import CalendarGrid
from dashboard_app.db import fetch_orders_by_date, fetch_order_revisa_fields
from dashboard_app.models import OrderItem
from dashboard_app.settings import load_settings


class OrdersDashboardAppBase:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Pedidos Pendientes de Entrega")

        self.settings = load_settings()

        self.grid = CalendarGrid(
            root,
            week_starts_on=self.settings.week_starts_on,
            cell_style=self.settings.cell_style,
            on_order_double_click=self.on_order_double_click,
        )
        self.grid.pack(fill="both", expand=True)

        top_bar = tk.Frame(root)
        top_bar.pack(fill="x")

        self.status_var = tk.StringVar(value="Ready.")
        tk.Label(top_bar, textvariable=self.status_var, anchor="w").pack(side="left", padx=8, pady=6)

        tk.Button(top_bar, text="Refresh now", command=self.refresh_now).pack(side="right", padx=8)

        # Month navigation controls (base behavior).
        month_controls = tk.Frame(root)
        month_controls.pack(fill="x")

        tk.Button(month_controls, text="<", command=self.show_prev_month).pack(side="left", padx=8, pady=4)
        tk.Button(month_controls, text=">", command=self.show_next_month).pack(side="right", padx=8, pady=4)

        self._refresh_in_progress = False
        self._next_refresh_after_id = None

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Start with current month.
        self.grid.set_month(date.today().replace(day=1))
        self.refresh_now()

    def on_close(self):
        self.root.destroy()

    def show_prev_month(self):
        y, m = self.grid.current_month_first_day.year, self.grid.current_month_first_day.month
        if m == 1:
            y -= 1
            m = 12
        else:
            m -= 1
        self.grid.set_month(date(y, m, 1))
        self.refresh_now()

    def show_next_month(self):
        y, m = self.grid.current_month_first_day.year, self.grid.current_month_first_day.month
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
        self.grid.set_month(date(y, m, 1))
        self.refresh_now()

    def schedule_next_refresh(self):
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

    def on_order_double_click(self, order_id: str):
        order_id = (order_id or "").strip()
        if not order_id:
            return

        self.status_var.set(f"Looking up order {order_id}...")

        def worker():
            try:
                result = fetch_order_revisa_fields(self.settings, order_id=order_id)
                self.root.after(0, self._show_order_details, result, order_id)
            except Exception as e:
                self.root.after(0, self._show_order_details_error, e)

        threading.Thread(target=worker, daemon=True).start()

    def _show_order_details(self, result: Optional[Dict[str, object]], order_id: str):
        if not result:
            self.status_var.set("Ready.")
            messagebox.showwarning("Order not found", f"Order ID {order_id} not found.")
            return

        fields = [
            "RevisaVen",
            "RevisaCom",
            "RevisaBoto",
            "RevisaProd",
            "RevisaTecnico",
            "RevisaAlm",
            "RevisaModif",
        ]

        def fmt(v: object) -> str:
            if v is None:
                return "NULL"
            return "True" if bool(v) else "False"

        lines = [f"Order: {order_id}"]
        for f in fields:
            lines.append(f"{f}: {fmt(result.get(f))}")

        self.status_var.set("Ready.")
        messagebox.showinfo("Order details", "\n".join(lines))

    def _show_order_details_error(self, err: Exception):
        self.status_var.set("Ready.")
        messagebox.showerror("Database error", str(err))


def main():
    root = tk.Tk()
    root.geometry("1050x780")
    OrdersDashboardAppBase(root)
    root.mainloop()


if __name__ == "__main__":
    main()

