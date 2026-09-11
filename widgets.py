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

        self.canvas = tk.Canvas(f_box, bg=bg, bd=0, highlightthickness=0, height=82)
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


# ==============================================================================
# 自訂組件：全深色模式定時週期任務卡片列表 (PeriodicTaskCardView)
# ==============================================================================
class PeriodicTaskCardView(tk.Frame):
    def __init__(self, parent, bg=UITheme.BG_DARK, select_bg="#1e3a5f", on_double_click=None, on_toggle=None):
        super().__init__(parent, bg=bg)
        self.bg = bg
        self.select_bg = select_bg
        self.on_double_click = on_double_click
        self.on_toggle = on_toggle
        self.selected_idx = None
        self.tasks = []
        self.card_widgets = []
        self._current_width = 240
        self.empty_label = None

        # 滾動容器
        self.canvas = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body_frame = tk.Frame(self.canvas, bg=bg)

        self.canvas_window = self.canvas.create_window((0, 0), window=self.body_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.body_frame.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.bind_mousewheel(self)
        self.bind_mousewheel(self.canvas)
        self.bind_mousewheel(self.body_frame)
        self._check_empty_state()

    def bind_mousewheel(self, widget):
        widget.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units") if e.delta else None, add="+")
        widget.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"), add="+")
        widget.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"), add="+")

    def _on_body_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._current_width = event.width
        self.canvas.itemconfig(self.canvas_window, width=event.width)
        self._update_all_wraplengths(event.width)

    def _update_all_wraplengths(self, width):
        # 保留卡片 padding (7*2=14)、滾動條 (~16) 與外邊距，精確計算文字折行寬度
        wrap_w = max(100, width - 32)
        for card_info in self.card_widgets:
            for lbl in card_info.get("wrap_labels", []):
                try:
                    lbl.config(wraplength=wrap_w)
                except Exception:
                    pass

    def _check_empty_state(self):
        if len(self.tasks) == 0:
            if not self.empty_label:
                self.empty_label = tk.Label(
                    self.body_frame,
                    text="⏱ 尚無定時任務\n\n點擊下方 [+ 新增] 建立週期任務\n(長名稱自動換行顯示)",
                    bg=self.bg,
                    fg="#64748b",
                    font=UITheme.FONT_SMALL,
                    justify="center"
                )
                self.empty_label.pack(expand=True, fill="both", pady=30)
                self.bind_mousewheel(self.empty_label)
        else:
            if self.empty_label:
                try:
                    self.empty_label.destroy()
                except Exception:
                    pass
                self.empty_label = None

    def delete(self, first=0, last=None):
        for card_info in self.card_widgets:
            try:
                card_info["frame"].destroy()
            except Exception:
                pass
        self.card_widgets.clear()
        self.tasks.clear()
        self.selected_idx = None
        self._check_empty_state()
        self.canvas.configure(scrollregion=(0, 0, 0, 0))

    def insert(self, index, item):
        if isinstance(item, dict):
            task = item
        else:
            task = {"name": str(item), "enabled": True, "interval": 1.0, "action": {}}

        self.tasks.append(task)
        idx = len(self.tasks) - 1
        self._check_empty_state()
        self._create_card(idx, task)

    def _create_card(self, idx, task):
        enabled = task.get("enabled", True)
        interval = task.get("interval", 1.0)
        try:
            f_sec = float(interval)
            sec_str = f"{int(f_sec)}s" if f_sec.is_integer() else f"{f_sec}s"
        except Exception:
            sec_str = f"{interval}s"

        name = task.get("name", "").strip()
        run_on_start = task.get("run_on_start", False)
        act = task.get("action", {})

        # 格式化動作描述
        var_name = act.get("var_name")
        atype = act.get("type", "")
        if var_name:
            act_text = f"↳ 變數:【{var_name}】"
        elif atype == "call_combo":
            act_text = f"↳ 組合:【{act.get('target_name', '')}】"
        elif atype == "key":
            act_text = f"↳ 按鍵: [ {str(act.get('key', '')).upper()} ]"
        elif atype == "click":
            btn_tag = "右鍵" if act.get("btn") == "right" else "左鍵"
            prefix = "相對" if act.get("rel") else "絕對"
            act_text = f"↳ 點擊: {btn_tag}·{prefix}({act.get('x', 0)}, {act.get('y', 0)})"
        elif atype == "wait":
            act_text = f"↳ 停頓: {act.get('sec', 0)} 秒"
        elif atype:
            act_text = f"↳ 動作: [{atype}]"
        else:
            act_text = ""

        # 配色方案
        card_bg = "#1e222b" if enabled else "#17191f"
        border_col = "#2d3544" if enabled else "#23262d"
        wrap_w = max(100, self._current_width - 32)

        # 外層卡片面板
        card = tk.Frame(
            self.body_frame,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=border_col,
            padx=7,
            pady=5
        )
        card.pack(fill="x", expand=True, padx=3, pady=2)

        # 頂部狀態列 (Badges + 序號)
        hdr = tk.Frame(card, bg=card_bg)
        hdr.pack(fill="x", anchor="w")

        # 狀態標籤 (點擊可直接切換開關狀態)
        if enabled:
            st_text = "✓ 啟用"
            st_bg = "#14532d"
            st_fg = "#4ade80"
        else:
            st_text = "✕ 停用"
            st_bg = "#334155"
            st_fg = "#94a3b8"

        lbl_status = tk.Label(
            hdr,
            text=st_text,
            bg=st_bg,
            fg=st_fg,
            font=UITheme.FONT_SMALL_BOLD,
            padx=5,
            pady=1,
            cursor="hand2"
        )
        lbl_status.pack(side="left", padx=(0, 4))
        lbl_status.bind("<Button-1>", lambda e, i=idx: self._on_toggle_click(i))

        # 週期秒數標籤
        lbl_int = tk.Label(
            hdr,
            text=f"⏱ {sec_str}",
            bg="#0c4a6e",
            fg="#38bdf8",
            font=UITheme.FONT_SMALL_BOLD,
            padx=5,
            pady=1
        )
        lbl_int.pack(side="left", padx=(0, 4))

        # 首發標籤
        lbl_start = None
        if run_on_start:
            lbl_start = tk.Label(
                hdr,
                text="⚡ 首發",
                bg="#3b0764",
                fg="#c084fc",
                font=UITheme.FONT_SMALL_BOLD,
                padx=5,
                pady=1
            )
            lbl_start.pack(side="left", padx=(0, 4))

        # 序號標籤 (靠右)
        lbl_idx = tk.Label(
            hdr,
            text=f"#{idx+1}",
            bg=card_bg,
            fg="#64748b",
            font=UITheme.FONT_SMALL
        )
        lbl_idx.pack(side="right")

        # 任務名稱主標題 (支援超出一行自動換行 wraplength)
        title_text = name if name else (act_text.replace("↳ ", "") if act_text else "定時任務")
        lbl_title = tk.Label(
            card,
            text=title_text,
            bg=card_bg,
            fg="#f8fafc" if enabled else "#64748b",
            font=UITheme.FONT_NORMAL_BOLD,
            anchor="w",
            justify="left",
            wraplength=wrap_w
        )
        lbl_title.pack(fill="x", expand=True, pady=(3, 1), anchor="w")

        # 動作詳細副標題 (支援超出一行自動換行 wraplength)
        lbl_act = None
        if name and act_text:
            lbl_act = tk.Label(
                card,
                text=act_text,
                bg=card_bg,
                fg="#7dd3fc" if enabled else "#475569",
                font=UITheme.FONT_SMALL,
                anchor="w",
                justify="left",
                wraplength=wrap_w
            )
            lbl_act.pack(fill="x", expand=True, pady=(0, 1), anchor="w")

        # 統整事件交互組件
        interactive_widgets = [card, hdr, lbl_int, lbl_idx, lbl_title]
        if lbl_start:
            interactive_widgets.append(lbl_start)
        if lbl_act:
            interactive_widgets.append(lbl_act)

        wrap_labels = [lbl_title]
        if lbl_act:
            wrap_labels.append(lbl_act)

        card_data = {
            "index": idx,
            "frame": card,
            "hdr": hdr,
            "lbl_status": lbl_status,
            "lbl_int": lbl_int,
            "lbl_start": lbl_start,
            "lbl_idx": lbl_idx,
            "lbl_title": lbl_title,
            "lbl_act": lbl_act,
            "wrap_labels": wrap_labels,
            "interactive_widgets": interactive_widgets,
            "normal_bg": card_bg,
            "normal_border": border_col,
            "enabled": enabled
        }

        # 綁定選取、雙擊與微互動懸停高亮
        for w in interactive_widgets:
            w.bind("<Button-1>", lambda e, i=idx: self.select(i))
            w.bind("<Double-Button-1>", lambda e, i=idx: self._on_dbl_click(i))
            w.bind("<Enter>", lambda e, i=idx: self._on_card_hover(i, True))
            w.bind("<Leave>", lambda e, i=idx: self._on_card_hover(i, False))
            self.bind_mousewheel(w)

        self.bind_mousewheel(lbl_status)
        self.card_widgets.append(card_data)

    def _on_card_hover(self, idx, entering):
        if self.selected_idx == idx:
            return
        if 0 <= idx < len(self.card_widgets):
            card_info = self.card_widgets[idx]
            target_bg = "#232834" if entering else card_info["normal_bg"]
            target_border = "#3a4454" if entering else card_info["normal_border"]
            card_info["frame"].config(bg=target_bg, highlightbackground=target_border)
            card_info["hdr"].config(bg=target_bg)
            card_info["lbl_idx"].config(bg=target_bg)
            card_info["lbl_title"].config(bg=target_bg)
            if card_info["lbl_act"]:
                card_info["lbl_act"].config(bg=target_bg)

    def _on_toggle_click(self, idx):
        self.select(idx)
        if self.on_toggle:
            self.on_toggle()

    def _on_dbl_click(self, idx):
        self.select(idx)
        if self.on_double_click:
            self.on_double_click()

    def select(self, idx):
        if not (0 <= idx < len(self.card_widgets)):
            return
        if self.selected_idx is not None and 0 <= self.selected_idx < len(self.card_widgets):
            old = self.card_widgets[self.selected_idx]
            self._apply_card_style(old, is_selected=False)

        self.selected_idx = idx
        curr = self.card_widgets[idx]
        self._apply_card_style(curr, is_selected=True)

    def _apply_card_style(self, card_info, is_selected):
        bg = self.select_bg if is_selected else card_info["normal_bg"]
        border = "#38bdf8" if is_selected else card_info["normal_border"]
        hl_thick = 2 if is_selected else 1

        card_info["frame"].config(bg=bg, highlightbackground=border, highlightthickness=hl_thick)
        card_info["hdr"].config(bg=bg)
        card_info["lbl_idx"].config(bg=bg)
        card_info["lbl_title"].config(bg=bg)
        if card_info["lbl_act"]:
            card_info["lbl_act"].config(bg=bg)

    def curselection(self):
        return (self.selected_idx,) if self.selected_idx is not None else ()

    def selection_set(self, idx):
        self.select(idx)

    def see(self, idx):
        if not (0 <= idx < len(self.card_widgets)):
            return
        total = len(self.card_widgets)
        if total > 0:
            frac = max(0.0, min(1.0, idx / float(total)))
            self.canvas.yview_moveto(frac)

    def size(self):
        return len(self.tasks)

    def get(self, idx):
        if 0 <= idx < len(self.tasks):
            t = self.tasks[idx]
            if isinstance(t, dict):
                import state
                return state.format_periodic_task_summary(t)
            return str(t)
        return ""

    def bind(self, sequence, func, add=None):
        if sequence == "<Double-Button-1>":
            self.on_double_click = func
        else:
            super().bind(sequence, func, add=add)

    def config(self, **kwargs):
        # 兼容 Listbox 外部傳入之 yscrollcommand 或其他屬性
        kwargs.pop("yscrollcommand", None)
        if kwargs:
            super().config(**kwargs)

    def yview(self, *args):
        return self.canvas.yview(*args)

