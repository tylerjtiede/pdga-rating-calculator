"""
gui.py
------
CustomTkinter desktop GUI for the PDGA ratings calculator.
Themed to match tylerjtiede.github.io — dark editorial palette,
DM font family, warm gold accent.

Run with: pdga-ratings-gui

Font setup:
  Download the DM font family from https://fonts.google.com and place the
  following files in a fonts/ folder in the project root:
    fonts/DMSerifDisplay-Regular.ttf
    fonts/DMMono-Regular.ttf
    fonts/DMSans-Regular.ttf
  The GUI works without them (falls back to system fonts) but looks best with them.
"""

import sys
import threading
from pathlib import Path

import customtkinter as ctk

from .scraper    import load_player_data, FetchError, ParseError
from .calculator import project_rating, rounds_needed_for_target

# ---------------------------------------------------------------------------
# Color palette — matches styles.css exactly
# ---------------------------------------------------------------------------

C_BG      = "#0E0E12"   # --bg
C_BG2     = "#14141A"   # --bg2
C_CARD    = "#18181F"   # --card
C_BORDER  = "#2A2A35"   # rgba(255,255,255,0.07) approximated
C_TEXT    = "#E8E8EC"   # --text
C_MUTED   = "#7A7A90"   # --muted
C_ACCENT  = "#C8A96E"   # --accent  (warm gold)
C_ACCENT2 = "#6E8EC8"   # --accent2 (steel blue)
C_SUCCESS = "#6EC88A"   # --success
C_DANGER  = "#C86E6E"   # --danger
C_YELLOW  = "#C8A96E"   # warnings reuse gold

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ---------------------------------------------------------------------------
# Font loading
# ---------------------------------------------------------------------------

def _find_fonts_dir() -> Path | None:
    for p in [Path(__file__).parent.parent / "fonts", Path.cwd() / "fonts"]:
        if p.is_dir():
            return p
    return None


def _load_fonts() -> dict[str, str]:
    """
    Try to load DM fonts from fonts/ directory.
    Returns family names to use in CTkFont, falling back to system fonts.
    """
    defaults = {
        "serif": "Georgia",
        "mono":  "Courier New",
        "sans":  "Segoe UI" if sys.platform == "win32" else "Helvetica",
    }

    fonts_dir = _find_fonts_dir()
    if fonts_dir is None:
        return defaults

    result = dict(defaults)
    mapping = {
        "serif": ("DMSerifDisplay-Regular.ttf", "DM Serif Display"),
        "mono":  ("DMMono-Regular.ttf",         "DM Mono"),
        "sans":  ("DMSans-Regular.ttf",          "DM Sans"),
    }

    # Use tkinter's font loading (works cross-platform)
    try:
        import tkinter as tk
        import tkinter.font as tkfont
        root = tk.Tk()
        root.withdraw()
        for role, (filename, family) in mapping.items():
            path = fonts_dir / filename
            if path.exists():
                try:
                    tkfont.Font(root=root, name=family, file=str(path))
                    result[role] = family
                except Exception:
                    pass
        root.destroy()
    except Exception:
        pass

    return result


FONTS = _load_fonts()
F_SERIF = FONTS["serif"]
F_MONO  = FONTS["mono"]
F_SANS  = FONTS["sans"]


def font_mono(size: int = 11, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=F_MONO, size=size, weight=weight)

def font_serif(size: int = 14, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=F_SERIF, size=size, weight=weight)

