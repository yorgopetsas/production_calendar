from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

import tkinter as tk

from dashboard_app.models import OrderItem

@dataclass(frozen=True)
class CellStyle:
    bg_in_month: str = "#FFFFFF"
    bg_out_month: str = "#F3F3F3"
    bg_today: str = "#DFF0FF"
    border: str = "#D0D0D0"
    day_font: Tuple[str, int] = ("Segoe UI", 10, "bold")
    orders_font: Tuple[str, int] = ("Consolas", 9)


class CalendarGrid(tk.Frame):
    def __init__(
        self,
        root,
        week_starts_on: str = "mon",
        cell_style: str = "light",
        on_order_double_click=None,
    ):
        super().__init__(root)

        self._root = root
        self._active_orders_canvas: tk.Canvas | None = None
        self._active_canvas_day: date | None = None
        self._on_order_double_click = on_order_double_click

        self._view_mode: str = "month"  # "month" or "week"
        self._grid_dates: List[date] = []
        self.current_month_first_day: date = date.today().replace(day=1)
        self.current_week_anchor_date: date = date.today()

        self.week_starts_on = week_starts_on.lower()
        # Each day cell holds (day_label, orders_canvas, orders_inner_frame).
        # We use a Canvas+Frame so we can add a vertical scrollbar per day cell.
        self._cell_widgets: Dict[date, Tuple[tk.Label, tk.Canvas, tk.Frame, int]] = {}

        # Style (simple; can be expanded).
        self.style = CellStyle()

        self.title_var = tk.StringVar(value="")
        title = tk.Label(self, textvariable=self.title_var, font=("Segoe UI", 26, "bold"))
        title.pack(pady=8)

        grid = tk.Frame(self)
        grid.pack(fill="both", expand=True)
        self._grid_frame = grid
        self._grid_frame.grid_columnconfigure(tuple(range(7)), weight=1)
        self._grid_frame.grid_rowconfigure(tuple(range(7)), weight=1)

        # Weekday header row.
        weekdays = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
        if self.week_starts_on.startswith("sun"):
            weekdays = ["Domingo", "Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado"]
        for col, wd in enumerate(weekdays):
            lbl = tk.Label(
                grid,
                text=wd,
                font=("Segoe UI", 10, "bold"),
                bg="#EAEAEA",
                relief="solid",
                bd=1,
            )
            lbl.grid(row=0, column=col, sticky="nsew", padx=2, pady=2)

        # Enable mouse-wheel scrolling inside the currently hovered day cell.
        # We use `bind_all` so the wheel still works when the mouse is over widgets
        # inside the canvas window (labels/frames).
        self._root.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        if self._active_orders_canvas is None:
            return
        # Windows: event.delta is typically +/-120 per notch.
        units = int(-event.delta / 120)
        if units == 0:
            return
        self._active_orders_canvas.yview_scroll(units, "units")

    def set_month(self, month_first_day: date):
        self._view_mode = "month"
        self.current_month_first_day = month_first_day

        grid_dates = self._calendar_dates_for_month(month_first_day)
        self._grid_dates = grid_dates
        self.title_var.set(self.current_month_first_day.strftime("%B %Y"))

        # Clear existing day cells.
        for child in self._grid_frame.winfo_children():
            # Keep weekday header row (row 0).
            info = child.grid_info()
            if info.get("row") == 0:
                continue
            child.destroy()
        self._cell_widgets.clear()

        # Create a 6-week grid (rows 1..6), 7 columns.
        # grid_dates length is 42.
        for idx, day in enumerate(grid_dates):
            row = 1 + (idx // 7)
            col = idx % 7

            today = date.today()
            if day == today:
                bg = self.style.bg_today
                in_month = True
            else:
                in_month = (day.month == month_first_day.month)
                bg = self.style.bg_in_month if in_month else self.style.bg_out_month

            cell = tk.Frame(
                self._grid_frame,
                bg=bg,
                relief="solid",
                bd=1,
            )
            cell.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
            cell.grid_propagate(False)

            day_lbl = tk.Label(cell, text=str(day.day), bg=bg, font=self.style.day_font, anchor="nw")
            day_lbl.pack(fill="x", padx=4, pady=(2, 0))

            # Scrollable container for multiple rows (text + colored status circle).
            orders_scroll = tk.Frame(cell, bg=bg)
            orders_scroll.pack(fill="both", expand=True, padx=6, pady=(2, 6))

            orders_canvas = tk.Canvas(orders_scroll, bg=bg, highlightthickness=0, borderwidth=0)
            v_scroll = tk.Scrollbar(orders_scroll, orient="vertical", command=orders_canvas.yview)
            orders_canvas.configure(yscrollcommand=v_scroll.set)

            orders_canvas.pack(side="left", fill="both", expand=True)
            v_scroll.pack(side="right", fill="y")

            orders_inner = tk.Frame(orders_canvas, bg=bg)
            window_id = orders_canvas.create_window((0, 0), window=orders_inner, anchor="nw")

            def _on_canvas_configure(event, c=orders_canvas, win=window_id):
                # Keep the inner frame width aligned with the canvas width.
                c.itemconfig(win, width=event.width)

            orders_canvas.bind("<Configure>", _on_canvas_configure)

            self._cell_widgets[day] = (day_lbl, orders_canvas, orders_inner, window_id)

    def set_week(self, week_anchor_date: date):
        """
        Show a single 7-day week view containing `week_anchor_date`.
        """
        self._view_mode = "week"
        self.current_week_anchor_date = week_anchor_date

        week_start = self._start_of_week(week_anchor_date)
        self._grid_dates = [week_start + timedelta(days=i) for i in range(7)]

        self.title_var.set(
            f"{week_start.strftime('%b %d')} - {(week_start + timedelta(days=6)).strftime('%b %d, %Y')}"
        )

        # Clear existing day cells.
        for child in self._grid_frame.winfo_children():
            # Keep weekday header row (row 0).
            info = child.grid_info()
            if info.get("row") == 0:
                continue
            child.destroy()
        self._cell_widgets.clear()

        today = date.today()
        for idx, day in enumerate(self._grid_dates):
            row = 1 + (idx // 7)
            col = idx % 7

            bg = self.style.bg_today if day == today else self.style.bg_in_month

            cell = tk.Frame(
                self._grid_frame,
                bg=bg,
                relief="solid",
                bd=1,
            )
            cell.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
            cell.grid_propagate(False)

            day_lbl = tk.Label(cell, text=str(day.day), bg=bg, font=self.style.day_font, anchor="nw")
            day_lbl.pack(fill="x", padx=4, pady=(2, 0))

            # Scrollable container for multiple rows (text + colored status circle).
            orders_scroll = tk.Frame(cell, bg=bg)
            orders_scroll.pack(fill="both", expand=True, padx=6, pady=(2, 6))

            orders_canvas = tk.Canvas(orders_scroll, bg=bg, highlightthickness=0, borderwidth=0)
            v_scroll = tk.Scrollbar(orders_scroll, orient="vertical", command=orders_canvas.yview)
            orders_canvas.configure(yscrollcommand=v_scroll.set)

            orders_canvas.pack(side="left", fill="both", expand=True)
            v_scroll.pack(side="right", fill="y")

            orders_inner = tk.Frame(orders_canvas, bg=bg)
            window_id = orders_canvas.create_window((0, 0), window=orders_inner, anchor="nw")

            def _on_canvas_configure(event, c=orders_canvas, win=window_id):
                # Keep the inner frame width aligned with the canvas width.
                c.itemconfig(win, width=event.width)

            orders_canvas.bind("<Configure>", _on_canvas_configure)

            self._cell_widgets[day] = (day_lbl, orders_canvas, orders_inner, window_id)

    def query_range_datetimes(self) -> Tuple[datetime, datetime]:
        """
        Compute the [start_dt, end_dt) window that matches the visible calendar cells.
        """
        if not self._grid_dates:
            # Fallback to current month if something went wrong.
            self._grid_dates = self._calendar_dates_for_month(self.current_month_first_day)

        start_day = self._grid_dates[0]
        end_day = self._grid_dates[-1] + timedelta(days=1)
        start_dt = datetime.combine(start_day, datetime.min.time())
        end_dt = datetime.combine(end_day, datetime.min.time())
        return start_dt, end_dt

    def render_orders(self, orders_by_day: Dict[date, List[OrderItem]], max_ids_per_day: int = 50):
        # Fill each cell with the items for that date.
        for day, (_day_lbl, orders_canvas, orders_inner, window_id) in self._cell_widgets.items():
            items = orders_by_day.get(day, [])

            # Clear previous widgets (only inside the scrollable inner frame).
            for child in orders_inner.winfo_children():
                child.destroy()

            truncated = False
            if len(items) > max_ids_per_day:
                items = items[:max_ids_per_day]
                truncated = True

            for item in items:
                row = tk.Frame(orders_inner, bg=orders_inner["bg"])
                row.pack(fill="x", anchor="nw")

                # Track which day cell is being hovered so mouse wheel scrolls it.
                row.bind("<Enter>", lambda e, c=orders_canvas: self._set_active_canvas(c))
                row.bind("<Leave>", lambda e: self._set_active_canvas(None))

                # Text `ORDER_ID - ClientName`.
                canvas = tk.Canvas(row, width=12, height=12, bg=orders_inner["bg"], highlightthickness=0)
                canvas.pack(side="left", padx=(0, 4))
                # Draw a filled circle. Using `create_oval` gives a crisp circle.
                canvas.create_oval(2, 2, 10, 10, fill=item.color, outline="")

                display_text = f"({item.type}) {item.text}"
                lbl = tk.Label(row, text=display_text, bg=orders_inner["bg"], font=self.style.orders_font, anchor="w")
                lbl.pack(side="left", fill="x", expand=True)

                if self._on_order_double_click is not None:
                    # Item text is `ORDER_ID - ClientName` (or just `ORDER_ID`).
                    # Double-click should open the order details for that ORDER_ID.
                    oid = item.text.split(" - ", 1)[0].strip()
                    row.bind(
                        "<Double-Button-1>",
                        lambda e, order_id=oid: self._on_order_double_click(order_id),
                    )
                    lbl.bind(
                        "<Double-Button-1>",
                        lambda e, order_id=oid: self._on_order_double_click(order_id),
                    )

                lbl.bind("<Enter>", lambda e, c=orders_canvas: self._set_active_canvas(c))
                lbl.bind("<Leave>", lambda e: self._set_active_canvas(None))

            if truncated:
                tk.Label(
                    orders_inner,
                    text="...",
                    bg=orders_inner["bg"],
                    font=self.style.orders_font,
                    anchor="w",
                ).pack(fill="x", anchor="w")

            # Update scroll region after filling.
            orders_inner.update_idletasks()
            orders_canvas.update_idletasks()
            bbox = orders_canvas.bbox(window_id)
            if bbox is None:
                bbox = (0, 0, 1, 1)
            orders_canvas.configure(scrollregion=bbox)

    def _set_active_canvas(self, canvas: tk.Canvas | None):
        self._active_orders_canvas = canvas
        self._active_canvas_day = None

    def _calendar_dates_for_month(self, month_first_day: date) -> List[date]:
        year = month_first_day.year
        month = month_first_day.month
        first_day_weekday, days_in_month = calendar.monthrange(year, month)  # weekday 0..6 (Mon..Sun)

        if self.week_starts_on.startswith("sun"):
            # Convert from Mon-based to Sun-based offset.
            # If first_day_weekday==6 (Sun), offset becomes 0; else offset = weekday+1.
            offset = (first_day_weekday + 1) % 7
        else:
            # Mon-based
            offset = first_day_weekday

        grid_start = month_first_day - timedelta(days=offset)
        return [grid_start + timedelta(days=i) for i in range(42)]

    def _start_of_week(self, d: date) -> date:
        """
        Returns the first day of the week that contains `d`,
        based on `self.week_starts_on`.
        """
        if self.week_starts_on.startswith("sun"):
            # Python weekday: Mon=0..Sun=6
            # For Sunday start, shift so Sunday becomes 0.
            offset = (d.weekday() + 1) % 7
        else:
            # Monday start: weekday offset is direct.
            offset = d.weekday()
        return d - timedelta(days=offset)
