import threading
import tkinter as tk
from tkinter import messagebox
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from dashboard_app.calendar_grid import CalendarGrid
from dashboard_app.db import fetch_orders_by_date, fetch_order_revisa_fields, fetch_order_item_rows
from dashboard_app.models import OrderItem
from dashboard_app.settings import load_settings


class OrdersDashboardAppBase:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()
        self.root.title(self.settings.window_title)

        self.grid = CalendarGrid(
            root,
            week_starts_on=self.settings.week_starts_on,
            cell_style=self.settings.cell_style,
            on_order_double_click=self.on_order_double_click,
            on_refresh_now=None,
        )

        top_bar = tk.Frame(root)
        top_bar.pack(fill="x", padx=6, pady=4)

        left_controls = tk.Frame(top_bar)
        left_controls.pack(side="left")

        tk.Button(left_controls, text="Anterior", command=self.show_prev_month).pack(side="left", padx=4)

        self.range_var = tk.StringVar(value="")
        tk.Label(left_controls, textvariable=self.range_var, font=("Helvetica", 26, "bold")).pack(side="left", padx=8)

        tk.Button(left_controls, text="Siguiente", command=self.show_next_month).pack(side="left", padx=4)

        self._view_mode = "week"
        self._view_toggle_btn = tk.Button(
            left_controls,
            text="Ver mes completo",
            command=self.toggle_current_view,
        )
        self._view_toggle_btn.pack(side="left", padx=8)

        # False => filter on: show only CabPedCli.TotalServido = 0; True => show all.
        self._include_fully_served = bool(self.settings.default_include_fully_served)
        self._albaranados_btn = tk.Button(
            left_controls,
            text="Servidos: Todos" if self._include_fully_served else "Servidos: No",
            command=self.toggle_not_served,
            relief="raised" if self._include_fully_served else "sunken",
        )
        self._albaranados_btn.pack(side="left", padx=8)

        # Order type toggle group (TipPed: 1/2/3).
        type_frame = tk.Frame(left_controls, relief="groove", bd=1, padx=4, pady=2)
        type_frame.pack(side="left", padx=8)
        selected_tips = set(self.settings.default_tip_filters or ("1", "2", "3"))
        self._tip_filters = {k: (k in selected_tips) for k in ("1", "2", "3")}
        if not any(self._tip_filters.values()):
            self._tip_filters["1"] = True
        self._tip_buttons: Dict[str, tk.Button] = {}

        self._tip_buttons["1"] = tk.Button(
            type_frame,
            text="Completa",
            relief="sunken" if self._tip_filters["1"] else "raised",
            command=lambda: self.toggle_tip_filter("1"),
        )
        self._tip_buttons["1"].pack(side="left", padx=2)

        self._tip_buttons["2"] = tk.Button(
            type_frame,
            text="Maniobra",
            relief="sunken" if self._tip_filters["2"] else "raised",
            command=lambda: self.toggle_tip_filter("2"),
        )
        self._tip_buttons["2"].pack(side="left", padx=2)

        self._tip_buttons["3"] = tk.Button(
            type_frame,
            text="Botonera",
            relief="sunken" if self._tip_filters["3"] else "raised",
            command=lambda: self.toggle_tip_filter("3"),
        )
        self._tip_buttons["3"].pack(side="left", padx=2)

        sort_frame = tk.Frame(left_controls, relief="groove", bd=1, padx=4, pady=2)
        sort_frame.pack(side="left", padx=8)
        tk.Label(sort_frame, text="Ordena Por").pack(side="left", padx=(0, 4))
        self._sort_options = {
            "Semaforo": "color",
            "Tipo de Pedido": "type",
            "Numero de Pedido": "id",
            "Cliente": "client",
        }
        sort_by_to_label = {
            "color": "Semaforo",
            "type": "Tipo de Pedido",
            "id": "Numero de Pedido",
            "client": "Cliente",
        }
        self._sort_var = tk.StringVar(value=sort_by_to_label.get(self.settings.default_sort_by, "Cliente"))
        sort_menu = tk.OptionMenu(sort_frame, self._sort_var, *self._sort_options.keys(), command=self.on_sort_change)
        sort_menu.config(width=16)
        sort_menu.pack(side="left")
        self.grid.set_global_sort(self.settings.default_sort_by, ascending=True)

        right_controls = tk.Frame(top_bar)
        right_controls.pack(side="right")

        self.last_refresh_var = tk.StringVar(value="Actualizado el : --")
        tk.Label(right_controls, textvariable=self.last_refresh_var, font=("Helvetica", 10, "bold")).pack(
            side="left", padx=8
        )
        tk.Button(right_controls, text="Actualizar", command=self.refresh_now).pack(side="left", padx=4)

        self.status_var = tk.StringVar(value="Ready.")

        # Keep calendar below controls so buttons are always visible.
        self.grid.pack(fill="both", expand=True)
        # Date range is shown in top bar; hide duplicate title inside calendar body.
        self.grid.set_title_visible(False)

        self._refresh_in_progress = False
        self._next_refresh_after_id = None
        self._hourly_refresh_seconds = 900
        self._last_orders_by_day: Dict[date, List[OrderItem]] = {}

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Start with current 2-week view (weekly template).
        self.grid.set_week(date.today())
        self.range_var.set(self.grid.title_var.get())
        self.refresh_now()

    def on_close(self):
        self.root.destroy()

    def show_prev_month(self):
        # Always shift by one week, regardless of current template.
        anchor = self.grid.current_week_anchor_date - timedelta(days=7)
        if self._view_mode == "week":
            self.grid.set_week(anchor)
        else:
            self.grid.set_month(anchor)
        self.range_var.set(self.grid.title_var.get())
        self.refresh_now()

    def show_next_month(self):
        # Always shift by one week, regardless of current template.
        anchor = self.grid.current_week_anchor_date + timedelta(days=7)
        if self._view_mode == "week":
            self.grid.set_week(anchor)
        else:
            self.grid.set_month(anchor)
        self.range_var.set(self.grid.title_var.get())
        self.refresh_now()

    def toggle_current_view(self):
        if self._view_mode == "week":
            self._view_mode = "month"
            self.grid.set_month(self.grid.current_week_anchor_date)
            self._view_toggle_btn.config(text="Ver 2 semanas")
        else:
            self._view_mode = "week"
            self.grid.set_week(self.grid.current_week_anchor_date)
            self._view_toggle_btn.config(text="Ver mes completo")
        self.range_var.set(self.grid.title_var.get())
        self.refresh_now()

    def schedule_next_refresh(self):
        if self._next_refresh_after_id is not None:
            try:
                self.root.after_cancel(self._next_refresh_after_id)
            except tk.TclError:
                pass

        self._next_refresh_after_id = self.root.after(
            int(self._hourly_refresh_seconds * 1000), self.refresh_now
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
        self.status_var.set("Actualizando desde la Base de Datos...")

        start_dt, end_dt = self.grid.query_range_datetimes()

        def worker():
            try:
                orders_by_day = fetch_orders_by_date(
                    settings=self.settings,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    include_fully_served=self._include_fully_served,
                    tip_ped_values=[k for k, enabled in self._tip_filters.items() if enabled],
                )
                self.root.after(0, self.update_ui, orders_by_day)
            except Exception as e:
                self.root.after(0, self.show_error, e)
            finally:
                self._refresh_in_progress = False

        threading.Thread(target=worker, daemon=True).start()

    def update_ui(self, orders_by_day: Dict[date, List[OrderItem]]):
        self._last_orders_by_day = orders_by_day
        self.grid.render_orders(orders_by_day, max_ids_per_day=self.settings.max_ids_per_day)
        ts = datetime.now().strftime("%H:%M de %d %m %Y ")
        self.status_var.set(f"Actualizado a las : {ts}")
        self.last_refresh_var.set(f"Actualizado a las : {ts}")
        self.schedule_next_refresh()

    def show_error(self, err: Exception):
        self.status_var.set("Error while refreshing.")
        messagebox.showerror("Database error", str(err))
        self.schedule_next_refresh()

    def toggle_not_served(self):
        self._include_fully_served = not self._include_fully_served
        # Sunken + "Servidos: No" => TotalServido = 0 only; raised + "Servidos: Todos" => all.
        self._albaranados_btn.config(
            relief="raised" if self._include_fully_served else "sunken",
            text="Servidos: Todos" if self._include_fully_served else "Servidos: No",
        )
        self.refresh_now()

    def toggle_tip_filter(self, tip: str):
        # Keep at least one order type active.
        enabled_now = self._tip_filters.get(tip, False)
        if enabled_now and sum(1 for v in self._tip_filters.values() if v) == 1:
            return

        self._tip_filters[tip] = not enabled_now
        self._tip_buttons[tip].config(relief="sunken" if self._tip_filters[tip] else "raised")
        self.refresh_now()

    def on_sort_change(self, selected: str):
        key = self._sort_options.get(selected, "client")
        self.grid.set_global_sort(key, ascending=True)

    def on_order_double_click(self, order_id: str, day: date | None = None, item: OrderItem | None = None):
        order_id = (order_id or "").strip()
        if not order_id:
            return

        self.status_var.set(f"Looking up order {order_id}...")

        def worker():
            try:
                result = fetch_order_revisa_fields(self.settings, order_id=order_id)
                item_rows = fetch_order_item_rows(self.settings, order_id=order_id)
                self.root.after(0, self._show_order_details, result, item_rows, order_id, day, item)
            except Exception as e:
                self.root.after(0, self._show_order_details_error, e)

        threading.Thread(target=worker, daemon=True).start()

    def _show_order_details(
        self,
        result: Optional[Dict[str, object]],
        item_rows: List[Dict[str, object]],
        order_id: str,
        day: date | None = None,
        item: OrderItem | None = None,
    ):
        if not result:
            self.status_var.set("Ready.")
            messagebox.showwarning("Order not found", f"Order ID {order_id} not found.")
            return

        fields = [
            ("RevisaVen", "Ventas"),
            ("RevisaCom", "Comercial"),
            ("RevisaBoto", "Botoneras"),
            ("RevisaProd", "Producción"),
            ("RevisaTecnico", "Tecnico"),
            ("RevisaAlm", "Almacen"),
            ("RevisaModif", "Modificado"),
        ]

        def fmt_mark(v: object) -> str:
            if v is None:
                return "❌"
            try:
                iv = int(v)
            except Exception:
                return "✅" if bool(v) else "❌"
            return "✅" if iv == 1 else "❌"

        prod_done = int(result.get("_prod_estado2", 0) or 0)
        prod_total = int(result.get("_prod_total", 0) or 0)
        self.status_var.set("Ready.")

        # Custom details window so we can render real colored dots.
        win = tk.Toplevel(self.root)
        win.title(f"Order details - {order_id}")
        win.geometry("860x620")

        body = tk.Frame(win, padx=10, pady=10)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=f"Order: {order_id}", font=("Helvetica", 11, "bold"), anchor="w").pack(fill="x")
        

        for key, label in fields:
            tk.Label(body, text=f"{label}: {fmt_mark(result.get(key))}", anchor="w").pack(fill="x")

        if day is not None and item is not None and item.client_name:
            day_items = self._last_orders_by_day.get(day, [])
            client_norm = item.client_name.strip().lower()
            total_client_orders_day = sum(
                1 for it in day_items if (it.client_name or "").strip().lower() == client_norm
            )
            tk.Label(body, text="", anchor="w").pack(fill="x")
            tk.Label(body, text=f"Client: {item.client_name}", anchor="w").pack(fill="x")
            tk.Label(body, text=f"Date: {day.strftime('%Y-%m-%d')}", anchor="w").pack(fill="x")
            tk.Label(
                body,
                text=f"Total client orders for the day: {total_client_orders_day}",
                anchor="w",
            ).pack(fill="x")

        # tk.Label(body, text="", anchor="w").pack(fill="x")
        # tk.Label(body, text="Lineas:", font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(
            body,
            text=f"Ordenes de producción: {prod_done}/{prod_total}",
            anchor="w",
        ).pack(fill="x", pady=(2, 8))
        
        list_wrap = tk.Frame(body)
        list_wrap.pack(fill="both", expand=True, pady=(4, 0))

        list_canvas = tk.Canvas(list_wrap, highlightthickness=0)
        list_scroll = tk.Scrollbar(list_wrap, orient="vertical", command=list_canvas.yview)
        list_canvas.configure(yscrollcommand=list_scroll.set)

        list_canvas.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")

        list_frame = tk.Frame(list_canvas)
        list_window_id = list_canvas.create_window((0, 0), window=list_frame, anchor="nw")

        def _on_list_frame_configure(_event):
            bbox = list_canvas.bbox("all")
            if bbox is not None:
                list_canvas.configure(scrollregion=bbox)

        def _on_list_canvas_configure(event):
            list_canvas.itemconfigure(list_window_id, width=event.width)

        list_frame.bind("<Configure>", _on_list_frame_configure)
        list_canvas.bind("<Configure>", _on_list_canvas_configure)

        def estado_color(v: object) -> str:
            s = "" if v is None else str(v).strip()
            if s == "0":
                return "#2ecc71"  # green
            if s == "1":
                return "#f1c40f"  # yellow
            if s == "2":
                return "#e74c3c"  # red
            return "#b0b0b0"

        for r in item_rows:
            row = tk.Frame(list_frame)
            row.pack(fill="x", anchor="w", pady=1)

            dot = tk.Canvas(row, width=12, height=12, highlightthickness=0)
            dot.pack(side="left", padx=(0, 6))
            dot.create_oval(2, 2, 10, 10, fill=estado_color(r.get("Estado")), outline="")

            codart = "" if r.get("CodArt") is None else str(r.get("CodArt")).strip()
            desart = "" if r.get("DesArt") is None else str(r.get("DesArt"))
            tk.Label(row, text=f"Referencia: {codart}, Descripción: {desart}", anchor="w").pack(side="left", fill="x", expand=True)

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

