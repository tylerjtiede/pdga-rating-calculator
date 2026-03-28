"""
gui.py
------
CustomTkinter desktop GUI for the PDGA rating calculator.
Run with: python -m pdga_rater.gui
"""

import threading
from datetime import datetime

import customtkinter as ctk

from .scraper    import load_player_data, FetchError, ParseError
from .calculator import project_rating, rounds_needed_for_target, build_used_rounds

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C_GREEN  = "#4ade80"
C_RED    = "#f87171"
C_YELLOW = "#facc15"
C_MUTED  = "#94a3b8"
C_CARD   = "#1e293b"
C_BG     = "#0f172a"
C_BORDER = "#334155"
C_ACCENT = "#3b82f6"


# ---------------------------------------------------------------------------
# Reusable widgets
# ---------------------------------------------------------------------------

class RoundsTable(ctk.CTkFrame):
    HEADERS      = ("Tournament", "Rd", "Rating")
    COL_WEIGHTS  = (6, 1, 1)

    def __init__(self, master, title: str, **kwargs):
        super().__init__(master, fg_color=C_CARD, corner_radius=8, **kwargs)
        self._drop_below = 0

        ctk.CTkLabel(
            self, text=title, font=ctk.CTkFont(size=12, weight="bold"),
            text_color=C_MUTED, anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 4))

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=12)
        for col, (h, w) in enumerate(zip(self.HEADERS, self.COL_WEIGHTS)):
            hdr.columnconfigure(col, weight=w)
            ctk.CTkLabel(
                hdr, text=h, font=ctk.CTkFont(size=11, weight="bold"),
                text_color=C_MUTED, anchor="w" if col == 0 else "e",
            ).grid(row=0, column=col, sticky="ew", pady=(0, 4))

        ctk.CTkFrame(self, height=1, fg_color=C_BORDER).pack(fill="x", padx=12)

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", height=130)
        self._scroll.pack(fill="both", expand=True, padx=4, pady=(4, 8))
        for col, w in enumerate(self.COL_WEIGHTS):
            self._scroll.columnconfigure(col, weight=w)

        self._empty = ctk.CTkLabel(
            self._scroll, text="None", text_color=C_MUTED,
            font=ctk.CTkFont(size=12), anchor="w",
        )
        self._rows: list = []

    def update_rows(self, rounds: list[dict], drop_below: float = 0):
        self._drop_below = drop_below
        for w in self._rows:
            w.destroy()
        self._rows.clear()
        self._empty.grid_forget()

        if not rounds:
            self._empty.grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=4)
            return

        for i, rd in enumerate(rounds):
            rating     = rd["rating"]
            is_outlier = rating < drop_below
            color      = C_RED if is_outlier else "white"
            bg         = "#2d1f1f" if is_outlier else "transparent"

            row_f = ctk.CTkFrame(self._scroll, fg_color=bg, corner_radius=4)
            row_f.grid(row=i, column=0, columnspan=3, sticky="ew", pady=1)
            for col, w in enumerate(self.COL_WEIGHTS):
                row_f.columnconfigure(col, weight=w)

            for col, val in enumerate([rd.get("name", "?"), str(rd.get("round", "?")), str(rating)]):
                ctk.CTkLabel(
                    row_f, text=val, font=ctk.CTkFont(size=12),
                    text_color=color, anchor="w" if col == 0 else "e",
                ).grid(row=0, column=col, sticky="ew",
                       padx=(8 if col == 0 else 4, 4), pady=3)

            self._rows.append(row_f)