def font_sans(size: int = 12, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=F_SANS, size=size, weight=weight)


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class SectionLabel(ctk.CTkFrame):
    """
    Uppercase mono label with trailing rule.
    Mirrors .section-label::after from the site.
    """
    def __init__(self, master, text: str, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self, text=text.upper(),
            font=font_mono(9), text_color=C_ACCENT, anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkFrame(self, height=1, fg_color=C_BORDER).grid(
            row=0, column=1, sticky="ew", padx=(10, 0)
        )


class RoundsTable(ctk.CTkFrame):
    """
    Non-scrolling card of tournament rounds, sized to content.
    """
    COL_WEIGHTS = (6, 1, 1)

    def __init__(self, master, title: str, **kwargs):
        super().__init__(master, fg_color=C_CARD, corner_radius=10,
                         border_width=1, border_color=C_BORDER, **kwargs)

        SectionLabel(self, title).pack(fill="x", padx=16, pady=(14, 10))

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(0, 4))
        for col, (h, w) in enumerate(zip(("Tournament", "Rd", "Rating"), self.COL_WEIGHTS)):
            hdr.columnconfigure(col, weight=w)
            ctk.CTkLabel(
                hdr, text=h.upper(),
                font=font_mono(8), text_color=C_MUTED,
                anchor="w" if col == 0 else "e",
            ).grid(row=0, column=col, sticky="ew")

        ctk.CTkFrame(self, height=1, fg_color=C_BORDER).pack(fill="x", padx=16)

        self._body = ctk.CTkFrame(self, fg_color="transparent")
        self._body.pack(fill="x", padx=8, pady=(4, 12))
        for col, w in enumerate(self.COL_WEIGHTS):
            self._body.columnconfigure(col, weight=w)

        self._empty = ctk.CTkLabel(
            self._body, text="None",
            font=font_mono(11), text_color=C_MUTED, anchor="w",
        )
        self._rows: list = []

    def update_rows(self, rounds: list[dict], drop_below: float = 0):
        for w in self._rows:
            w.destroy()
        self._rows.clear()
        self._empty.grid_forget()

        if not rounds:
            self._empty.grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=8)
            return

        for i, rd in enumerate(rounds):
            rating     = rd["rating"]
            is_outlier = rating < drop_below

            row_f = ctk.CTkFrame(self._body, fg_color="transparent", corner_radius=0)
            row_f.grid(row=i, column=0, columnspan=3, sticky="ew")
            for col, w in enumerate(self.COL_WEIGHTS):
                row_f.columnconfigure(col, weight=w)

            if i > 0:
                ctk.CTkFrame(row_f, height=1, fg_color=C_BORDER).grid(
                    row=0, column=0, columnspan=3, sticky="ew"
                )

            ctk.CTkLabel(
                row_f, text=rd.get("name", "?"),
                font=font_sans(11), text_color=C_MUTED, anchor="w",
            ).grid(row=1, column=0, sticky="ew", padx=(8, 4), pady=5)

            ctk.CTkLabel(
                row_f, text=str(rd.get("round", "?")),
                font=font_mono(11), text_color=C_MUTED, anchor="e",
            ).grid(row=1, column=1, sticky="ew", padx=4, pady=5)

            ctk.CTkLabel(
                row_f, text=str(rating),
                font=font_mono(11), text_color=C_DANGER if is_outlier else C_TEXT, anchor="e",
            ).grid(row=1, column=2, sticky="ew", padx=(4, 8), pady=5)

            self._rows.append(row_f)


class RatingDisplay(ctk.CTkFrame):
    """
    Hero card — mirrors .rating-display / .rating-number style from the site.
    """
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=C_CARD, corner_radius=10,
                         border_width=1, border_color=C_BORDER, **kwargs)

        self._accent_bar = ctk.CTkFrame(self, width=4, corner_radius=0, fg_color=C_MUTED)
        self._accent_bar.pack(side="left", fill="y")

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(side="left", fill="both", expand=True, padx=20, pady=18)

        ctk.CTkLabel(
            inner, text="PROJECTED RATING",
            font=font_mono(9), text_color=C_ACCENT, anchor="w",
        ).pack(anchor="w")

        self._rating_lbl = ctk.CTkLabel(
            inner, text="—",
            font=font_serif(64), text_color=C_TEXT, anchor="w",
        )
        self._rating_lbl.pack(anchor="w", pady=(2, 2))

        self._change_lbl = ctk.CTkLabel(
            inner, text="Enter a PDGA number above to calculate",
            font=font_mono(12), text_color=C_MUTED, anchor="w",
        )
        self._change_lbl.pack(anchor="w")

        self._cutoff_lbl = ctk.CTkLabel(
            inner, text="",
            font=font_mono(10), text_color=C_MUTED, anchor="w",
        )
        self._cutoff_lbl.pack(anchor="w", pady=(6, 0))

    def update(self, projected: int, current: int, drop_below: float):
        change = projected - current
        color  = C_SUCCESS if change >= 0 else C_DANGER
        sign   = "+" if change >= 0 else ""
        self._accent_bar.configure(fg_color=color)
        self._rating_lbl.configure(text=str(projected))
        self._change_lbl.configure(
            text=f"{sign}{change} from current rating of {current}", text_color=color
        )
        self._cutoff_lbl.configure(text=f"Outlier cutoff: {int(drop_below)}")

    def reset(self):
        self._accent_bar.configure(fg_color=C_MUTED)
        self._rating_lbl.configure(text="—")
        self._change_lbl.configure(
            text="Enter a PDGA number above to calculate", text_color=C_MUTED
        )
        self._cutoff_lbl.configure(text="")


