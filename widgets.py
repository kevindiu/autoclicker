import tkinter as tk
from theme import UITheme

# ==============================================================================
# 自訂組件：全深色模式變數表格 (VarTable)
# ==============================================================================
class VarTable(tk.Frame):
    def __init__(self, parent, bg=UITheme.BG_DARK, select_bg=UITheme.ACCENT_BLUE, on_double_click=None):
        super().__init__(parent, bg=bg)
        self.bg = bg
        self.select_bg = select_bg
        self.on_double_click = on_double_click
        self.selected_name = None
        self.rows = {}

        # 標題欄
        self.hdr = tk.Frame(self, bg=UITheme.BG_PANEL, pady=3, padx=4)
        self.hdr.pack(fill="x")
        tk.Label(self.hdr, text="變數名稱", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_SMALL_BOLD, width=12, anchor="w").pack(side="left", padx=2)
        tk.Label(self.hdr, text="種類", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_SMALL_BOLD, width=9, anchor="center").pack(side="left", padx=2)
        tk.Label(self.hdr, text="當前數值", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_SMALL_BOLD, anchor="w").pack(side="left", fill="x", expand=True, padx=2)

        # 內容滾動區
        f_box = tk.Frame(self, bg=bg)
        f_box.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(f_box, bg=bg, bd=0, highlightthickness=0, height=60)
        self.scrollbar = tk.Scrollbar(f_box, orient="vertical", command=self.canvas.yview)
        self.body_frame = tk.Frame(self.canvas, bg=bg)

        self.body_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.body_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))

        self.bind_mousewheel(self)
        self.bind_mousewheel(self.canvas)
        self.bind_mousewheel(self.body_frame)

    def bind_mousewheel(self, widget):
        widget.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units") if e.delta else None, add="+")
        widget.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"), add="+")
        widget.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"), add="+")

    def get_children(self):
        return list(self.rows.keys())

    def delete(self, item):
        if item in self.rows:
            self.rows[item]['frame'].destroy()
            del self.rows[item]
            if self.selected_name == item:
                self.selected_name = None

    def insert(self, parent, index, iid=None, values=()):
        name, t_disp, v_str = values
        rf = tk.Frame(self.body_frame, bg=self.bg, pady=2, padx=4)
        rf.pack(fill="x", expand=True)

        l1 = tk.Label(rf, text=name, bg=self.bg, fg=UITheme.TEXT_MAIN, font=UITheme.FONT_NORMAL, width=12, anchor="w")
        l1.pack(side="left", padx=2)
        l2 = tk.Label(rf, text=t_disp, bg=self.bg, fg=UITheme.CYAN_SUB, font=UITheme.FONT_SMALL_BOLD, width=9, anchor="center")
        l2.pack(side="left", padx=2)
        l3 = tk.Label(rf, text=v_str, bg=self.bg, fg="#e5e7eb", font=UITheme.FONT_NORMAL, anchor="w")
        l3.pack(side="left", fill="x", expand=True, padx=2)

        for w in (rf, l1, l2, l3):
            w.bind("<Button-1>", lambda e, n=iid: self._select(n))
            w.bind("<Double-Button-1>", lambda e, n=iid: self._on_dbl(n))
            self.bind_mousewheel(w)

        self.rows[iid] = {'frame': rf, 'l1': l1, 'l2': l2, 'l3': l3}

    def _select(self, name):
        if self.selected_name in self.rows:
            old = self.rows[self.selected_name]
            for w in (old['frame'], old['l1'], old['l2'], old['l3']):
                w.config(bg=self.bg)
        self.selected_name = name
        if name in self.rows:
            curr = self.rows[name]
            for w in (curr['frame'], curr['l1'], curr['l2'], curr['l3']):
                w.config(bg=self.select_bg)

    def _on_dbl(self, name):
        self._select(name)
        if self.on_double_click:
            self.on_double_click()

    def selection(self):
        return (self.selected_name,) if self.selected_name else ()