class RatingDisplay(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=C_CARD, corner_radius=8, **kwargs)

        self._rating_lbl = ctk.CTkLabel(
            self, text="—", font=ctk.CTkFont(size=52, weight="bold"), text_color="white"
        )
        self._rating_lbl.pack(pady=(18, 0))

        self._change_lbl = ctk.CTkLabel(
            self, text="projected rating", font=ctk.CTkFont(size=13), text_color=C_MUTED
        )
        self._change_lbl.pack(pady=(0, 2))

        self._cutoff_lbl = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12), text_color=C_MUTED
        )
        self._cutoff_lbl.pack(pady=(0, 14))

    def update(self, projected: int, current: int, drop_below: float):
        change = projected - current
        color  = C_GREEN if change >= 0 else C_RED
        sign   = "+" if change >= 0 else ""
        self._rating_lbl.configure(text=str(projected))
        self._change_lbl.configure(
            text=f"{sign}{change} from current ({current})", text_color=color
        )
        self._cutoff_lbl.configure(text=f"Outlier cutoff: {int(drop_below)}")

    def reset(self):
        self._rating_lbl.configure(text="—")
        self._change_lbl.configure(text="projected rating", text_color=C_MUTED)
        self._cutoff_lbl.configure(text="")


# ---------------------------------------------------------------------------
# What-if panel
# ---------------------------------------------------------------------------

