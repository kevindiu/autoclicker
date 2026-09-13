import tkinter as tk
from tkinter import ttk
from theme import UITheme
from widgets import VarTable, PeriodicTaskCardView

# ==============================================================================
# UI 左欄面板 (LeftPanel)
# 包含：設定檔管理、視窗綁定、常用變數庫 (VarTable)、技能組合庫 (Combos)
# ==============================================================================
class LeftPanel(tk.Frame):
    def __init__(self, parent, app, **kwargs):
        super().__init__(
            parent,
            bg=UITheme.BG_PANEL,
            padx=8,
            pady=8,
            highlightbackground=UITheme.BORDER,
            highlightthickness=1,
            **kwargs
        )
        self.app = app
        self._build_ui()
        self.export_widgets_to_app(app)

    def _build_ui(self):
        app = self.app

        # 1. 設定與視窗綁定
        f_cfg = tk.LabelFrame(
            self,
            text=" 設定與視窗綁定 ",
            bg=UITheme.BG_PANEL,
            fg=UITheme.CYAN_TITLE,
            font=UITheme.FONT_TITLE,
            padx=6,
            pady=4
        )
        f_cfg.pack(fill="x", pady=(0, 4))

        # 第 1 行: 設定檔管理 + 核心功能勾選 (背景掛機、相對坐標、視窗置頂)
        r1 = tk.Frame(f_cfg, bg=UITheme.BG_PANEL)
        r1.pack(fill="x", pady=(1, 2))
        tk.Label(r1, text="設定檔:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left")
        self.cbo_profile = ttk.Combobox(r1, textvariable=app.var_profile_name, width=14, state="readonly")
        self.cbo_profile.pack(side="left", padx=(3, 3))
        tk.Button(r1, text="載入", width=4, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.load_config).pack(side="left", padx=1)
        tk.Button(r1, text="儲存", width=4, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.save_config).pack(side="left", padx=1)
        tk.Button(r1, text="+ 新增", width=5, bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.create_new_profile).pack(side="left", padx=(1, 8))

        tk.Checkbutton(r1, text="背景掛機", variable=app.var_use_bg, bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, selectcolor=UITheme.BG_PANEL, activebackground=UITheme.BG_PANEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=2)
        tk.Checkbutton(r1, text="相對坐標", variable=app.var_use_rel, bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, selectcolor=UITheme.BG_PANEL, activebackground=UITheme.BG_PANEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=2)
        tk.Checkbutton(r1, text="視窗置頂", variable=app.var_topmost, command=app.toggle_topmost, bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, selectcolor=UITheme.BG_PANEL, activebackground=UITheme.BG_PANEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=2)

        # 第 2 行: 目標視窗綁定 + 重新整理/定位 + 偏差校正 X/Y
        r2 = tk.Frame(f_cfg, bg=UITheme.BG_PANEL)
        r2.pack(fill="x", pady=(2, 1))
        tk.Label(r2, text="目標視窗:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left")
        self.cbo_window = ttk.Combobox(r2, textvariable=app.var_window, width=16, state="readonly")
        self.cbo_window.pack(side="left", padx=(3, 3), fill="x", expand=True)
        self.cbo_window.bind("<<ComboboxSelected>>", app.on_window_select)
        tk.Button(r2, text="↻ 重新整理", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, padx=4, command=app.refresh_window_dropdown).pack(side="left", padx=1)
        tk.Button(r2, text="◎ 定位視窗", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, padx=4, command=app.locate_target_window).pack(side="left", padx=(1, 8))

        tk.Label(r2, text="偏差校正:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left")
        tk.Label(r2, text="X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_NORMAL).pack(side="left", padx=(3, 1))
        tk.Entry(r2, textvariable=app.var_offset_x, width=3, bg=UITheme.BG_INPUT, fg="#ffffff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)
        tk.Label(r2, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_NORMAL).pack(side="left", padx=(3, 1))
        tk.Entry(r2, textvariable=app.var_offset_y, width=3, bg=UITheme.BG_INPUT, fg="#ffffff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)

        # 垂直 PanedWindow 將「常用變數庫」與「技能組合庫」連接
        pw_left = tk.PanedWindow(
            self,
            orient="vertical",
            bg=UITheme.BORDER,
            bd=0,
            sashwidth=5,
            sashrelief="flat",
            sashpad=1,
            opaqueresize=True
        )
        pw_left.pack(fill="both", expand=True)

        # 2. 常用變數庫
        f_vars = tk.LabelFrame(
            pw_left,
            text=" 常用變數庫 ",
            bg=UITheme.BG_PANEL,
            fg=UITheme.CYAN_TITLE,
            font=UITheme.FONT_TITLE,
            padx=6,
            pady=3
        )

        f_vars_row = tk.Frame(f_vars, bg=UITheme.BG_PANEL)
        f_vars_row.pack(fill="both", expand=True)

        self.tree_vars = VarTable(f_vars_row, on_double_click=app.edit_selected_variable)
        self.tree_vars.pack(side="left", fill="both", expand=True, padx=(0, 6))

        col_v_btns = tk.Frame(f_vars_row, bg=UITheme.BG_PANEL)
        col_v_btns.pack(side="right", anchor="n")
        col_v_btns.grid_columnconfigure(0, weight=1)
        col_v_btns.grid_columnconfigure(1, weight=1)
        col_v_btns.grid_rowconfigure(0, weight=1)
        col_v_btns.grid_rowconfigure(1, weight=1)
        col_v_btns.grid_rowconfigure(2, weight=1)

        btn_var_add_main = tk.Button(
            col_v_btns,
            text="➔ 加入掛機流程",
            bg=UITheme.ACCENT_BLUE,
            fg="#fff",
            activebackground=UITheme.ACCENT_BLUE_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=3,
            pady=1,
            command=app.add_variable_to_main_steps
        )
        btn_var_add_main.grid(row=0, column=0, padx=1, pady=1, sticky="nsew")

        tk.Button(
            col_v_btns,
            text="+ 新增變數",
            bg=UITheme.ACCENT_GREEN,
            fg="#fff",
            activebackground=UITheme.ACCENT_GREEN_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=3,
            pady=1,
            command=app.add_variable_dialog
        ).grid(row=0, column=1, padx=1, pady=1, sticky="nsew")

        tk.Button(
            col_v_btns,
            text="✎ 修改變數",
            bg=UITheme.ACCENT_BLUE,
            fg="#fff",
            activebackground=UITheme.ACCENT_BLUE_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=3,
            pady=1,
            command=app.edit_selected_variable
        ).grid(row=1, column=0, padx=1, pady=1, sticky="nsew")

        tk.Button(
            col_v_btns,
            text="✕ 刪除變數",
            bg=UITheme.ACCENT_RED,
            fg="#fff",
            activebackground=UITheme.ACCENT_RED_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=3,
            pady=1,
            command=app.delete_selected_variable
        ).grid(row=1, column=1, padx=1, pady=1, sticky="nsew")

        tk.Button(
            col_v_btns,
            text="▲ 上移",
            bg=UITheme.BTN_GRAY,
            fg="#fff",
            activebackground=UITheme.BTN_GRAY_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=3,
            pady=1,
            command=lambda: app.move_variable(-1)
        ).grid(row=2, column=0, padx=1, pady=1, sticky="nsew")

        tk.Button(
            col_v_btns,
            text="▼ 下移",
            bg=UITheme.BTN_GRAY,
            fg="#fff",
            activebackground=UITheme.BTN_GRAY_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=3,
            pady=1,
            command=lambda: app.move_variable(1)
        ).grid(row=2, column=1, padx=1, pady=1, sticky="nsew")

        # 3. 技能組合區塊
        f_combo = tk.LabelFrame(
            pw_left,
            text=" 技能組合庫 ",
            bg=UITheme.BG_PANEL,
            fg=UITheme.CYAN_TITLE,
            font=UITheme.FONT_TITLE,
            padx=6,
            pady=4
        )

        pw_left.add(f_vars, minsize=85, height=155)
        pw_left.add(f_combo, minsize=130)

        f_combo_split = tk.Frame(f_combo, bg=UITheme.BG_PANEL)
        f_combo_split.pack(fill="both", expand=True)
        f_combo_split.grid_columnconfigure(0, weight=3)
        f_combo_split.grid_columnconfigure(1, weight=8)
        f_combo_split.grid_rowconfigure(0, weight=1)

        # 2-A. 組合清單 (支援雙擊加入掛機流程)
        f_cl = tk.Frame(f_combo_split, bg=UITheme.BG_PANEL, padx=4, pady=2)
        f_cl.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        tk.Label(f_cl, text="【組合清單】", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_NORMAL_BOLD).pack(anchor="w")

        tk.Entry(f_cl, textvariable=app.var_combo_name, bg=UITheme.BG_INPUT, fg="#fff", font=UITheme.FONT_NORMAL, relief="flat").pack(fill="x", pady=(2, 2))

        cr_btns = tk.Frame(f_cl, bg=UITheme.BG_PANEL)
        cr_btns.pack(fill="x", pady=(0, 2))
        tk.Button(cr_btns, text="+ 新增", bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=1, command=app.add_new_combo).pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(cr_btns, text="✎ 改名", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=1, command=app.rename_selected_combo).pack(side="left", fill="x", expand=True, padx=1)
        tk.Button(cr_btns, text="⎘ 複製", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=1, command=app.duplicate_selected_combo).pack(side="left", fill="x", expand=True, padx=(1, 0))

        cr_act = tk.Frame(f_cl, bg=UITheme.BG_PANEL)
        cr_act.pack(side="bottom", fill="x", pady=(1, 0))
        tk.Button(cr_act, text="➔ 加入掛機流程", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, font=UITheme.FONT_SMALL_BOLD, pady=1, command=app.add_combo_to_main_steps).pack(side="left", fill="x", expand=True, padx=(0, 2))
        tk.Button(cr_act, text="✕ 刪除", bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, font=UITheme.FONT_SMALL_BOLD, pady=1, command=app.delete_selected_combo).pack(side="right")

        cr_order = tk.Frame(f_cl, bg=UITheme.BG_PANEL)
        cr_order.pack(side="bottom", fill="x", pady=(1, 1))
        tk.Button(cr_order, text="▲ 上移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=1, command=lambda: app.move_combo(-1)).pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(cr_order, text="▼ 下移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=1, command=lambda: app.move_combo(1)).pack(side="left", fill="x", expand=True, padx=(1, 0))

        f_cl_box = tk.Frame(f_cl, bg=UITheme.BG_DARK)
        f_cl_box.pack(side="top", fill="both", expand=True, pady=2)
        self.combo_listbox = tk.Listbox(
            f_cl_box,
            height=4,
            bg=UITheme.BG_DARK,
            fg=UITheme.TEXT_MAIN,
            selectbackground=UITheme.ACCENT_BLUE,
            selectforeground="#fff",
            bd=0,
            highlightthickness=0,
            font=UITheme.FONT_NORMAL,
            exportselection=False
        )
        self.combo_listbox.pack(side="left", fill="both", expand=True)
        self.combo_listbox.bind("<<ListboxSelect>>", app.on_combo_select)
        self.combo_listbox.bind("<Double-Button-1>", app.on_combo_double_click_add)
        sc_cl = tk.Scrollbar(f_cl_box, orient="vertical", command=self.combo_listbox.yview)
        sc_cl.pack(side="right", fill="y")
        self.combo_listbox.config(yscrollcommand=sc_cl.set)

        # 2-B. 組合動作
        f_cr = tk.Frame(f_combo_split, bg=UITheme.BG_PANEL, padx=6, pady=2, highlightbackground=UITheme.BORDER, highlightthickness=1)
        f_cr.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        f_cr_top = tk.Frame(f_cr, bg=UITheme.BG_PANEL)
        f_cr_top.pack(fill="x", pady=(0, 2))
        self.lbl_combo_editing = tk.Label(f_cr_top, text="【組合動作: 未選取】", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_SUB, font=UITheme.FONT_NORMAL_BOLD)
        self.lbl_combo_editing.pack(side="left")
        tk.Button(f_cr_top, text="▶ 試跑組合", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, font=UITheme.FONT_SMALL_BOLD, relief="flat", padx=6, command=app.test_run_current_combo).pack(side="right")

        # 動作建立面板
        f_action_card = tk.LabelFrame(f_cr, text=" 加入動作 ", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL_BOLD, padx=5, pady=2)
        f_action_card.pack(fill="x", pady=(0, 2))

        # 1. 點擊動作行
        r_click = tk.Frame(f_action_card, bg=UITheme.BG_PANEL)
        r_click.pack(fill="x", pady=1)
        ttk.Combobox(r_click, textvariable=app.var_combo_btn, values=["左鍵", "右鍵"], width=4, state="readonly").pack(side="left", padx=(0, 2))
        btn_combo_add_click = tk.Button(r_click, text="+ 瞄準取點", bg=UITheme.ACCENT_GREEN, fg="#fff", font=UITheme.FONT_NORMAL_BOLD, activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", padx=6, command=lambda: app.add_click_action(is_combo=True))
        btn_combo_add_click.pack(side="left", padx=1, fill="x", expand=True)

        tk.Label(r_click, text="X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(side="left", padx=(3, 1))
        tk.Entry(r_click, textvariable=app.var_combo_manual_x, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)
        tk.Label(r_click, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(side="left", padx=(1, 1))
        tk.Entry(r_click, textvariable=app.var_combo_manual_y, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)
        tk.Button(r_click, text="+ 手動", width=5, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: app.add_manual_click(is_combo=True)).pack(side="left", padx=(2, 0))

        # 2. 按鍵與等待行
        r_fast = tk.Frame(f_action_card, bg=UITheme.BG_PANEL)
        r_fast.pack(fill="x", pady=1)

        f_k = tk.Frame(r_fast, bg=UITheme.BG_PANEL)
        f_k.pack(side="left", fill="x", expand=True, padx=(0, 2))
        tk.Entry(f_k, textvariable=app.var_combo_act_key, width=5, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 2))
        tk.Button(f_k, text="+ 按鍵", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, font=UITheme.FONT_SMALL_BOLD, command=lambda: app.add_key_action(is_combo=True)).pack(side="left", fill="x", expand=True)

        f_w = tk.Frame(r_fast, bg=UITheme.BG_PANEL)
        f_w.pack(side="left", fill="x", expand=True, padx=(2, 0))
        tk.Entry(f_w, textvariable=app.var_combo_act_wait, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 2))
        tk.Button(f_w, text="+ 停頓(s)", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, font=UITheme.FONT_SMALL_BOLD, command=lambda: app.add_wait_action(is_combo=True)).pack(side="left", fill="x", expand=True)

        # 3. 呼叫組合與引用變數
        r_comb = tk.Frame(f_action_card, bg=UITheme.BG_PANEL)
        r_comb.pack(fill="x", pady=1)

        f_call = tk.Frame(r_comb, bg=UITheme.BG_PANEL)
        f_call.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.cbo_call_combo = ttk.Combobox(f_call, textvariable=app.var_combo_to_call, width=10, state="readonly")
        self.cbo_call_combo.pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(f_call, text="+ 呼叫組合", width=7, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.combo_add_call_action).pack(side="left")

        f_var = tk.Frame(r_comb, bg=UITheme.BG_PANEL)
        f_var.pack(side="left", fill="x", expand=True, padx=(2, 0))
        self.cbo_combo_add_var = ttk.Combobox(f_var, textvariable=app.var_combo_ref_var, width=10, state="readonly")
        self.cbo_combo_add_var.pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(f_var, text="+ 引用變數", width=8, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.combo_add_variable_action).pack(side="left")

        # 底部管理工具列
        cr_act_ctrl = tk.Frame(f_cr, bg=UITheme.BG_PANEL)
        cr_act_ctrl.pack(side="bottom", fill="x", pady=(2, 1))
        cr_act_ctrl.grid_columnconfigure(0, weight=1)
        cr_act_ctrl.grid_columnconfigure(1, weight=1)
        cr_act_ctrl.grid_columnconfigure(2, weight=1)

        tk.Button(cr_act_ctrl, text="▲ 上移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: app.move_combo_action(-1)).grid(row=0, column=0, padx=1, pady=1, sticky="nsew")
        tk.Button(cr_act_ctrl, text="▼ 下移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: app.move_combo_action(1)).grid(row=0, column=1, padx=1, pady=1, sticky="nsew")
        tk.Button(cr_act_ctrl, text="▶ 試跑", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.test_run_selected_combo_action).grid(row=0, column=2, padx=1, pady=1, sticky="nsew")

        tk.Button(cr_act_ctrl, text="✎ 修改", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.edit_selected_combo_action).grid(row=1, column=0, padx=1, pady=1, sticky="nsew")
        tk.Button(cr_act_ctrl, text="⎘ 複製", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.duplicate_combo_action).grid(row=1, column=1, padx=1, pady=1, sticky="nsew")
        tk.Button(cr_act_ctrl, text="✕ 刪除", bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.delete_combo_action).grid(row=1, column=2, padx=1, pady=1, sticky="nsew")

        # 動作清單
        f_cr_box = tk.Frame(f_cr, bg=UITheme.BG_DARK)
        f_cr_box.pack(side="top", fill="both", expand=True, pady=(1, 2))

        self.combo_act_listbox = tk.Listbox(
            f_cr_box,
            height=4,
            bg=UITheme.BG_DARK,
            fg=UITheme.TEXT_MAIN,
            selectbackground=UITheme.ACCENT_BLUE,
            selectforeground="#fff",
            bd=0,
            highlightthickness=0,
            font=UITheme.FONT_NORMAL,
            exportselection=False
        )
        self.combo_act_listbox.pack(side="left", fill="both", expand=True)

        def _on_combo_act_click(event):
            idx = self.combo_act_listbox.nearest(event.y)
            bbox = self.combo_act_listbox.bbox(idx)
            if not bbox or event.y > (bbox[1] + bbox[3]):
                self.combo_act_listbox.selection_clear(0, tk.END)
                return "break"

        self.combo_act_listbox.bind("<Button-1>", _on_combo_act_click)
        self.combo_act_listbox.bind("<Double-Button-1>", lambda e: app.edit_selected_combo_action())
        f_cr_box.bind("<Button-1>", lambda e: self.combo_act_listbox.selection_clear(0, tk.END))
        sc_cr = tk.Scrollbar(f_cr_box, orient="vertical", command=self.combo_act_listbox.yview)
        sc_cr.pack(side="right", fill="y")
        self.combo_act_listbox.config(yscrollcommand=sc_cr.set)

    def get_widgets(self):
        """明確定義左欄面板所管理的公開 UI 控制項字典"""
        return {
            "cbo_profile": getattr(self, "cbo_profile", None),
            "cbo_window": getattr(self, "cbo_window", None),
            "tree_vars": getattr(self, "tree_vars", None),
            "combo_listbox": getattr(self, "combo_listbox", None),
            "lbl_combo_editing": getattr(self, "lbl_combo_editing", None),
            "cbo_call_combo": getattr(self, "cbo_call_combo", None),
            "cbo_combo_add_var": getattr(self, "cbo_combo_add_var", None),
            "combo_act_listbox": getattr(self, "combo_act_listbox", None),
        }

    def export_widgets_to_app(self, app):
        """統一把面板子組件引用寫回 app，讓跨組件依賴關係清晰、可追蹤"""
        if app is None:
            return
        for name, widget in self.get_widgets().items():
            if widget is not None:
                setattr(app, name, widget)

    # ======================= 公開組件存取 API =======================
    def get_tree_vars(self):
        return self.tree_vars

    def get_cbo_profile(self):
        return self.cbo_profile

    def get_cbo_window(self):
        return self.cbo_window

    def get_combo_listbox(self):
        return self.combo_listbox

    def get_combo_act_listbox(self):
        return self.combo_act_listbox


# ==============================================================================
# UI 右欄面板 (RightPanel)
# 包含：單一動作新增、掛機流程清單、定時週期任務卡片視圖、執行日誌、啟動與狀態列
# ==============================================================================
class RightPanel(tk.Frame):
    def __init__(self, parent, app, **kwargs):
        super().__init__(
            parent,
            bg=UITheme.BG_PANEL,
            padx=8,
            pady=8,
            highlightbackground=UITheme.BORDER,
            highlightthickness=1,
            **kwargs
        )
        self.app = app
        self._build_ui()
        self.export_widgets_to_app(app)

    def _build_ui(self):
        app = self.app

        # 1. 單一動作新增
        f_step = tk.LabelFrame(
            self,
            text=" 單一動作 ",
            bg=UITheme.BG_PANEL,
            fg=UITheme.CYAN_TITLE,
            font=UITheme.FONT_TITLE,
            padx=6,
            pady=3
        )
        f_step.pack(fill="x", pady=(0, 4))

        sr_click = tk.Frame(f_step, bg=UITheme.BG_PANEL)
        sr_click.pack(fill="x", pady=1)
        ttk.Combobox(sr_click, textvariable=app.var_step_btn, values=["左鍵", "右鍵"], width=4, state="readonly").pack(side="left", padx=(0, 2))
        btn_step_click = tk.Button(sr_click, text="+ 瞄準取點", bg=UITheme.ACCENT_GREEN, fg="#fff", font=UITheme.FONT_NORMAL_BOLD, activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", padx=6, command=lambda: app.add_click_action(is_combo=False))
        btn_step_click.pack(side="left", padx=1, fill="x", expand=True)
        tk.Label(sr_click, text="X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(side="left", padx=(4, 1))
        tk.Entry(sr_click, textvariable=app.var_step_manual_x, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)
        tk.Label(sr_click, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(side="left", padx=(1, 1))
        tk.Entry(sr_click, textvariable=app.var_step_manual_y, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=1)
        tk.Button(sr_click, text="+ 手動", width=5, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: app.add_manual_click(is_combo=False)).pack(side="left", padx=(2, 0))

        sr = tk.Frame(f_step, bg=UITheme.BG_PANEL)
        sr.pack(fill="x", pady=1)
        f_sk = tk.Frame(sr, bg=UITheme.BG_PANEL)
        f_sk.pack(side="left", fill="x", expand=True, padx=(0, 2))
        tk.Entry(f_sk, textvariable=app.var_step_key, width=5, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 2))
        tk.Button(f_sk, text="+ 按鍵", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, font=UITheme.FONT_SMALL_BOLD, command=lambda: app.add_key_action(is_combo=False)).pack(side="left", fill="x", expand=True)

        f_sw = tk.Frame(sr, bg=UITheme.BG_PANEL)
        f_sw.pack(side="left", fill="x", expand=True, padx=(2, 0))
        tk.Entry(f_sw, textvariable=app.var_step_wait, width=4, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 2))
        tk.Button(f_sw, text="+ 停頓(s)", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", padx=4, font=UITheme.FONT_SMALL_BOLD, command=lambda: app.add_wait_action(is_combo=False)).pack(side="left", fill="x", expand=True)

        # 3. 呼叫組合與引用變數
        sr_comb = tk.Frame(f_step, bg=UITheme.BG_PANEL)
        sr_comb.pack(fill="x", pady=1)

        f_scall = tk.Frame(sr_comb, bg=UITheme.BG_PANEL)
        f_scall.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.cbo_step_call_combo = ttk.Combobox(f_scall, textvariable=app.var_step_combo_to_call, width=10, state="readonly")
        self.cbo_step_call_combo.pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(f_scall, text="+ 呼叫組合", width=7, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.step_add_call_combo_action).pack(side="left")

        f_svar = tk.Frame(sr_comb, bg=UITheme.BG_PANEL)
        f_svar.pack(side="left", fill="x", expand=True, padx=(2, 0))
        self.cbo_step_add_var = ttk.Combobox(f_svar, textvariable=app.var_step_ref_var, width=10, state="readonly")
        self.cbo_step_add_var.pack(side="left", fill="x", expand=True, padx=(0, 1))
        tk.Button(f_svar, text="+ 引用變數", width=8, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.step_add_variable_action).pack(side="left")

        # 3. 底部固定控制區 (HUD 游標坐標 與 鎖定大小大按鈕)
        bot = tk.Frame(self, bg=UITheme.BG_PANEL)
        bot.pack(side="bottom", fill="x", pady=(2, 0))

        self.lbl_mouse_hud = tk.Label(bot, text="● 游標實時坐標: (0, 0)", anchor="w", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_NORMAL_BOLD)
        self.lbl_mouse_hud.pack(fill="x", pady=(0, 2))

        self.lbl_status = None

        # 鎖定大小之開始/停止按鈕容器 (嚴格鎖定 46px 高度)
        f_btn_wrap = tk.Frame(bot, height=46, bg=UITheme.BG_PANEL)
        f_btn_wrap.pack(fill="x", pady=(2, 0))
        f_btn_wrap.pack_propagate(False)

        self.btn_toggle = tk.Button(
            f_btn_wrap,
            text="▶ 開始循環執行",
            bg=UITheme.ACCENT_GREEN,
            fg="#ffffff",
            font=UITheme.FONT_BIG_BTN,
            activebackground=UITheme.ACCENT_GREEN_HOVER,
            relief="flat",
            command=app.toggle_run
        )
        self.btn_toggle.pack(fill="both", expand=True)

        # 垂直 PanedWindow 將「流程/定時雙清單」與「執行日誌」連接
        pw_right = tk.PanedWindow(
            self,
            orient="vertical",
            bg=UITheme.BORDER,
            bd=0,
            sashwidth=5,
            sashrelief="flat",
            sashpad=1,
            opaqueresize=True
        )
        pw_right.pack(side="top", fill="both", expand=True, pady=(0, 2))

        # 2. 自動循環清單（掛機流程）與定時週期任務 (左右雙清單並排)
        f_middle_split = tk.Frame(pw_right, bg=UITheme.BG_PANEL)
        f_middle_split.grid_columnconfigure(0, weight=1, uniform="split_cols")
        f_middle_split.grid_columnconfigure(1, weight=1, uniform="split_cols")
        f_middle_split.grid_rowconfigure(0, weight=1)

        # 2-A. 左側：自動循環清單（掛機流程）
        f_seq = tk.LabelFrame(f_middle_split, text=" 掛機流程清單 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=4, pady=4)
        f_seq.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        # 頂部控制列
        f_seq_hdr = tk.Frame(f_seq, bg=UITheme.BG_PANEL)
        f_seq_hdr.pack(fill="x", pady=(0, 2))
        self.lbl_seq_hint = tk.Label(f_seq_hdr, text="【流程步驟】 (雙擊修改)", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL)
        self.lbl_seq_hint.pack(side="left")

        self.btn_main_test_all = tk.Button(
            f_seq_hdr,
            text="▶ 試跑流程",
            bg=UITheme.ACCENT_INDIGO,
            fg="#fff",
            activebackground=UITheme.ACCENT_INDIGO_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=4,
            command=app.test_run_execution_flow
        )
        self.btn_main_test_all.pack(side="right")

        # 底部工具列
        sr2 = tk.Frame(f_seq, bg=UITheme.BG_PANEL)
        sr2.pack(side="bottom", fill="x", pady=(2, 0))
        sr2.grid_columnconfigure(0, weight=1)
        sr2.grid_columnconfigure(1, weight=1)
        sr2.grid_columnconfigure(2, weight=1)

        self.btn_main_up = tk.Button(sr2, text="▲ 上移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: app.move_main_step(-1))
        self.btn_main_up.grid(row=0, column=0, padx=1, pady=1, sticky="nsew")

        self.btn_main_down = tk.Button(sr2, text="▼ 下移", bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=lambda: app.move_main_step(1))
        self.btn_main_down.grid(row=0, column=1, padx=1, pady=1, sticky="nsew")

        self.btn_main_test = tk.Button(sr2, text="▶ 試跑", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.test_run_selected_main_step)
        self.btn_main_test.grid(row=0, column=2, padx=1, pady=1, sticky="nsew")

        self.btn_main_edit = tk.Button(sr2, text="✎ 修改", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.edit_selected_main_step)
        self.btn_main_edit.grid(row=1, column=0, padx=1, pady=1, sticky="nsew")

        self.btn_main_dup = tk.Button(sr2, text="⎘ 複製", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.duplicate_main_step)
        self.btn_main_dup.grid(row=1, column=1, padx=1, pady=1, sticky="nsew")

        self.btn_main_del = tk.Button(sr2, text="✕ 刪除", bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.delete_main_step)
        self.btn_main_del.grid(row=1, column=2, padx=1, pady=1, sticky="nsew")

        # 流程清單
        f_list_s = tk.Frame(f_seq, bg=UITheme.BG_DARK)
        f_list_s.pack(side="top", fill="both", expand=True, pady=1)

        self.step_listbox = tk.Listbox(
            f_list_s,
            height=4,
            bg=UITheme.BG_DARK,
            fg=UITheme.TEXT_MAIN,
            selectbackground=UITheme.ACCENT_BLUE,
            selectforeground="#fff",
            bd=0,
            highlightthickness=0,
            font=UITheme.FONT_NORMAL,
            exportselection=False
        )
        self.step_listbox.pack(side="left", fill="both", expand=True)

        def _on_step_list_click(event):
            idx = self.step_listbox.nearest(event.y)
            bbox = self.step_listbox.bbox(idx)
            if not bbox or event.y > (bbox[1] + bbox[3]):
                self.step_listbox.selection_clear(0, tk.END)
                return "break"

        self.step_listbox.bind("<Button-1>", _on_step_list_click)
        self.step_listbox.bind("<Double-Button-1>", lambda e: app.edit_selected_main_step())
        f_list_s.bind("<Button-1>", lambda e: self.step_listbox.selection_clear(0, tk.END))
        sc_step = tk.Scrollbar(f_list_s, orient="vertical", command=self.step_listbox.yview)
        sc_step.pack(side="right", fill="y")
        self.step_listbox.config(yscrollcommand=sc_step.set)

        # 2-B. 右側：定時週期任務清單
        f_pt = tk.LabelFrame(f_middle_split, text=" 定時週期任務 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=4, pady=4)
        f_pt.grid(row=0, column=1, sticky="nsew", padx=(2, 0))

        f_pt_hdr = tk.Frame(f_pt, bg=UITheme.BG_PANEL)
        f_pt_hdr.pack(fill="x", pady=(0, 2))
        lbl_pt_hint = tk.Label(f_pt_hdr, text="【定時任務】 (雙擊修改)", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL)
        lbl_pt_hint.pack(side="left")

        btn_pt_add_hdr = tk.Button(
            f_pt_hdr,
            text="+ 新增",
            bg=UITheme.ACCENT_GREEN,
            fg="#fff",
            activebackground=UITheme.ACCENT_GREEN_HOVER,
            font=UITheme.FONT_SMALL_BOLD,
            relief="flat",
            padx=6,
            command=app.add_new_periodic_task
        )
        btn_pt_add_hdr.pack(side="right")

        # 底部工具列
        pt_ctrl = tk.Frame(f_pt, bg=UITheme.BG_PANEL)
        pt_ctrl.pack(side="bottom", fill="x", pady=(2, 0))
        pt_ctrl.grid_columnconfigure(0, weight=1)
        pt_ctrl.grid_columnconfigure(1, weight=1)
        pt_ctrl.grid_columnconfigure(2, weight=1)

        tk.Button(pt_ctrl, text="+ 新增", bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.add_new_periodic_task).grid(row=0, column=0, padx=1, pady=1, sticky="nsew")
        tk.Button(pt_ctrl, text="✎ 修改", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.edit_selected_periodic_task).grid(row=0, column=1, padx=1, pady=1, sticky="nsew")
        tk.Button(pt_ctrl, text="✓ 開關", bg=UITheme.ACCENT_CYAN, fg="#fff", activebackground=UITheme.ACCENT_CYAN_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.toggle_selected_periodic_task).grid(row=0, column=2, padx=1, pady=1, sticky="nsew")

        tk.Button(pt_ctrl, text="▶ 試跑", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.test_run_selected_periodic_task).grid(row=1, column=0, padx=1, pady=1, sticky="nsew")
        tk.Button(pt_ctrl, text="⎘ 複製", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.duplicate_selected_periodic_task).grid(row=1, column=1, padx=1, pady=1, sticky="nsew")
        tk.Button(pt_ctrl, text="✕ 刪除", bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, command=app.delete_selected_periodic_task).grid(row=1, column=2, padx=1, pady=1, sticky="nsew")

        # 定時清單
        f_list_pt = tk.Frame(f_pt, bg=UITheme.BG_DARK)
        f_list_pt.pack(side="top", fill="both", expand=True, pady=1)

        self.periodic_listbox = PeriodicTaskCardView(
            f_list_pt,
            on_double_click=app.edit_selected_periodic_task,
            on_toggle=app.toggle_selected_periodic_task
        )
        self.periodic_listbox.pack(fill="both", expand=True)
        self.periodic_task_view = self.periodic_listbox

        # 執行日誌面板
        f_log_panel = tk.LabelFrame(
            pw_right,
            text=" 執行日誌 ",
            bg=UITheme.BG_PANEL,
            fg=UITheme.CYAN_TITLE,
            font=UITheme.FONT_TITLE,
            padx=4,
            pady=4
        )

        f_log_hdr = tk.Frame(f_log_panel, bg=UITheme.BG_PANEL)
        f_log_hdr.pack(fill="x", pady=(0, 2))

        tk.Label(
            f_log_hdr,
            text="最新 100 筆",
            bg=UITheme.BG_PANEL,
            fg=UITheme.TEXT_MUTED,
            font=UITheme.FONT_SMALL
        ).pack(side="left")

        btn_clear_log = tk.Button(
            f_log_hdr,
            text="清空",
            bg=UITheme.BTN_GRAY,
            fg="#fff",
            activebackground=UITheme.BTN_GRAY_HOVER,
            relief="flat",
            font=UITheme.FONT_SMALL,
            padx=6,
            pady=0,
            command=app.clear_logs
        )
        btn_clear_log.pack(side="right", padx=(4, 0))

        chk_autoscroll = tk.Checkbutton(
            f_log_hdr,
            text="自動滾動",
            variable=app.var_log_autoscroll,
            bg=UITheme.BG_PANEL,
            fg=UITheme.TEXT_MUTED,
            selectcolor=UITheme.BG_INPUT,
            activebackground=UITheme.BG_PANEL,
            activeforeground=UITheme.TEXT_MAIN,
            font=UITheme.FONT_SMALL
        )
        chk_autoscroll.pack(side="right")

        f_log_box = tk.Frame(f_log_panel, bg=UITheme.BG_DARK, highlightbackground=UITheme.BORDER, highlightthickness=1)
        f_log_box.pack(fill="both", expand=True, pady=(0, 2))

        self.txt_log = tk.Text(
            f_log_box,
            height=6,
            bg=UITheme.BG_DARK,
            fg=UITheme.TEXT_MAIN,
            font=UITheme.FONT_SMALL,
            bd=0,
            highlightthickness=0,
            state="disabled",
            wrap="none"
        )
        self.txt_log.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=2)

        sc_log = tk.Scrollbar(f_log_box, orient="vertical", command=self.txt_log.yview)
        sc_log.pack(side="right", fill="y")
        self.txt_log.config(yscrollcommand=sc_log.set)

        self.txt_log.bind("<MouseWheel>", lambda e: self.txt_log.yview_scroll(int(-1 * (e.delta / 120)), "units") if e.delta else None, add="+")
        self.txt_log.bind("<Button-4>", lambda e: self.txt_log.yview_scroll(-1, "units"), add="+")
        self.txt_log.bind("<Button-5>", lambda e: self.txt_log.yview_scroll(1, "units"), add="+")

        # 設定 Tag 色彩樣式
        self.txt_log.tag_config("time", foreground="#94a3b8")
        self.txt_log.tag_config("tag_流程", foreground="#f1f5f9")
        self.txt_log.tag_config("tag_定時", foreground="#38bdf8")
        self.txt_log.tag_config("tag_組合", foreground="#c084fc")
        self.txt_log.tag_config("tag_系統", foreground="#4ade80")
        self.txt_log.tag_config("tag_試跑", foreground="#818cf8")
        self.txt_log.tag_config("tag_警示", foreground="#f87171")
        self.txt_log.tag_config("text_警示", foreground="#fca5a5")
        self.txt_log.tag_config("text_流程", foreground="#e2e8f0")
        self.txt_log.tag_config("text_定時", foreground="#bae6fd")
        self.txt_log.tag_config("text_組合", foreground="#e9d5ff")
        self.txt_log.tag_config("text_系統", foreground="#86efac")
        self.txt_log.tag_config("text_試跑", foreground="#c7d2fe")

        pw_right.add(f_middle_split, minsize=140)
        pw_right.add(f_log_panel, minsize=75, height=150)

    def get_widgets(self):
        """明確定義右欄面板所管理的公開 UI 控制項字典"""
        return {
            "step_listbox": getattr(self, "step_listbox", None),
            "periodic_listbox": getattr(self, "periodic_listbox", None),
            "periodic_task_view": getattr(self, "periodic_task_view", None),
            "txt_log": getattr(self, "txt_log", None),
            "lbl_mouse_hud": getattr(self, "lbl_mouse_hud", None),
            "btn_toggle": getattr(self, "btn_toggle", None),
            "cbo_step_call_combo": getattr(self, "cbo_step_call_combo", None),
            "cbo_step_add_var": getattr(self, "cbo_step_add_var", None),
            "btn_main_test_all": getattr(self, "btn_main_test_all", None),
            "btn_main_up": getattr(self, "btn_main_up", None),
            "btn_main_down": getattr(self, "btn_main_down", None),
            "btn_main_test": getattr(self, "btn_main_test", None),
            "btn_main_edit": getattr(self, "btn_main_edit", None),
            "btn_main_dup": getattr(self, "btn_main_dup", None),
            "btn_main_del": getattr(self, "btn_main_del", None),
        }

    def export_widgets_to_app(self, app):
        """統一把面板子組件引用寫回 app，讓跨組件依賴關係清晰、可追蹤"""
        if app is None:
            return
        for name, widget in self.get_widgets().items():
            if widget is not None:
                setattr(app, name, widget)

    # ======================= 公開組件存取 API =======================
    def get_step_listbox(self):
        return self.step_listbox

    def get_periodic_listbox(self):
        return self.periodic_listbox

    def get_periodic_task_view(self):
        return self.periodic_task_view

    def get_txt_log(self):
        return self.txt_log

    def get_lbl_status(self):
        return self.lbl_status

    def get_lbl_mouse_hud(self):
        return self.lbl_mouse_hud

    def get_btn_toggle(self):
        return self.btn_toggle