class WhatIfPanel(ctk.CTkFrame):
    """Compact what-if / target solver panel."""

    def __init__(self, master, on_change, **kwargs):
        super().__init__(master, fg_color=C_CARD, corner_radius=10,
                         border_width=1, border_color=C_BORDER, **kwargs)
        self._on_change       = on_change
        self._whatif_ratings: list[int]          = []
        self._row_frames:     list[ctk.CTkFrame] = []

        SectionLabel(self, "What-If Simulator").pack(fill="x", padx=16, pady=(14, 10))

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=16, pady=(0, 8))

        self._entry = ctk.CTkEntry(
            controls, placeholder_text="Round rating", width=130, height=30,
            font=font_mono(11), fg_color=C_BG2,
            border_color=C_BORDER, text_color=C_TEXT,
        )
        self._entry.pack(side="left", padx=(0, 6))
        self._entry.bind("<Return>", lambda e: self._add_round())

        ctk.CTkButton(
            controls, text="Add", width=60, height=30,
            font=font_mono(11, "bold"),
            fg_color=C_ACCENT, hover_color="#b8924a",
            text_color="#0E0E12", corner_radius=6, command=self._add_round,
        ).pack(side="left", padx=(0, 16))

        ctk.CTkFrame(controls, width=1, height=24, fg_color=C_BORDER).pack(side="left", padx=(0, 16))

        self._target_entry = ctk.CTkEntry(
            controls, placeholder_text="Target rating", width=110, height=30,
            font=font_mono(11), fg_color=C_BG2,
            border_color=C_BORDER, text_color=C_TEXT,
        )
        self._target_entry.pack(side="left", padx=(0, 6))

        self._rounds_entry = ctk.CTkEntry(
            controls, placeholder_text="# rds", width=56, height=30,
            font=font_mono(11), fg_color=C_BG2,
            border_color=C_BORDER, text_color=C_TEXT,
        )
        self._rounds_entry.pack(side="left", padx=(0, 6))
        self._rounds_entry.insert(0, "3")

        ctk.CTkButton(
            controls, text="Solve", width=66, height=30,
            font=font_mono(11, "bold"),
            fg_color=C_ACCENT2, hover_color="#5a7ab4",
            text_color="#0E0E12", corner_radius=6, command=self._solve_target,
        ).pack(side="left")

        self._target_lbl = ctk.CTkLabel(
            self, text="", font=font_mono(10),
            text_color=C_MUTED, anchor="w", wraplength=700,
        )
        self._target_lbl.pack(fill="x", padx=16, pady=(0, 6))

        ctk.CTkFrame(self, height=1, fg_color=C_BORDER).pack(fill="x", padx=16)

        self._list = ctk.CTkFrame(self, fg_color="transparent")
        self._list.pack(fill="x", padx=8, pady=(4, 10))

        self._empty_lbl = ctk.CTkLabel(
            self._list, text="No hypothetical rounds added yet.",
            font=font_mono(10), text_color=C_MUTED, anchor="w",
        )
        self._empty_lbl.pack(pady=8, padx=8, anchor="w")

    def _add_round(self):
        val = self._entry.get().strip()
        if not val.lstrip("-").isdigit():
            self._entry.configure(border_color=C_DANGER)
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
            self._empty_lbl.pack(pady=8, padx=8, anchor="w")
            return
        self._empty_lbl.pack_forget()

        for i, rating in enumerate(self._whatif_ratings):
            row = ctk.CTkFrame(self._list, fg_color="transparent", corner_radius=0)
            row.pack(fill="x", padx=8)
            if i > 0:
                ctk.CTkFrame(row, height=1, fg_color=C_BORDER).pack(fill="x")
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x")
            ctk.CTkLabel(
                inner, text=f"Rd {i+1}",
                font=font_mono(10), text_color=C_MUTED, width=44, anchor="w",
            ).pack(side="left", padx=(0, 8), pady=5)
            ctk.CTkLabel(
                inner, text=str(rating),
                font=font_mono(11, "bold"), text_color=C_TEXT,
            ).pack(side="left")
            idx = i
            ctk.CTkButton(
                inner, text="✕", width=22, height=20,
                font=font_mono(9),
                fg_color="transparent", hover_color="#3a1a1a", text_color=C_DANGER,
                command=lambda i=idx: self._remove_round(i),
            ).pack(side="right", padx=4, pady=4)
            self._row_frames.append(row)

    def _solve_target(self):
        t, r = self._target_entry.get().strip(), self._rounds_entry.get().strip()
        if not t.isdigit() or not r.isdigit():
            self._target_lbl.configure(
                text="Enter a valid target rating and number of rounds.",
                text_color=C_YELLOW,
            )
            return
        self._on_change(list(self._whatif_ratings), solve_target=int(t), solve_rounds=int(r))

    def set_target_result(self, msg: str, success: bool):
        self._target_lbl.configure(text=msg, text_color=C_SUCCESS if success else C_DANGER)

    def get_ratings(self) -> list[int]:
        return list(self._whatif_ratings)

    def reset(self):
        self._whatif_ratings.clear()
        self._rebuild()
        self._target_lbl.configure(text="", text_color=C_MUTED)


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("PDGA Ratings Calculator")
        self.geometry("1100x820")
        self.minsize(900, 680)
        self.configure(fg_color=C_BG)
        self._player_data: dict | None = None
        self._build_ui()

    def _build_ui(self):
        # Navbar
        topbar = ctk.CTkFrame(self, fg_color=C_BG2, corner_radius=0, height=56)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        ctk.CTkLabel(
            topbar, text="PDGA Ratings",
            font=font_serif(18), text_color=C_ACCENT,
        ).pack(side="left", padx=20)

        input_row = ctk.CTkFrame(topbar, fg_color="transparent")
        input_row.pack(side="right", padx=20)

        self._refresh_btn = ctk.CTkButton(
            input_row, text="↺ refresh", width=84, height=30,
            font=font_mono(10),
            fg_color="transparent", hover_color=C_BG,
            border_width=1, border_color=C_BORDER,
            text_color=C_MUTED, corner_radius=6,
            command=lambda: self._start_fetch(force_refresh=True),
        )
        self._refresh_btn.pack(side="right", padx=(6, 0))

        self._fetch_btn = ctk.CTkButton(
            input_row, text="calculate", width=100, height=30,
            font=font_mono(10, "bold"),
            fg_color=C_ACCENT, hover_color="#b8924a",
            text_color="#0E0E12", corner_radius=6,
            command=self._start_fetch,
        )
        self._fetch_btn.pack(side="right")

        self._pdga_entry = ctk.CTkEntry(
            input_row, placeholder_text="pdga number",
            width=150, height=30,
            font=font_mono(11),
            fg_color=C_BG, border_color=C_BORDER, text_color=C_TEXT,
            corner_radius=6,
        )
        self._pdga_entry.pack(side="right", padx=(0, 10))
        self._pdga_entry.bind("<Return>", lambda e: self._start_fetch())

        ctk.CTkFrame(self, height=1, fg_color=C_BORDER, corner_radius=0).pack(fill="x")

        # Status
        self._status = ctk.CTkLabel(
            self, text="Enter a PDGA number to get started.",
            font=font_mono(9), text_color=C_MUTED, anchor="w",
        )
        self._status.pack(fill="x", padx=20, pady=(8, 0))

        # Scrollable content
        content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=(10, 16))

        self._rating_disp  = RatingDisplay(content)
        self._rating_disp.pack(fill="x", pady=(0, 10))

        self._whatif = WhatIfPanel(content, on_change=self._on_whatif_change)
        self._whatif.pack(fill="x", pady=(0, 10))

        self._incoming_tbl = RoundsTable(content, "Rounds Coming In")
        self._incoming_tbl.pack(fill="x", pady=(0, 10))

        self._outgoing_tbl = RoundsTable(content, "Rounds Dropping Off")
        self._outgoing_tbl.pack(fill="x", pady=(0, 10))

        self._outlier_tbl = RoundsTable(content, "Outlier Rounds")
        self._outlier_tbl.pack(fill="x")

    def _start_fetch(self, force_refresh: bool = False):
        pdga = self._pdga_entry.get().strip()
        if not pdga:
            self._set_status("Please enter a PDGA number.", C_YELLOW)
            return
        self._fetch_btn.configure(state="disabled", text="loading…")
        self._refresh_btn.configure(state="disabled")
        self._player_data = None
        self._rating_disp.reset()
        self._whatif.reset()
        for t in [self._incoming_tbl, self._outgoing_tbl, self._outlier_tbl]:
            t.update_rows([])
        threading.Thread(
            target=self._fetch_worker, args=(pdga, force_refresh), daemon=True
        ).start()

    def _fetch_worker(self, pdga: str, force_refresh: bool):
        try:
            self._set_status("Fetching player data…")
            data = load_player_data(pdga, force_refresh=force_refresh)
            self.after(0, lambda d=data: self._on_fetch_done(d))
        except (FetchError, ParseError) as e:
            self.after(0, lambda e=e: self._set_status(f"Error: {e}", C_DANGER))
            self.after(0, self._reset_buttons)

    def _on_fetch_done(self, data: dict):
        self._player_data = data
        result = project_rating(data["tournaments"], data["new_tournaments"])
        self._render(result, data["current_rating"])
        self._set_status("Done.", C_SUCCESS)
        self._reset_buttons()

    def _reset_buttons(self):
        self._fetch_btn.configure(state="normal", text="calculate")
        self._refresh_btn.configure(state="normal")

    def _set_status(self, msg: str, color: str = C_MUTED):
        self._status.configure(text=msg, text_color=color)

    def _render(self, result: dict, current_rating: int):
        db = result["drop_below"]
        self._rating_disp.update(result["projected_rating"], current_rating, db)
        self._incoming_tbl.update_rows(result["incoming_rounds"], db)
        self._outgoing_tbl.update_rows(result["outgoing_rounds"], db)
        self._outlier_tbl.update_rows(result["outlier_rounds"],   db)

    def _on_whatif_change(
        self,
        whatif_ratings: list[int],
        solve_target:   int | None = None,
        solve_rounds:   int | None = None,
    ):
        if self._player_data is None:
            return
        tournaments    = self._player_data["tournaments"]
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
            self._set_status("Done.", C_SUCCESS)

        if solve_target is not None and solve_rounds is not None:
            try:
                tr = rounds_needed_for_target(
                    tournaments, new_tournaments, solve_target, solve_rounds
                )
                if tr["achievable"]:
                    self._whatif.set_target_result(
                        f"Need avg {tr['needed_avg']} × {solve_rounds} rd(s) → projected {tr['with_avg']}",
                        success=True,
                    )
                else:
                    self._whatif.set_target_result(tr["message"], success=False)
            except ValueError as e:
                self._whatif.set_target_result(str(e), success=False)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