class WhatIfPanel(ctk.CTkFrame):
    def __init__(self, master, on_change, **kwargs):
        super().__init__(master, fg_color=C_CARD, corner_radius=8, **kwargs)
        self._on_change      = on_change
        self._whatif_ratings: list[int] = []
        self._row_frames:     list[ctk.CTkFrame] = []

        ctk.CTkLabel(
            self, text="What-If Simulator",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).pack(fill="x", padx=14, pady=(12, 0))

        ctk.CTkLabel(
            self, text="Add hypothetical rounds or solve for a target rating.",
            font=ctk.CTkFont(size=11), text_color=C_MUTED, anchor="w", wraplength=280
        ).pack(fill="x", padx=14, pady=(2, 10))

        # Add-round row
        add_row = ctk.CTkFrame(self, fg_color="transparent")
        add_row.pack(fill="x", padx=14, pady=(0, 6))

        self._entry = ctk.CTkEntry(add_row, placeholder_text="Round rating", width=160, height=32)
        self._entry.pack(side="left", padx=(0, 8))
        self._entry.bind("<Return>", lambda e: self._add_round())

        ctk.CTkButton(
            add_row, text="Add Round", width=90, height=32,
            fg_color=C_ACCENT, hover_color="#2563eb", command=self._add_round
        ).pack(side="left")

        # Target-rating solver row
        target_row = ctk.CTkFrame(self, fg_color="transparent")
        target_row.pack(fill="x", padx=14, pady=(0, 10))

        self._target_entry = ctk.CTkEntry(target_row, placeholder_text="Target rating", width=120, height=32)
        self._target_entry.pack(side="left", padx=(0, 6))

        self._rounds_entry = ctk.CTkEntry(target_row, placeholder_text="# rounds", width=70, height=32)
        self._rounds_entry.pack(side="left", padx=(0, 8))
        self._rounds_entry.insert(0, "3")

        ctk.CTkButton(
            target_row, text="Solve", width=70, height=32,
            fg_color="#7c3aed", hover_color="#6d28d9", command=self._solve_target
        ).pack(side="left")

        # Target result label
        self._target_lbl = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12),
            text_color=C_MUTED, anchor="w", wraplength=280
        )
        self._target_lbl.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkFrame(self, height=1, fg_color=C_BORDER).pack(fill="x", padx=14)

        # Scrollable list
        self._list = ctk.CTkScrollableFrame(self, fg_color="transparent", height=180)
        self._list.pack(fill="both", expand=True, padx=8, pady=8)

        self._empty_lbl = ctk.CTkLabel(
            self._list, text="No hypothetical rounds yet.",
            text_color=C_MUTED, font=ctk.CTkFont(size=12)
        )
        self._empty_lbl.pack(pady=14)

    # ── Internal ──────────────────────────────────────────────────

    def _add_round(self):
        val = self._entry.get().strip()
        if not val.lstrip("-").isdigit():
            self._entry.configure(border_color=C_RED)
            self._entry.after(800, lambda: self._entry.configure(border_color=C_BORDER))
            return
        self._whatif_ratings.append(int(val))
        self._entry.delete(0, "end")
        self._rebuild()
        self._on_change(list(self._whatif_ratings))

    def _remove_round(self, idx: int):
        self._whatif_ratings.pop(idx)
        self._rebuild()
        self._on_change(list(self._whatif_ratings))

    def _rebuild(self):
        for f in self._row_frames:
            f.destroy()
        self._row_frames.clear()

        if not self._whatif_ratings:
            self._empty_lbl.pack(pady=14)
            return
        self._empty_lbl.pack_forget()

        for i, rating in enumerate(self._whatif_ratings):
            row = ctk.CTkFrame(self._list, fg_color="#1a2744", corner_radius=6)
            row.pack(fill="x", pady=3, padx=2)

            ctk.CTkLabel(
                row, text=f"Rd {i+1}", font=ctk.CTkFont(size=12),
                text_color=C_MUTED, width=50, anchor="w"
            ).pack(side="left", padx=(10, 4), pady=6)

            ctk.CTkLabel(
                row, text=str(rating),
                font=ctk.CTkFont(size=13, weight="bold"), text_color="white"
            ).pack(side="left")

            idx = i
            ctk.CTkButton(
                row, text="✕", width=28, height=24,
                fg_color="transparent", hover_color="#3f1f1f", text_color=C_RED,
                command=lambda i=idx: self._remove_round(i)
            ).pack(side="right", padx=6)

            self._row_frames.append(row)

    def _solve_target(self):
        target_str = self._target_entry.get().strip()
        rounds_str = self._rounds_entry.get().strip()

        if not target_str.isdigit() or not rounds_str.isdigit():
            self._target_lbl.configure(
                text="Enter a valid target rating and number of rounds.", text_color=C_YELLOW
            )
            return

        # Fire callback with a special signal so App can run the solver
        self._on_change(list(self._whatif_ratings), solve_target=int(target_str), solve_rounds=int(rounds_str))

    def set_target_result(self, msg: str, success: bool):
        color = C_GREEN if success else C_RED
        self._target_lbl.configure(text=msg, text_color=color)

    def get_ratings(self) -> list[int]:
        return list(self._whatif_ratings)

    def reset(self):
        self._whatif_ratings.clear()
        self._rebuild()
        self._target_lbl.configure(text="", text_color=C_MUTED)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PDGA Rating Calculator")
        self.geometry("940x720")
        self.minsize(820, 600)
        self.configure(fg_color=C_BG)

        self._base_data:    dict | None = None
        self._player_data:  dict | None = None

        self._build_ui()

    def _build_ui(self):
        # Top bar
        topbar = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=0, height=58)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        ctk.CTkLabel(
            topbar, text="PDGA Rating Calculator",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(side="left", padx=20)

        input_row = ctk.CTkFrame(topbar, fg_color="transparent")
        input_row.pack(side="right", padx=20)

        self._refresh_btn = ctk.CTkButton(
            input_row, text="↺ Refresh", width=84, height=34,
            fg_color="#334155", hover_color="#475569",
            command=lambda: self._start_fetch(force_refresh=True),
        )
        self._refresh_btn.pack(side="right", padx=(6, 0))

        self._fetch_btn = ctk.CTkButton(
            input_row, text="Calculate", width=100, height=34,
            command=self._start_fetch,
        )
        self._fetch_btn.pack(side="right")

        self._pdga_entry = ctk.CTkEntry(
            input_row, placeholder_text="PDGA number", width=150, height=34,
        )
        self._pdga_entry.pack(side="right", padx=(0, 10))
        self._pdga_entry.bind("<Return>", lambda e: self._start_fetch())

        # Status bar
        self._status = ctk.CTkLabel(
            self, text="Enter a PDGA number to get started.",
            font=ctk.CTkFont(size=12), text_color=C_MUTED, anchor="w",
        )
        self._status.pack(fill="x", padx=20, pady=(8, 0))

        # Content grid
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=14, pady=10)
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        for r in range(4):
            content.rowconfigure(r, weight=1)

        self._rating_disp = RatingDisplay(content)
        self._rating_disp.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))

        self._whatif = WhatIfPanel(content, on_change=self._on_whatif_change)
        self._whatif.grid(row=0, column=1, rowspan=4, sticky="nsew", padx=(8, 0))

        self._incoming_tbl = RoundsTable(content, "Rounds Coming In")
        self._incoming_tbl.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))

        self._outgoing_tbl = RoundsTable(content, "Rounds Dropping Off")
        self._outgoing_tbl.grid(row=2, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))

        self._outlier_tbl = RoundsTable(content, "Outlier Rounds (excluded)")
        self._outlier_tbl.grid(row=3, column=0, sticky="nsew", padx=(0, 8))

    # ── Fetch ──────────────────────────────────────────────────────

    def _start_fetch(self, force_refresh: bool = False):
        pdga = self._pdga_entry.get().strip()
        if not pdga:
            self._set_status("Please enter a PDGA number.", C_YELLOW)
            return

        self._fetch_btn.configure(state="disabled", text="Loading…")
        self._refresh_btn.configure(state="disabled")
        self._base_data   = None
        self._player_data = None
        self._rating_disp.reset()
        self._whatif.reset()
        for t in [self._incoming_tbl, self._outgoing_tbl, self._outlier_tbl]:
            t.update_rows([])

        threading.Thread(
            target=self._fetch_worker,
            args=(pdga, force_refresh),
            daemon=True,
        ).start()

    def _fetch_worker(self, pdga: str, force_refresh: bool):
        try:
            self._set_status("Fetching player data…")
            data = load_player_data(pdga, force_refresh=force_refresh)
            self.after(0, lambda d=data: self._on_fetch_done(d))
        except (FetchError, ParseError) as e:
            self.after(0, lambda e=e: self._set_status(f"Error: {e}", C_RED))
            self.after(0, self._reset_buttons)

    def _on_fetch_done(self, data: dict):
        self._player_data = data
        result = project_rating(data["tournaments"], data["new_tournaments"])
        self._base_data = {**data, **result}
        self._render(result, data["current_rating"])
        self._set_status("Done.", C_GREEN)
        self._reset_buttons()

    def _reset_buttons(self):
        self._fetch_btn.configure(state="normal", text="Calculate")
        self._refresh_btn.configure(state="normal")

    def _set_status(self, msg: str, color: str = C_MUTED):
        self._status.configure(text=msg, text_color=color)

    # ── Render ─────────────────────────────────────────────────────

    def _render(self, result: dict, current_rating: int):
        db = result["drop_below"]
        self._rating_disp.update(result["projected_rating"], current_rating, db)
        self._incoming_tbl.update_rows(result["incoming_rounds"],  db)
        self._outgoing_tbl.update_rows(result["outgoing_rounds"],  db)
        self._outlier_tbl.update_rows(result["outlier_rounds"],    db)

    # ── What-if / solver ───────────────────────────────────────────

    def _on_whatif_change(
        self,
        whatif_ratings: list[int],
        solve_target:   int | None = None,
        solve_rounds:   int | None = None,
    ):
        if self._player_data is None:
            return

        tournaments     = self._player_data["tournaments"]
        new_tournaments = self._player_data["new_tournaments"]
        current_rating  = self._player_data["current_rating"]

        result = project_rating(tournaments, new_tournaments, whatif_ratings or None)
        self._render(result, current_rating)

        change = result["projected_rating"] - current_rating
        sign   = "+" if change >= 0 else ""

        if whatif_ratings:
            self._set_status(
                f"What-if: {len(whatif_ratings)} hypothetical round(s) → "
                f"projected {result['projected_rating']} ({sign}{change})",
                C_ACCENT,
            )
        else:
            self._set_status("Done.", C_GREEN)

        if solve_target is not None and solve_rounds is not None:
            try:
                tr = rounds_needed_for_target(
                    tournaments, new_tournaments, solve_target, solve_rounds
                )
                if tr["achievable"]:
                    self._whatif.set_target_result(
                        f"Need avg {tr['needed_avg']} × {solve_rounds} rd(s) → {tr['with_avg']}",
                        success=True,
                    )
                else:
                    self._whatif.set_target_result(tr["message"], success=False)
            except ValueError as e:
                self._whatif.set_target_result(str(e), success=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
