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
    day_font: Tuple[str, int] = ("Helvetica", 10, "bold")
    orders_font: Tuple[str, int] = ("Helvetica", 9)


class CalendarGrid(tk.Frame):
    def __init__(
        self,
        root,
        week_starts_on: str = "mon",
        cell_style: str = "light",
        on_order_double_click=None,
        on_refresh_now=None,
    ):
        super().__init__(root)

        self._root = root
        self._active_orders_canvas: tk.Canvas | None = None
        self._active_canvas_day: date | None = None
        self._on_order_double_click = on_order_double_click
        self._on_refresh_now = on_refresh_now
        self._day_sort_state: Dict[date, Tuple[str, bool]] = {}
        self._global_sort: Tuple[str, bool] = ("client", True)
        self._last_render_orders_by_day: Dict[date, List[OrderItem]] = {}
        self._last_render_max_ids_per_day: int = 50
        self._order_col_minsizes = [24, 62, 62, 74]

        self._view_mode: str = "month"  # "month" or "week"
        self._grid_dates: List[date] = []
        self._visible_columns: int = 7
        self._show_saturday: bool = True
        self.current_month_first_day: date = date.today().replace(day=1)
        self.current_week_anchor_date: date = date.today()

        self.week_starts_on = week_starts_on.lower()
        # Each day cell holds (day_left_label, day_week_label, orders_canvas, orders_inner_frame).
        # We use a Canvas+Frame so we can add a vertical scrollbar per day cell.
        self._cell_widgets: Dict[date, Tuple[tk.Label, tk.Label, tk.Canvas, tk.Frame, int]] = {}

        # Style (simple; can be expanded).
        self.style = CellStyle()

        self.title_var = tk.StringVar(value="")

        header = tk.Frame(self)
        header.pack(fill="x", padx=8, pady=8)

        self._title_label = tk.Label(header, textvariable=self.title_var, font=("Helvetica", 26, "bold"), anchor="w")
        self._title_label.pack(side="left")

        right = tk.Frame(header)
        right.pack(side="right")

        grid = tk.Frame(self)
        grid.pack(fill="both", expand=True)
        self._grid_frame = grid
        self._header_labels: List[tk.Label] = []
        for col in range(7):
            self._grid_frame.grid_columnconfigure(col, weight=1)
        # Keep row 0 as dedicated weekday header row.
        self._grid_frame.grid_rowconfigure(0, weight=0, minsize=28)
        for r in range(1, 7):
            self._grid_frame.grid_rowconfigure(r, weight=1)

        self._render_weekday_header(
            ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
        )

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
        """
        Show a 4-week window (Mon..Sat):
        previous week + current week + next two weeks.
        """
        self._view_mode = "month"
        self._visible_columns = 6
        self._show_saturday = True
        self.current_month_first_day = month_first_day
        self.current_week_anchor_date = month_first_day

        # 4-week template uses Monday..Saturday only (no Sunday column).
        week_start = self._start_of_week(month_first_day)
        first_week_start = week_start - timedelta(days=7)  # previous week
        grid_dates: List[date] = []
        for w in range(4):
            ws = first_week_start + timedelta(days=7 * w)
            grid_dates.extend([ws + timedelta(days=i) for i in range(6)])  # Mon..Sat
        self._grid_dates = grid_dates
        self.title_var.set(
            f"{grid_dates[0].strftime('%d %b %Y')} - {grid_dates[-1].strftime('%d %b %Y')}"
        )

        # Clear existing day cells.
        for child in self._grid_frame.winfo_children():
            # Keep weekday header row (row 0).
            info = child.grid_info()
            if str(info.get("row")) == "0":
                continue
            child.destroy()
        self._cell_widgets.clear()

        # Re-render weekday header after rebuild to ensure visibility.
        self._render_weekday_header(
            ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
        )

        # Create a 4-week grid (rows 1..4), 6 columns (Mon..Sat).
        # grid_dates length is 24.
        for idx, day in enumerate(grid_dates):
            row = 1 + (idx // self._visible_columns)
            col = idx % self._visible_columns

            today = date.today()
            if day == today:
                bg = self.style.bg_today
                in_month = True
            else:
                bg = self.style.bg_in_month

            cell = tk.Frame(
                self._grid_frame,
                bg=bg,
                relief="solid",
                bd=1,
            )
            cell.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
            cell.grid_propagate(False)

            day_header = tk.Frame(cell, bg=bg)
            day_header.pack(fill="x", padx=4, pady=(2, 0))
            day_header.grid_columnconfigure(0, weight=1)
            day_header.grid_columnconfigure(1, weight=0)

            day_lbl = tk.Label(day_header, text=self._day_label_text(day), bg=bg, font=self.style.day_font, anchor="w")
            day_lbl.grid(row=0, column=0, sticky="w")
            week_lbl = tk.Label(day_header, text="", bg=bg, fg="#1f6feb", font=self.style.day_font, anchor="e")
            week_lbl.grid(row=0, column=1, sticky="e")

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

            self._cell_widgets[day] = (day_lbl, week_lbl, orders_canvas, orders_inner, window_id)

        # 4-week template never shows Sunday column.
        self._set_column_visibility(show_saturday=True, show_sunday=False)
        # Force header visibility after grid rebuild.
        self._refresh_weekday_header_for_visibility()

    def set_week(self, week_anchor_date: date):
        """
        Show a 2-week view (current + next), Monday..Saturday columns.
        """
        self._view_mode = "week"
        self._visible_columns = 6
        self._show_saturday = True
        self.current_week_anchor_date = week_anchor_date

        week_start = self._start_of_week(week_anchor_date)  # Monday
        # Two rows: current week + next week, Monday..Saturday (12 days total), no Sundays.
        first_week = [week_start + timedelta(days=i) for i in range(6)]  # Mon..Sat
        second_week_start = week_start + timedelta(days=7)
        second_week = [second_week_start + timedelta(days=i) for i in range(6)]  # Mon..Sat
        self._grid_dates = first_week + second_week

        self.title_var.set(f"{week_start.strftime('%b %d')} - {(second_week[-1]).strftime('%b %d, %Y')}")

        # Clear existing day cells.
        for child in self._grid_frame.winfo_children():
            # Keep weekday header row (row 0).
            info = child.grid_info()
            if str(info.get("row")) == "0":
                continue
            child.destroy()
        self._cell_widgets.clear()

        self._render_weekday_header(
            ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
        )

        today = date.today()
        for idx, day in enumerate(self._grid_dates):
            row = 1 + (idx // self._visible_columns)
            col = idx % self._visible_columns

            bg = self.style.bg_today if day == today else self.style.bg_in_month

            cell = tk.Frame(
                self._grid_frame,
                bg=bg,
                relief="solid",
                bd=1,
            )
            cell.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
            cell.grid_propagate(False)

            day_header = tk.Frame(cell, bg=bg)
            day_header.pack(fill="x", padx=4, pady=(2, 0))
            day_header.grid_columnconfigure(0, weight=1)
            day_header.grid_columnconfigure(1, weight=0)

            day_lbl = tk.Label(day_header, text=self._day_label_text(day), bg=bg, font=self.style.day_font, anchor="w")
            day_lbl.grid(row=0, column=0, sticky="w")
            week_lbl = tk.Label(day_header, text="", bg=bg, fg="#1f6feb", font=self.style.day_font, anchor="e")
            week_lbl.grid(row=0, column=1, sticky="e")

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

            self._cell_widgets[day] = (day_lbl, week_lbl, orders_canvas, orders_inner, window_id)

        self._set_column_visibility(show_saturday=True, show_sunday=False)
        self._refresh_weekday_header_for_visibility()

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
        self._last_render_orders_by_day = {d: list(v) for d, v in orders_by_day.items()}
        self._last_render_max_ids_per_day = max_ids_per_day

        # Show Saturday only when any visible Saturday cell has orders.
        visible_saturdays = {d for d in self._cell_widgets.keys() if d.weekday() == 5}
        has_saturday_orders = any(len(orders_by_day.get(d, [])) > 0 for d in visible_saturdays)
        if has_saturday_orders != self._show_saturday:
            self._show_saturday = has_saturday_orders
            self._refresh_weekday_header_for_visibility()
            self._set_column_visibility(show_saturday=self._show_saturday, show_sunday=False)

        # Fill each cell with the items for that date.
        for day, (day_lbl, week_lbl, orders_canvas, orders_inner, window_id) in self._cell_widgets.items():
            items = orders_by_day.get(day, [])
            items = self._sorted_items_for_day(day, items)
            if day.weekday() == 0:
                week_num = day.isocalendar().week
                day_lbl.config(text=f"{day.day} ({len(items)} pedidos)")
                week_lbl.config(text=f"[Semana {week_num}]")
            else:
                day_lbl.config(text=f"{day.day} ({len(items)} pedidos)")
                week_lbl.config(text="")

            # Clear previous widgets (only inside the scrollable inner frame).
            for child in orders_inner.winfo_children():
                child.destroy()

            # if items:
            #     self._build_sort_header(orders_inner, day)

            truncated = False
            if len(items) > max_ids_per_day:
                items = items[:max_ids_per_day]
                truncated = True

            for item in items:
                row = tk.Frame(orders_inner, bg=orders_inner["bg"])
                row.pack(fill="x", anchor="nw")
                self._configure_order_columns(row)

                # Track which day cell is being hovered so mouse wheel scrolls it.
                row.bind("<Enter>", lambda e, c=orders_canvas: self._set_active_canvas(c))
                row.bind("<Leave>", lambda e: self._set_active_canvas(None))

                # Parse "ORDER_ID - CompanyName" into separate values for row rendering.
                if " - " in item.text:
                    order_num, company_name = item.text.split(" - ", 1)
                else:
                    order_num, company_name = item.text, ""

                # 1) Color dot first (production status). If no production rows, keep this area empty.
                if item.prod_color:
                    prod_canvas = tk.Canvas(row, width=12, height=12, bg=orders_inner["bg"], highlightthickness=0)
                    prod_canvas.grid(row=0, column=0, padx=(2, 2), pady=(0, 0))
                    prod_canvas.create_oval(2, 2, 10, 10, fill=item.prod_color, outline="")
                else:
                    tk.Label(row, text="", bg=orders_inner["bg"], width=2).grid(
                        row=0, column=0, padx=(2, 2), pady=(0, 0), sticky="w"
                    )

                # 2) Type
                type_lbl = tk.Label(
                    row,
                    text=f"({item.type})",
                    bg=orders_inner["bg"],
                    font=self.style.orders_font,
                    anchor="w",
                    width=8,
                )
                type_lbl.grid(row=0, column=1, sticky="w", padx=(2, 2))

                # 3) Order number
                order_lbl = tk.Label(
                    row,
                    text=str(order_num).strip(),
                    bg=orders_inner["bg"],
                    font=(self.style.orders_font[0], self.style.orders_font[1], "bold")
                    if item.revisa_modif
                    else self.style.orders_font,
                    fg="#c0392b" if item.revisa_modif else "#000000",
                    anchor="w",
                    width=8,
                )
                order_lbl.grid(row=0, column=2, sticky="w", padx=(2, 2))

                # 4) Revisa letters (V/C/B/P/A)
                revisa_lbl = tk.Label(
                    row,
                    text=item.revisa_letters,
                    bg=orders_inner["bg"],
                    font=self.style.orders_font,
                    fg="#555555",
                    anchor="w",
                    width=9,
                )
                revisa_lbl.grid(row=0, column=3, sticky="w", padx=(2, 2))

                # 5) Company name
                company_lbl = tk.Label(
                    row,
                    text=str(company_name).strip(),
                    bg=orders_inner["bg"],
                    font=self.style.orders_font,
                    anchor="w",
                )
                company_lbl.grid(row=0, column=4, sticky="ew", padx=(2, 0))

                if self._on_order_double_click is not None:
                    # Item text is `ORDER_ID - ClientName` (or just `ORDER_ID`).
                    # Double-click should open the order details for that ORDER_ID.
                    oid = item.text.split(" - ", 1)[0].strip()
                    row.bind(
                        "<Double-Button-1>",
                        lambda e, order_id=oid, d=day, it=item: self._on_order_double_click(order_id, d, it),
                    )
                    order_lbl.bind(
                        "<Double-Button-1>",
                        lambda e, order_id=oid, d=day, it=item: self._on_order_double_click(order_id, d, it),
                    )
                    revisa_lbl.bind(
                        "<Double-Button-1>",
                        lambda e, order_id=oid, d=day, it=item: self._on_order_double_click(order_id, d, it),
                    )
                    company_lbl.bind(
                        "<Double-Button-1>",
                        lambda e, order_id=oid, d=day, it=item: self._on_order_double_click(order_id, d, it),
                    )

                order_lbl.bind("<Enter>", lambda e, c=orders_canvas: self._set_active_canvas(c))
                order_lbl.bind("<Leave>", lambda e: self._set_active_canvas(None))
                revisa_lbl.bind("<Enter>", lambda e, c=orders_canvas: self._set_active_canvas(c))
                revisa_lbl.bind("<Leave>", lambda e: self._set_active_canvas(None))
                company_lbl.bind("<Enter>", lambda e, c=orders_canvas: self._set_active_canvas(c))
                company_lbl.bind("<Leave>", lambda e: self._set_active_canvas(None))

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

    def _sorted_items_for_day(self, day: date, items: List[OrderItem]) -> List[OrderItem]:
        sort_state = self._global_sort or self._day_sort_state.get(day)
        if not sort_state:
            return list(items)

        key_name, asc = sort_state
        out = list(items)

        def _color_rank(it: OrderItem) -> int:
            # Sort by the visible first-dot color in the row.
            dot = (it.prod_color or "#b0b0b0").lower()
            return {
                "#2ecc71": 0,  # green
                "#f1c40f": 1,  # yellow
                "#e74c3c": 2,  # red
                "#b0b0b0": 3,  # gray
            }.get(dot, 9)

        def _id_value(it: OrderItem):
            raw = (it.text.split(" - ", 1)[0]).strip()
            return int(raw) if raw.isdigit() else raw.lower()

        if key_name == "color":
            key_fn = lambda it: (_color_rank(it), (it.text or "").lower())
        elif key_name == "type":
            key_fn = lambda it: ((it.type or "").lower(), (it.text or "").lower())
        elif key_name == "id":
            key_fn = lambda it: (_id_value(it), (it.text or "").lower())
        elif key_name == "client":
            key_fn = lambda it: ((it.client_name or "").lower(), (it.text or "").lower())
        else:
            return out

        out.sort(key=key_fn, reverse=not asc)
        return out

    def set_global_sort(self, key_name: str, ascending: bool = True):
        self._global_sort = (key_name, ascending)
        if self._last_render_orders_by_day:
            self.render_orders(self._last_render_orders_by_day, self._last_render_max_ids_per_day)

    def _toggle_day_sort(self, day: date, key_name: str):
        current = self._day_sort_state.get(day)
        if current is None or current[0] != key_name:
            self._day_sort_state[day] = (key_name, True)
        else:
            self._day_sort_state[day] = (key_name, not current[1])

        self.render_orders(self._last_render_orders_by_day, self._last_render_max_ids_per_day)

    def _header_cell(self, parent: tk.Frame, day: date, key_name: str, label_text: str, width: int, col: int):
        active_key, active_asc = self._day_sort_state.get(day, ("", True))
        is_active = active_key == key_name
        bg = "#AFAFAF" if is_active else "#CFCFCF"
        suffix = f" {'^' if active_asc else 'v'}" if is_active else ""

        lbl = tk.Label(
            parent,
            text=f"{label_text}{suffix}",
            font=("Helvetica", 8, "bold"),
            bg=bg,
            fg="#2F2F2F",
            width=width,
            anchor="center",
            relief="solid",
            bd=1,
            cursor="hand2",
        )
        lbl.grid(row=0, column=col, sticky="ew", padx=(0, 1))
        lbl.bind("<Button-1>", lambda _e, d=day, k=key_name: self._toggle_day_sort(d, k))
        return lbl

    def _build_sort_header(self, orders_inner: tk.Frame, day: date):
        header = tk.Frame(orders_inner, bg="#CFCFCF", height=18)
        header.pack(fill="x", anchor="nw", pady=(0, 1))
        header.pack_propagate(False)
        self._configure_order_columns(header)

        # Match row layout: color | type | id | revisa (skip) | client
        self._header_cell(header, day, "color", "S", width=3, col=0)
        self._header_cell(header, day, "type", "TIPO", width=8, col=1)
        self._header_cell(header, day, "id", "ID", width=8, col=2)

        checks_lbl = tk.Label(
            header,
            text="CHECKS",
            bg="#CFCFCF",
            fg="#2F2F2F",
            font=("Helvetica", 8, "bold"),
            width=9,
            relief="solid",
            bd=1,
            anchor="center",
        )
        checks_lbl.grid(row=0, column=3, sticky="ew", padx=(0, 1))

        active_key, active_asc = self._day_sort_state.get(day, ("", True))
        client_is_active = active_key == "client"
        client_bg = "#AFAFAF" if client_is_active else "#CFCFCF"
        client_suffix = f" {'^' if active_asc else 'v'}" if client_is_active else ""
        client_lbl = tk.Label(
            header,
            text=f"CLIENTE{client_suffix}",
            font=("Helvetica", 8, "bold"),
            bg=client_bg,
            fg="#2F2F2F",
            anchor="w",
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=6,
        )
        client_lbl.grid(row=0, column=4, sticky="ew")
        client_lbl.bind("<Button-1>", lambda _e, d=day: self._toggle_day_sort(d, "client"))

    def _configure_order_columns(self, container: tk.Widget):
        container.grid_columnconfigure(0, minsize=self._order_col_minsizes[0], weight=0)
        container.grid_columnconfigure(1, minsize=self._order_col_minsizes[1], weight=0)
        container.grid_columnconfigure(2, minsize=self._order_col_minsizes[2], weight=0)
        container.grid_columnconfigure(3, minsize=self._order_col_minsizes[3], weight=0)
        container.grid_columnconfigure(4, weight=1)

    def _refresh_weekday_header_for_visibility(self):
        if self._show_saturday:
            weekdays = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
        else:
            weekdays = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
        self._render_weekday_header(weekdays)

    def _set_column_visibility(self, show_saturday: bool, show_sunday: bool):
        # Columns are always Mon..Sun indexes in month view; Mon..Sat in week view.
        hidden_cols = set()
        if not show_saturday:
            hidden_cols.add(5)
        if not show_sunday:
            hidden_cols.add(6)

        max_col = 6
        for col in range(7):
            if col >= max_col or col in hidden_cols:
                self._grid_frame.grid_columnconfigure(col, weight=0, minsize=0)
            else:
                # Saturday is narrower (about 75% of other columns) when visible.
                if col == 5 and show_saturday:
                    self._grid_frame.grid_columnconfigure(col, weight=3)
                else:
                    self._grid_frame.grid_columnconfigure(col, weight=4)

        for child in self._grid_frame.winfo_children():
            info = child.grid_info()
            col = int(info.get("column", 0))
            if col >= max_col or col in hidden_cols:
                child.grid_remove()
            else:
                child.grid()

    def set_last_refresh_text(self, text: str):
        # Kept for backwards compatibility; refresh is now shown in app top bar only.
        return

    def set_title_visible(self, visible: bool):
        if visible:
            self._title_label.pack(side="left")
        else:
            self._title_label.pack_forget()

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
        Returns Monday of the week that contains `d`.
        """
        offset = d.weekday()  # Mon=0..Sun=6
        return d - timedelta(days=offset)

    def _day_label_text(self, d: date) -> str:
        # Show week number on Mondays, e.g. "6 (Semana 10)".
        if d.weekday() == 0:
            week_num = d.isocalendar().week
            return f"{d.day} (Semana {week_num})"
        return str(d.day)

    def _render_weekday_header(self, weekdays: List[str]):
        # Remove previous header labels.
        for lbl in self._header_labels:
            lbl.destroy()
        self._header_labels.clear()

        # Reconfigure columns: visible ones stretch, hidden ones collapse.
        for col in range(7):
            self._grid_frame.grid_columnconfigure(col, weight=1 if col < len(weekdays) else 0, minsize=0)

        for col, wd in enumerate(weekdays):
            lbl = tk.Label(
                self._grid_frame,
                text=wd,
                font=("Helvetica", 10, "bold"),
                bg="#EAEAEA",
                relief="solid",
                bd=1,
            )
            lbl.grid(row=0, column=col, sticky="nsew", padx=2, pady=2)
            self._header_labels.append(lbl)
