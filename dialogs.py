import copy
import time
import tkinter as tk
from tkinter import ttk, messagebox

import state
from theme import UITheme

# ==============================================================================
# 次層級對話框模組
# ==============================================================================

def prompt_variable_dialog(app, edit_name=None):
    """彈出變數新增 / 修改對話框 (通用無 Emoji 標籤)"""
    is_edit = edit_name is not None
    title = f"修改變數: {edit_name}" if is_edit else "新增變數"

    orig_data = state.variables.get(edit_name, {}) if is_edit else {}
    orig_type = orig_data.get("type", "coord")
    orig_val = orig_data.get("value", {})

    type_display_map = {"coord": "[坐標]", "key": "[按鍵]", "wait": "[停頓]"}
    type_key_map = {"[坐標]": "coord", "[按鍵]": "key", "[停頓]": "wait", "坐標": "coord", "按鍵": "key", "停頓": "wait"}

    dialog = tk.Toplevel(app)
    dialog.title(title)
    dialog.configure(bg=UITheme.BG_PANEL)
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.transient(app)
    dialog.grab_set()
    app.apply_app_icon(dialog)

    w, h = 380, 340
    app.update_idletasks()
    pos_x = app.winfo_x() + max(0, (app.winfo_width() - w) // 2)
    pos_y = app.winfo_y() + max(0, (app.winfo_height() - h) // 2)
    dialog.geometry(f"{w}x{h}+{pos_x}+{pos_y}")

    f_main = tk.Frame(dialog, bg=UITheme.BG_PANEL, padx=16, pady=12)
    f_main.pack(fill="both", expand=True)

    # 變數名稱
    r_name = tk.Frame(f_main, bg=UITheme.BG_PANEL)
    r_name.pack(fill="x", pady=(0, 8))
    tk.Label(r_name, text="變數名稱:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL_BOLD, width=8, anchor="e").pack(side="left", padx=(0, 8))
    var_name = tk.StringVar(value=edit_name if is_edit else "")
    e_name = tk.Entry(r_name, textvariable=var_name, bg=UITheme.BG_INPUT, fg="#fff", font=UITheme.FONT_NORMAL, relief="flat")
    e_name.pack(side="left", fill="x", expand=True)
    if is_edit:
        e_name.config(state="disabled", fg=UITheme.TEXT_MUTED)

    # 變數種類
    r_type = tk.Frame(f_main, bg=UITheme.BG_PANEL)
    r_type.pack(fill="x", pady=(0, 8))
    tk.Label(r_type, text="變數種類:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL_BOLD, width=8, anchor="e").pack(side="left", padx=(0, 8))
    curr_type_disp = type_display_map.get(orig_type, "[坐標]")
    var_type = tk.StringVar(value=curr_type_disp)
    cbo_type = ttk.Combobox(r_type, textvariable=var_type, values=["[坐標]", "[按鍵]", "[停頓]"], state="readonly" if not is_edit else "disabled", font=UITheme.FONT_NORMAL)
    cbo_type.pack(side="left", fill="x", expand=True)

    # 數值動態容器
    f_val_box = tk.LabelFrame(f_main, text=" 數值設定 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=10, pady=8)
    f_val_box.pack(fill="both", expand=True, pady=(0, 10))

    if orig_type == "coord" and isinstance(orig_val, dict):
        init_x = str(orig_val.get("x", 0))
        init_y = str(orig_val.get("y", 0))
        init_btn = "右鍵" if orig_val.get("btn") == "right" else "左鍵"
    else:
        init_x, init_y, init_btn = "0", "0", "左鍵"
    var_x = tk.StringVar(value=init_x)
    var_y = tk.StringVar(value=init_y)
    var_btn = tk.StringVar(value=init_btn)

    init_key = str(orig_val) if orig_type == "key" else "f1"
    var_key = tk.StringVar(value=init_key)

    init_wait = str(orig_val) if orig_type == "wait" else "1.0"
    var_wait = tk.StringVar(value=init_wait)

    def start_space_capture():
        if state.running:
            app.set_status("巨集正在循環執行中，為免干擾滑鼠瞄準，請先停止運行再取點！")
            return
        dialog.grab_release()
        dialog.withdraw()
        target_btn = "right" if var_btn.get() == "右鍵" else "left"
        def on_finish(rx, ry, rel):
            dialog.deiconify()
            dialog.lift()
            dialog.focus_force()
            dialog.grab_set()
            var_x.set(str(rx))
            var_y.set(str(ry))
            btn_cn = "右鍵" if target_btn == "right" else "左鍵"
            app.set_status(f"變數取點成功 [{btn_cn}]: ({rx}, {ry})")
        def on_cancel():
            dialog.deiconify()
            dialog.lift()
            dialog.focus_force()
            dialog.grab_set()
        app.capture_pos_space(on_finish, on_cancel, btn=target_btn)

    def render_inputs():
        for child in f_val_box.winfo_children():
            child.destroy()

        selected_type_disp = var_type.get()
        selected_type = type_key_map.get(selected_type_disp, "coord")
        if selected_type == "coord":
            r_btn = tk.Frame(f_val_box, bg=UITheme.BG_PANEL)
            r_btn.pack(fill="x", pady=(1, 3))
            tk.Label(r_btn, text="點擊類型:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 4))
            cbo_btn = ttk.Combobox(r_btn, textvariable=var_btn, values=["左鍵", "右鍵"], width=6, state="readonly", font=UITheme.FONT_NORMAL)
            cbo_btn.pack(side="left", padx=(0, 4))

            r_coords = tk.Frame(f_val_box, bg=UITheme.BG_PANEL)
            r_coords.pack(fill="x", pady=(2, 5))

            tk.Label(r_coords, text="X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 4))
            e_x = tk.Entry(r_coords, textvariable=var_x, width=7, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL)
            e_x.pack(side="left", padx=(0, 12))

            tk.Label(r_coords, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 4))
            e_y = tk.Entry(r_coords, textvariable=var_y, width=7, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL)
            e_y.pack(side="left", padx=(0, 4))

            btn_rec = tk.Button(
                f_val_box,
                text="◎ 瞄準取點 (Space)",
                bg=UITheme.ACCENT_GREEN,
                fg="#fff",
                activebackground=UITheme.ACCENT_GREEN_HOVER,
                font=UITheme.FONT_NORMAL_BOLD,
                relief="flat",
                command=start_space_capture
            )
            btn_rec.pack(fill="x", pady=(2, 2))

        elif selected_type == "key":
            r_k = tk.Frame(f_val_box, bg=UITheme.BG_PANEL)
            r_k.pack(fill="x", pady=6)
            tk.Label(r_k, text="按鍵名稱:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 8))
            e_k = tk.Entry(r_k, textvariable=var_key, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL)
            e_k.pack(side="left", fill="x", expand=True)
            tk.Label(f_val_box, text="(例: f1, 1, z, space, enter)", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(anchor="w")

        elif selected_type == "wait":
            r_w = tk.Frame(f_val_box, bg=UITheme.BG_PANEL)
            r_w.pack(fill="x", pady=6)
            tk.Label(r_w, text="停頓時間 (秒):", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 8))
            e_w = tk.Entry(r_w, textvariable=var_wait, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL)
            e_w.pack(side="left", fill="x", expand=True)
            tk.Label(f_val_box, text="(例: 0.5, 1.0, 2.5)", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(anchor="w")

    cbo_type.bind("<<ComboboxSelected>>", lambda e: render_inputs())
    render_inputs()

    # 底部確定 / 取消按鈕
    def on_save():
        name = var_name.get().strip()
        if not name:
            messagebox.showerror("錯誤", "變數名稱不可為空！", parent=dialog)
            return
        if not is_edit and name in state.variables:
            messagebox.showerror("錯誤", f"變數「{name}」已存在！請使用其他名稱。", parent=dialog)
            return

        sel_type_disp = var_type.get()
        type_key = type_key_map.get(sel_type_disp, "coord")

        if type_key == "coord":
            try:
                px = int(var_x.get().strip())
                py = int(var_y.get().strip())
            except ValueError:
                messagebox.showerror("錯誤", "坐標 X 與 Y 必須是整數！", parent=dialog)
                return
            btn_type = "right" if var_btn.get() == "右鍵" else "left"
            val = {"x": px, "y": py, "btn": btn_type}
        elif type_key == "key":
            k = var_key.get().strip().lower()
            if not k:
                messagebox.showerror("錯誤", "按鍵名稱不可為空！", parent=dialog)
                return
            val = k
        elif type_key == "wait":
            try:
                sec = float(var_wait.get().strip())
                if sec <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("錯誤", "停頓時間必須輸入大於 0 的秒數！", parent=dialog)
                return
            val = sec
        else:
            return

        state.variables[name] = {"type": type_key, "value": val}
        app.trigger_hot_reload()
        app.refresh_variables_table()
        app.refresh_combo_actions_list()
        app.update_step_list()
        app.set_status(f"已儲存變數: {name}")
        dialog.destroy()

    r_btns = tk.Frame(f_main, bg=UITheme.BG_PANEL)
    r_btns.pack(fill="x", pady=(4, 0))

    tk.Button(
        r_btns,
        text="✓ 確定儲存",
        width=10,
        bg=UITheme.ACCENT_BLUE,
        fg="#fff",
        activebackground=UITheme.ACCENT_BLUE_HOVER,
        font=UITheme.FONT_NORMAL_BOLD,
        relief="flat",
        padx=8,
        pady=4,
        command=on_save
    ).pack(side="right", padx=(4, 0))

    tk.Button(
        r_btns,
        text="✕ 取消",
        width=8,
        bg=UITheme.BTN_GRAY,
        fg="#fff",
        activebackground=UITheme.BTN_GRAY_HOVER,
        font=UITheme.FONT_NORMAL,
        relief="flat",
        padx=8,
        pady=4,
        command=dialog.destroy
    ).pack(side="right")

    dialog.bind("<Return>", lambda e: on_save())
    dialog.bind("<Escape>", lambda e: dialog.destroy())

    if not is_edit:
        e_name.focus_set()


def prompt_edit_combo_dialog(app, combo_step, step_idx=None):
    """彈出完整的組合子動作管理視窗 (支援在組合內移位、刪除、複製、修改、試跑與展開)"""
    dialog = tk.Toplevel(app)
    combo_name = combo_step.get("name", "組合")
    dialog.title(f"管理組合步驟: 【{combo_name}】")
    dialog.configure(bg=UITheme.BG_PANEL)
    dialog.resizable(True, True)
    dialog.attributes("-topmost", True)
    dialog.transient(app)
    dialog.grab_set()
    app.apply_app_icon(dialog)

    w, h = 660, 520
    app.update_idletasks()
    pos_x = app.winfo_x() + max(0, (app.winfo_width() - w) // 2)
    pos_y = app.winfo_y() + max(0, (app.winfo_height() - h) // 2)
    dialog.geometry(f"{w}x{h}+{pos_x}+{pos_y}")
    dialog.minsize(560, 420)

    working_actions = copy.deepcopy(combo_step.get("actions", []))
    modified = [False]

    # 頂部控制欄 (標題、切換範本、展開按鈕)
    f_top = tk.Frame(dialog, bg=UITheme.BG_PANEL, padx=12, pady=8)
    f_top.pack(fill="x")

    r1 = tk.Frame(f_top, bg=UITheme.BG_PANEL)
    r1.pack(fill="x", pady=(0, 4))
    lbl_title = tk.Label(r1, text=f"◆ 組合名稱: 【{combo_name}】", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE)
    lbl_title.pack(side="left")

    def do_unpack():
        if not working_actions:
            messagebox.showwarning("提示", "此組合內沒有任何子動作可展開！", parent=dialog)
            return
        if messagebox.askyesno("展開確認", f"確定要將組合 【{combo_name}】 的 {len(working_actions)} 個子動作直接展開為掛機流程中的獨立步驟嗎？\n\n展開後每一步均可直接在流程清單中自由移動、修改與刪除。", parent=dialog):
            if step_idx is not None and 0 <= step_idx < len(state.steps):
                del state.steps[step_idx]
                for offset, act in enumerate(working_actions):
                    state.steps.insert(step_idx + offset, copy.deepcopy(act))
                app.update_step_list(select_idx=step_idx)
                app.set_status(f"已將組合 [{combo_name}] 展開為 {len(working_actions)} 個獨立步驟")
                app.trigger_hot_reload()
            modified[0] = True
            dialog.destroy()

    btn_unpack = tk.Button(
        r1,
        text="[ ➔ 展開為獨立步驟到掛機流程 ]",
        bg=UITheme.ACCENT_CYAN,
        fg="#fff",
        activebackground=UITheme.ACCENT_CYAN_HOVER,
        font=UITheme.FONT_SMALL_BOLD,
        relief="flat",
        padx=8,
        pady=2,
        command=do_unpack
    )
    btn_unpack.pack(side="right")

    r2 = tk.Frame(f_top, bg=UITheme.BG_PANEL)
    r2.pack(fill="x", pady=(4, 0))
    tk.Label(r2, text="載入組合庫範本:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 4))
    tpl_names = [c["name"] for c in state.combos]
    var_tpl = tk.StringVar(value=combo_name if combo_name in tpl_names else (tpl_names[0] if tpl_names else ""))
    cbo_tpl = ttk.Combobox(r2, textvariable=var_tpl, values=tpl_names, width=16, state="readonly")
    cbo_tpl.pack(side="left", padx=2)

    def do_load_tpl():
        chosen = var_tpl.get().strip()
        matched = next((c for c in state.combos if c["name"] == chosen), None)
        if matched:
            nonlocal combo_name
            combo_name = matched["name"]
            combo_step["name"] = combo_name
            lbl_title.config(text=f"◆ 組合名稱: 【{combo_name}】")
            working_actions.clear()
            working_actions.extend(copy.deepcopy(matched.get("actions", [])))
            refresh_sub_list(select_idx=0 if working_actions else None)
            app.set_status(f"已載入範本 [{combo_name}] 的子動作清單")

    tk.Button(r2, text="套用範本動作", bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, font=UITheme.FONT_SMALL_BOLD, relief="flat", padx=6, command=do_load_tpl).pack(side="left", padx=4)

    # 中間主工作區 (左邊子步驟清單，右邊垂直操作按鈕列)
    f_mid = tk.Frame(dialog, bg=UITheme.BG_PANEL, padx=12, pady=4)
    f_mid.pack(fill="both", expand=True)

    f_list_wrap = tk.Frame(f_mid, bg=UITheme.BG_PANEL)
    f_list_wrap.pack(side="left", fill="both", expand=True)

    tk.Label(f_list_wrap, text="【子動作清單】 (雙擊可修改)", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL_BOLD, anchor="w").pack(fill="x", pady=(0, 3))

    f_sub_box = tk.Frame(f_list_wrap, bg=UITheme.BG_DARK)
    f_sub_box.pack(fill="both", expand=True)

    sub_list = tk.Listbox(
        f_sub_box,
        bg=UITheme.BG_DARK,
        fg=UITheme.TEXT_MAIN,
        selectbackground=UITheme.ACCENT_BLUE,
        selectforeground="#fff",
        bd=0,
        highlightthickness=0,
        font=UITheme.FONT_NORMAL,
        exportselection=False
    )
    sub_list.pack(side="left", fill="both", expand=True)
    sub_list.bind("<Double-Button-1>", lambda e: do_edit_sub())

    sc_sub = tk.Scrollbar(f_sub_box, orient="vertical", command=sub_list.yview)
    sc_sub.pack(side="right", fill="y")
    sub_list.config(yscrollcommand=sc_sub.set)

    def refresh_sub_list(select_idx=None):
        sub_list.delete(0, tk.END)
        for i, act in enumerate(working_actions):
            sub_list.insert(tk.END, state.format_action_summary(act, index=i))
        if select_idx is not None and 0 <= select_idx < len(working_actions):
            sub_list.selection_set(select_idx)
            sub_list.see(select_idx)

    # 右側控制按鈕列
    f_btns = tk.Frame(f_mid, bg=UITheme.BG_PANEL, padx=8)
    f_btns.pack(side="right", fill="y")

    def get_sel_sub():
        sel = sub_list.curselection()
        return sel[0] if sel else None

    def do_move_sub(delta):
        idx = get_sel_sub()
        if idx is None:
            messagebox.showinfo("提示", "請先在清單中選取要移動的子步驟！", parent=dialog)
            return
        target = idx + delta
        if 0 <= target < len(working_actions):
            working_actions[idx], working_actions[target] = working_actions[target], working_actions[idx]
            refresh_sub_list(select_idx=target)

    def do_edit_sub():
        idx = get_sel_sub()
        if idx is None:
            messagebox.showinfo("提示", "請先在清單中選取要修改的子步驟！", parent=dialog)
            return
        curr_act = working_actions[idx]
        if prompt_edit_action(app, curr_act):
            refresh_sub_list(select_idx=idx)

    def do_dup_sub():
        idx = get_sel_sub()
        if idx is None:
            messagebox.showinfo("提示", "請先在清單中選取要複製的子步驟！", parent=dialog)
            return
        working_actions.insert(idx + 1, copy.deepcopy(working_actions[idx]))
        refresh_sub_list(select_idx=idx + 1)

    def do_del_sub():
        idx = get_sel_sub()
        if idx is None:
            messagebox.showinfo("提示", "請先在清單中選取要刪除的子步驟！", parent=dialog)
            return
        del working_actions[idx]
        new_sel = min(idx, len(working_actions) - 1) if working_actions else None
        refresh_sub_list(select_idx=new_sel)

    def do_test_sub():
        idx = get_sel_sub()
        if idx is None:
            messagebox.showinfo("提示", "請先在清單中選取要試跑的子步驟！", parent=dialog)
            return
        act = working_actions[idx]
        app.run_in_test_thread(f"組合動作 #{idx+1}", lambda: app.execute_single_action(act, f"[{combo_name}#{idx+1}]"))

    tk.Button(f_btns, text="▲ 上移", width=12, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=4, command=lambda: do_move_sub(-1)).pack(fill="x", pady=2)
    tk.Button(f_btns, text="▼ 下移", width=12, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=4, command=lambda: do_move_sub(1)).pack(fill="x", pady=2)
    tk.Button(f_btns, text="▶ 試跑動作", width=12, bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=4, command=do_test_sub).pack(fill="x", pady=2)
    tk.Button(f_btns, text="✎ 修改", width=12, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=4, command=do_edit_sub).pack(fill="x", pady=2)
    tk.Button(f_btns, text="⎘ 複製", width=12, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=4, command=do_dup_sub).pack(fill="x", pady=2)
    tk.Button(f_btns, text="✕ 刪除", width=12, bg=UITheme.ACCENT_RED, fg="#fff", activebackground=UITheme.ACCENT_RED_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, pady=4, command=do_del_sub).pack(fill="x", pady=(2, 6))

    # 底部按鈕列 (確認 / 取消)
    f_bot = tk.Frame(dialog, bg=UITheme.BG_PANEL, padx=12, pady=10)
    f_bot.pack(fill="x")

    def on_save():
        combo_step["name"] = combo_name
        combo_step["actions"] = working_actions
        modified[0] = True
        dialog.destroy()

    tk.Button(f_bot, text="✓ 確定儲存", width=12, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_NORMAL_BOLD, pady=4, command=on_save).pack(side="right", padx=(4, 0))
    tk.Button(f_bot, text="✕ 取消", width=8, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_NORMAL, pady=4, command=dialog.destroy).pack(side="right")

    refresh_sub_list(select_idx=0 if working_actions else None)

    dialog.bind("<Return>", lambda e: on_save())
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    app.wait_window(dialog)
    return modified[0]


def prompt_edit_action(app, action, available_combos=None, step_idx=None):
    """彈出針對各動作型別的編輯對話框"""
    atype = action.get("type")
    if not atype: return False

    if atype == "combo":
        return prompt_edit_combo_dialog(app, action, step_idx=step_idx)

    dialog = tk.Toplevel(app)
    dialog.configure(bg=UITheme.BG_PANEL)
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.transient(app)
    dialog.grab_set()
    app.apply_app_icon(dialog)

    w, h = 350, 260
    app.update_idletasks()
    pos_x = app.winfo_x() + max(0, (app.winfo_width() - w) // 2)
    pos_y = app.winfo_y() + max(0, (app.winfo_height() - h) // 2)
    dialog.geometry(f"{w}x{h}+{pos_x}+{pos_y}")

    modified = [False]
    f = tk.Frame(dialog, bg=UITheme.BG_PANEL, pady=10)
    f.pack()

    if atype == "click":
        dialog.title("修改點擊動作")
        var_x = tk.StringVar(value=str(action.get("x", 0)))
        var_y = tk.StringVar(value=str(action.get("y", 0)))
        curr_btn = "右鍵" if action.get("btn") == "right" else "左鍵"
        var_btn = tk.StringVar(value=curr_btn)

        coord_vars = [k for k, v in state.variables.items() if v.get("type") == "coord"]
        opt_vars = ["(不引用 / 固定坐標)"] + coord_vars
        curr_var = action.get("var_name", "")
        var_ref = tk.StringVar(value=curr_var if curr_var in coord_vars else "(不引用 / 固定坐標)")

        tk.Label(f, text="引用變數:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=0, column=0, padx=6, pady=3, sticky="e")
        cbo_ref = ttk.Combobox(f, textvariable=var_ref, values=opt_vars, width=14, state="readonly")
        cbo_ref.grid(row=0, column=1, padx=6, pady=3, sticky="w")

        def on_ref_change(event=None):
            chosen = var_ref.get()
            if chosen in state.variables:
                v_val = state.variables[chosen].get("value", {})
                if isinstance(v_val, dict):
                    var_x.set(str(v_val.get("x", 0)))
                    var_y.set(str(v_val.get("y", 0)))
                    if "btn" in v_val:
                        var_btn.set("右鍵" if v_val.get("btn") == "right" else "左鍵")
        cbo_ref.bind("<<ComboboxSelected>>", on_ref_change)

        tk.Label(f, text="按鍵類型:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=1, column=0, padx=6, pady=3, sticky="e")
        cbo_btn = ttk.Combobox(f, textvariable=var_btn, values=["左鍵", "右鍵"], width=8, state="readonly")
        cbo_btn.grid(row=1, column=1, padx=6, pady=3, sticky="w")

        tk.Label(f, text="X 坐標:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=2, column=0, padx=6, pady=3, sticky="e")
        e_x = tk.Entry(f, textvariable=var_x, width=10, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL)
        e_x.grid(row=2, column=1, padx=6, pady=3, sticky="w")

        tk.Label(f, text="Y 坐標:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=3, column=0, padx=6, pady=3, sticky="e")
        e_y = tk.Entry(f, textvariable=var_y, width=10, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL)
        e_y.grid(row=3, column=1, padx=6, pady=3, sticky="w")

        btn_rec = tk.Button(f, text="◎ 重新瞄準取點 (Space)", width=24, bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, font=UITheme.FONT_NORMAL_BOLD)
        btn_rec.grid(row=4, column=0, columnspan=2, pady=(8, 2))

        def do_rec():
            if state.running:
                app.set_status("巨集正在循環執行中，為免干擾滑鼠瞄準，請先停止運行再取點！")
                return
            dialog.grab_release()
            dialog.withdraw()

            def on_finish_space(rx, ry, rel):
                dialog.deiconify()
                dialog.lift()
                dialog.focus_force()
                dialog.grab_set()
                var_x.set(str(rx))
                var_y.set(str(ry))
                app.set_status(f"已更新點擊位置: ({rx}, {ry})")

            def on_cancel_space():
                dialog.deiconify()
                dialog.lift()
                dialog.focus_force()
                dialog.grab_set()

            target_btn = "right" if var_btn.get() == "右鍵" else "left"
            app.capture_pos_space(on_finish_space, on_cancel_space, btn=target_btn)

        btn_rec.config(command=do_rec)
        e_x.focus_set()

        def on_ok():
            try:
                action["x"] = int(var_x.get().strip())
                action["y"] = int(var_y.get().strip())
                action["btn"] = "right" if var_btn.get() == "右鍵" else "left"
                chosen = var_ref.get()
                if chosen in coord_vars:
                    action["var_name"] = chosen
                else:
                    action.pop("var_name", None)
                modified[0] = True
                dialog.destroy()
            except ValueError:
                messagebox.showerror("錯誤", "X 和 Y 必須輸入整數！", parent=dialog)

    elif atype == "key":
        dialog.title("修改按鍵")
        var_k = tk.StringVar(value=str(action.get("key", "f1")))
        key_vars = [k for k, v in state.variables.items() if v.get("type") == "key"]
        opt_vars = ["(不引用 / 固定按鍵)"] + key_vars
        curr_var = action.get("var_name", "")
        var_ref = tk.StringVar(value=curr_var if curr_var in key_vars else "(不引用 / 固定按鍵)")

        tk.Label(f, text="引用變數:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=0, column=0, padx=6, pady=3, sticky="e")
        cbo_ref = ttk.Combobox(f, textvariable=var_ref, values=opt_vars, width=14, state="readonly")
        cbo_ref.grid(row=0, column=1, padx=6, pady=3, sticky="w")

        def on_ref_change(event=None):
            chosen = var_ref.get()
            if chosen in state.variables:
                var_k.set(str(state.variables[chosen].get("value", "")))
        cbo_ref.bind("<<ComboboxSelected>>", on_ref_change)

        tk.Label(f, text="按鍵名稱:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=1, column=0, padx=6, pady=6, sticky="e")
        e_k = tk.Entry(f, textvariable=var_k, width=12, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL)
        e_k.grid(row=1, column=1, padx=6, pady=6)
        e_k.focus_set()

        def on_ok():
            k = var_k.get().strip().lower()
            if not k:
                messagebox.showerror("錯誤", "按鍵名稱不可為空！", parent=dialog)
                return
            action["key"] = k
            chosen = var_ref.get()
            if chosen in key_vars:
                action["var_name"] = chosen
            else:
                action.pop("var_name", None)
            modified[0] = True
            dialog.destroy()

    elif atype == "wait":
        dialog.title("修改停頓時間")
        var_w = tk.StringVar(value=str(action.get("sec", 1.0)))
        wait_vars = [k for k, v in state.variables.items() if v.get("type") == "wait"]
        opt_vars = ["(不引用 / 固定秒數)"] + wait_vars
        curr_var = action.get("var_name", "")
        var_ref = tk.StringVar(value=curr_var if curr_var in wait_vars else "(不引用 / 固定秒數)")

        tk.Label(f, text="引用變數:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=0, column=0, padx=6, pady=3, sticky="e")
        cbo_ref = ttk.Combobox(f, textvariable=var_ref, values=opt_vars, width=14, state="readonly")
        cbo_ref.grid(row=0, column=1, padx=6, pady=3, sticky="w")

        def on_ref_change(event=None):
            chosen = var_ref.get()
            if chosen in state.variables:
                var_w.set(str(state.variables[chosen].get("value", "")))
        cbo_ref.bind("<<ComboboxSelected>>", on_ref_change)

        tk.Label(f, text="等待秒數:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=1, column=0, padx=6, pady=6, sticky="e")
        e_w = tk.Entry(f, textvariable=var_w, width=10, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL)
        e_w.grid(row=1, column=1, padx=6, pady=6)
        e_w.focus_set()

        def on_ok():
            try:
                sec = float(var_w.get().strip())
                if sec <= 0: raise ValueError
                action["sec"] = sec
                chosen = var_ref.get()
                if chosen in wait_vars:
                    action["var_name"] = chosen
                else:
                    action.pop("var_name", None)
                modified[0] = True
                dialog.destroy()
            except ValueError:
                messagebox.showerror("錯誤", "停頓時間必須輸入大於 0 的數字！", parent=dialog)

    elif atype == "call_combo":
        dialog.title("修改呼叫目標組合")
        curr_tgt = action.get("target_name", "")
        var_c = tk.StringVar(value=curr_tgt)
        combos_list = available_combos or [c["name"] for c in state.combos]
        tk.Label(f, text="目標組合:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL).grid(row=0, column=0, padx=6, pady=10, sticky="e")
        cbo = ttk.Combobox(f, textvariable=var_c, values=combos_list, width=14, state="readonly")
        cbo.grid(row=0, column=1, padx=6, pady=10)
        if curr_tgt in combos_list: cbo.set(curr_tgt)
        elif combos_list: cbo.current(0)

        def on_ok():
            tgt = var_c.get().strip()
            if not tgt:
                messagebox.showerror("錯誤", "請先選擇有效的組合名稱！", parent=dialog)
                return
            action["target_name"] = tgt
            modified[0] = True
            dialog.destroy()

    bf = tk.Frame(dialog, bg=UITheme.BG_PANEL, padx=16, pady=10)
    bf.pack(fill="x")
    tk.Button(bf, text="✓ 確定儲存", width=10, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_NORMAL_BOLD, command=on_ok).pack(side="right", padx=(4, 0))
    tk.Button(bf, text="✕ 取消", width=8, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_NORMAL, command=dialog.destroy).pack(side="right")

    dialog.bind("<Return>", lambda e: on_ok())
    dialog.bind("<Escape>", lambda e: dialog.destroy())

    app.wait_window(dialog)
    return modified[0]

def prompt_edit_periodic_task(app, task=None):
    """彈出定時週期任務新增 / 修改對話框"""
    is_edit = task is not None
    title = "修改定時週期任務" if is_edit else "新增定時週期任務"

    orig_task = copy.deepcopy(task) if is_edit else {}
    task_id = orig_task.get("id") or f"pt_{int(time.time()*1000)}"
    init_name = orig_task.get("name", "")
    init_interval = str(orig_task.get("interval", 30.0))
    init_enabled = orig_task.get("enabled", True)
    init_run_on_start = orig_task.get("run_on_start", False)

    act = orig_task.get("action", {})
    act_type = act.get("type", "call_combo" if state.combos else "key")
    act_var = act.get("var_name")

    dialog = tk.Toplevel(app)
    dialog.title(title)
    dialog.configure(bg=UITheme.BG_PANEL)
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)
    dialog.transient(app)
    dialog.grab_set()
    app.apply_app_icon(dialog)

    w, h = 420, 460
    app.update_idletasks()
    pos_x = app.winfo_x() + max(0, (app.winfo_width() - w) // 2)
    pos_y = app.winfo_y() + max(0, (app.winfo_height() - h) // 2)
    dialog.geometry(f"{w}x{h}+{pos_x}+{pos_y}")

    result = [None]
    f_main = tk.Frame(dialog, bg=UITheme.BG_PANEL, padx=16, pady=12)
    f_main.pack(fill="both", expand=True)

    # 1. 基本設定卡片
    f_base = tk.LabelFrame(f_main, text=" 基本設定 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=8, pady=6)
    f_base.pack(fill="x", pady=(0, 8))

    # 任務名稱
    r1 = tk.Frame(f_base, bg=UITheme.BG_PANEL)
    r1.pack(fill="x", pady=2)
    tk.Label(r1, text="任務名稱:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL_BOLD, width=8, anchor="e").pack(side="left", padx=(0, 6))
    var_name = tk.StringVar(value=init_name)
    e_name = tk.Entry(r1, textvariable=var_name, bg=UITheme.BG_INPUT, fg="#fff", font=UITheme.FONT_NORMAL, relief="flat")
    e_name.pack(side="left", fill="x", expand=True)

    # 執行間隔 (秒)
    r2 = tk.Frame(f_base, bg=UITheme.BG_PANEL)
    r2.pack(fill="x", pady=2)
    tk.Label(r2, text="觸發間隔:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL_BOLD, width=8, anchor="e").pack(side="left", padx=(0, 6))
    var_interval = tk.StringVar(value=init_interval)
    e_interval = tk.Entry(r2, textvariable=var_interval, width=8, bg=UITheme.BG_INPUT, fg="#fff", font=UITheme.FONT_NORMAL, relief="flat")
    e_interval.pack(side="left", padx=(0, 4))
    tk.Label(r2, text="秒 (例如: 30 或 2.5)", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(side="left")

    # 啟用與啟動時立即首發
    r3 = tk.Frame(f_base, bg=UITheme.BG_PANEL)
    r3.pack(fill="x", pady=(4, 0))
    var_enabled = tk.BooleanVar(value=init_enabled)
    var_start = tk.BooleanVar(value=init_run_on_start)
    tk.Checkbutton(r3, text="啟用此定時任務", variable=var_enabled, bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, selectcolor=UITheme.BG_PANEL, activebackground=UITheme.BG_PANEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(8, 12))
    tk.Checkbutton(r3, text="巨集啟動時先執行一次", variable=var_start, bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, selectcolor=UITheme.BG_PANEL, activebackground=UITheme.BG_PANEL, font=UITheme.FONT_NORMAL).pack(side="left")

    # 2. 執行動作設定卡片
    f_act = tk.LabelFrame(f_main, text=" 執行動作內容 ", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_TITLE, font=UITheme.FONT_TITLE, padx=8, pady=6)
    f_act.pack(fill="both", expand=True, pady=(0, 8))

    # Determine initial category
    if act_var:
        init_category = "[引用全域變數]"
    elif act_type == "call_combo":
        init_category = "[呼叫技能組合]"
    elif act_type == "click":
        init_category = "[單一點擊]"
    elif act_type == "wait":
        init_category = "[單一停頓]"
    else:
        init_category = "[單一按鍵]"

    r_cat = tk.Frame(f_act, bg=UITheme.BG_PANEL)
    r_cat.pack(fill="x", pady=(0, 6))
    tk.Label(r_cat, text="動作類型:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL_BOLD, width=8, anchor="e").pack(side="left", padx=(0, 6))
    var_category = tk.StringVar(value=init_category)
    cbo_cat = ttk.Combobox(r_cat, textvariable=var_category, values=["[呼叫技能組合]", "[引用全域變數]", "[單一按鍵]", "[單一點擊]", "[單一停頓]"], state="readonly", font=UITheme.FONT_NORMAL)
    cbo_cat.pack(side="left", fill="x", expand=True)

    # 動態內容容器
    f_dynamic = tk.Frame(f_act, bg=UITheme.BG_PANEL)
    f_dynamic.pack(fill="both", expand=True, pady=4)

    # 各類型對應變數
    combos_list = [c["name"] for c in state.combos]
    var_combo = tk.StringVar(value=act.get("target_name") or (combos_list[0] if combos_list else ""))

    vars_list = list(state.variables.keys())
    var_var_name = tk.StringVar(value=act_var or (vars_list[0] if vars_list else ""))

    var_key = tk.StringVar(value=str(act.get("key", "f1")))

    var_x = tk.StringVar(value=str(act.get("x", 0)))
    var_y = tk.StringVar(value=str(act.get("y", 0)))
    var_btn = tk.StringVar(value="右鍵" if act.get("btn") == "right" else "左鍵")

    var_wait = tk.StringVar(value=str(act.get("sec", 1.0)))

    def update_dynamic_panel(event=None):
        for widget in f_dynamic.winfo_children():
            widget.destroy()

        cat = var_category.get()
        if cat == "[呼叫技能組合]":
            row = tk.Frame(f_dynamic, bg=UITheme.BG_PANEL)
            row.pack(fill="x", pady=6)
            tk.Label(row, text="目標組合:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(4, 6))
            c_vals = [c["name"] for c in state.combos]
            if not c_vals:
                tk.Label(row, text="(目前技能組合庫中無組合，請先建立組合)", bg=UITheme.BG_PANEL, fg=UITheme.ACCENT_RED, font=UITheme.FONT_SMALL).pack(side="left")
            else:
                if var_combo.get() not in c_vals:
                    var_combo.set(c_vals[0])
                cbo = ttk.Combobox(row, textvariable=var_combo, values=c_vals, state="readonly", font=UITheme.FONT_NORMAL)
                cbo.pack(side="left", fill="x", expand=True)

        elif cat == "[引用全域變數]":
            row = tk.Frame(f_dynamic, bg=UITheme.BG_PANEL)
            row.pack(fill="x", pady=4)
            tk.Label(row, text="目標變數:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(4, 6))
            v_vals = list(state.variables.keys())
            if not v_vals:
                tk.Label(row, text="(目前無任何變數，請先於變數庫建立)", bg=UITheme.BG_PANEL, fg=UITheme.ACCENT_RED, font=UITheme.FONT_SMALL).pack(side="left")
            else:
                if var_var_name.get() not in v_vals:
                    var_var_name.set(v_vals[0])
                cbo = ttk.Combobox(row, textvariable=var_var_name, values=v_vals, state="readonly", font=UITheme.FONT_NORMAL)
                cbo.pack(side="left", fill="x", expand=True)

                lbl_preview = tk.Label(f_dynamic, text="", bg=UITheme.BG_PANEL, fg=UITheme.CYAN_SUB, font=UITheme.FONT_SMALL)
                lbl_preview.pack(anchor="w", padx=10, pady=2)

                def _update_var_preview(e=None):
                    v_name = var_var_name.get()
                    if v_name in state.variables:
                        v_info = state.variables[v_name]
                        v_type = v_info.get("type", "")
                        v_val = v_info.get("value", "")
                        lbl_preview.config(text=f"變數型態: [{v_type}]  數值: {v_val}")
                cbo.bind("<<ComboboxSelected>>", _update_var_preview)
                _update_var_preview()

        elif cat == "[單一按鍵]":
            row = tk.Frame(f_dynamic, bg=UITheme.BG_PANEL)
            row.pack(fill="x", pady=6)
            tk.Label(row, text="按鍵名稱:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(4, 6))
            e_k = tk.Entry(row, textvariable=var_key, width=12, bg=UITheme.BG_INPUT, fg="#fff", font=UITheme.FONT_NORMAL, relief="flat")
            e_k.pack(side="left", padx=(0, 6))
            tk.Label(row, text="(例如: f1, space, 1, a)", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(side="left")

        elif cat == "[單一點擊]":
            r_c1 = tk.Frame(f_dynamic, bg=UITheme.BG_PANEL)
            r_c1.pack(fill="x", pady=2)
            tk.Label(r_c1, text="滑鼠按鍵:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(4, 6))
            ttk.Combobox(r_c1, textvariable=var_btn, values=["左鍵", "右鍵"], width=6, state="readonly").pack(side="left", padx=(0, 8))

            tk.Label(r_c1, text="X:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_NORMAL).pack(side="left", padx=(4, 2))
            tk.Entry(r_c1, textvariable=var_x, width=6, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left", padx=(0, 6))
            tk.Label(r_c1, text="Y:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_NORMAL).pack(side="left", padx=(4, 2))
            tk.Entry(r_c1, textvariable=var_y, width=6, bg=UITheme.BG_INPUT, fg="#fff", relief="flat", font=UITheme.FONT_NORMAL).pack(side="left")

            r_c2 = tk.Frame(f_dynamic, bg=UITheme.BG_PANEL)
            r_c2.pack(fill="x", pady=4)
            btn_rec = tk.Button(r_c2, text="◎ 重新瞄準取點 (Space)", bg=UITheme.ACCENT_GREEN, fg="#fff", activebackground=UITheme.ACCENT_GREEN_HOVER, font=UITheme.FONT_NORMAL_BOLD, relief="flat", padx=8)
            btn_rec.pack(fill="x", padx=4)

            def do_rec():
                if state.running:
                    app.set_status("巨集正在循環執行中，為免干擾滑鼠瞄準，請先停止運行再取點！")
                    return
                dialog.grab_release()
                dialog.withdraw()

                def on_finish_space(rx, ry, rel):
                    dialog.deiconify()
                    dialog.lift()
                    dialog.focus_force()
                    dialog.grab_set()
                    var_x.set(str(rx))
                    var_y.set(str(ry))
                    app.set_status(f"定時點擊取點成功: ({rx}, {ry})")

                def on_cancel_space():
                    dialog.deiconify()
                    dialog.lift()
                    dialog.focus_force()
                    dialog.grab_set()

                target_btn = "right" if var_btn.get() == "右鍵" else "left"
                app.capture_pos_space(on_finish_space, on_cancel_space, btn=target_btn)

            btn_rec.config(command=do_rec)

        elif cat == "[單一停頓]":
            row = tk.Frame(f_dynamic, bg=UITheme.BG_PANEL)
            row.pack(fill="x", pady=6)
            tk.Label(row, text="等待秒數:", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_LABEL, font=UITheme.FONT_NORMAL).pack(side="left", padx=(4, 6))
            e_w = tk.Entry(row, textvariable=var_wait, width=8, bg=UITheme.BG_INPUT, fg="#fff", font=UITheme.FONT_NORMAL, relief="flat")
            e_w.pack(side="left", padx=(0, 6))
            tk.Label(row, text="秒 (大於 0 的數字)", bg=UITheme.BG_PANEL, fg=UITheme.TEXT_MUTED, font=UITheme.FONT_SMALL).pack(side="left")

    cbo_cat.bind("<<ComboboxSelected>>", update_dynamic_panel)
    update_dynamic_panel()

    def build_action_dict():
        cat = var_category.get()
        if cat == "[呼叫技能組合]":
            tgt = var_combo.get().strip()
            if not tgt:
                messagebox.showerror("錯誤", "請先選擇有效的技能組合！", parent=dialog)
                return None
            return {"type": "call_combo", "target_name": tgt}
        elif cat == "[引用全域變數]":
            v_name = var_var_name.get().strip()
            if not v_name or v_name not in state.variables:
                messagebox.showerror("錯誤", "請先選擇有效的全域變數！", parent=dialog)
                return None
            v_info = state.variables[v_name]
            v_type = v_info.get("type", "key")
            v_val = v_info.get("value", {})
            if v_type == "coord":
                btn = v_val.get("btn", "left") if isinstance(v_val, dict) else "left"
                x = v_val.get("x", 0) if isinstance(v_val, dict) else 0
                y = v_val.get("y", 0) if isinstance(v_val, dict) else 0
                return {"type": "click", "x": x, "y": y, "btn": btn, "var_name": v_name}
            elif v_type == "wait":
                try:
                    sec = float(v_val)
                except Exception:
                    sec = 1.0
                return {"type": "wait", "sec": sec, "var_name": v_name}
            else:
                key_str = str(v_val) if v_val else "f1"
                return {"type": "key", "key": key_str, "var_name": v_name}
        elif cat == "[單一按鍵]":
            k = var_key.get().strip().lower()
            if not k:
                messagebox.showerror("錯誤", "按鍵名稱不可為空！", parent=dialog)
                return None
            return {"type": "key", "key": k}
        elif cat == "[單一點擊]":
            try:
                x = int(var_x.get().strip())
                y = int(var_y.get().strip())
                btn = "right" if var_btn.get() == "右鍵" else "left"
                return {"type": "click", "x": x, "y": y, "btn": btn}
            except ValueError:
                messagebox.showerror("錯誤", "坐標 X 與 Y 必須輸入整數！", parent=dialog)
                return None
        elif cat == "[單一停頓]":
            try:
                s = float(var_wait.get().strip())
                if s <= 0:
                    raise ValueError
                return {"type": "wait", "sec": s}
            except ValueError:
                messagebox.showerror("錯誤", "停頓時間必須大於 0 秒！", parent=dialog)
                return None
        return None

    def do_test():
        built_act = build_action_dict()
        if not built_act:
            return
        app.execute_single_action(built_act, f"[試跑定時動作]")

    def on_ok():
        try:
            interval_val = float(var_interval.get().strip())
            if interval_val <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("錯誤", "執行間隔必須輸入大於 0 的秒數！", parent=dialog)
            return

        built_act = build_action_dict()
        if not built_act:
            return

        name_val = var_name.get().strip()
        if not name_val:
            if built_act.get("type") == "call_combo":
                name_val = f"定時_{built_act.get('target_name', '組合')}"
            elif built_act.get("var_name"):
                name_val = f"定時_{built_act.get('var_name')}"
            elif built_act.get("type") == "key":
                name_val = f"定時按鍵_{built_act.get('key', '').upper()}"
            elif built_act.get("type") == "click":
                btn_str = "右鍵" if built_act.get("btn") == "right" else "左鍵"
                name_val = f"定時點擊_{btn_str}"
            else:
                name_val = "定時任務"

        result[0] = {
            "id": task_id,
            "name": name_val,
            "interval": interval_val,
            "enabled": var_enabled.get(),
            "run_on_start": var_start.get(),
            "action": built_act
        }
        dialog.destroy()

    bf = tk.Frame(dialog, bg=UITheme.BG_PANEL, padx=16, pady=10)
    bf.pack(fill="x")
    tk.Button(bf, text="▶ 試跑動作", bg=UITheme.ACCENT_INDIGO, fg="#fff", activebackground=UITheme.ACCENT_INDIGO_HOVER, relief="flat", font=UITheme.FONT_SMALL_BOLD, padx=6, command=do_test).pack(side="left")
    tk.Button(bf, text="✓ 確定儲存", width=10, bg=UITheme.ACCENT_BLUE, fg="#fff", activebackground=UITheme.ACCENT_BLUE_HOVER, relief="flat", font=UITheme.FONT_NORMAL_BOLD, command=on_ok).pack(side="right", padx=(4, 0))
    tk.Button(bf, text="✕ 取消", width=8, bg=UITheme.BTN_GRAY, fg="#fff", activebackground=UITheme.BTN_GRAY_HOVER, relief="flat", font=UITheme.FONT_NORMAL, command=dialog.destroy).pack(side="right")

    dialog.bind("<Return>", lambda e: on_ok())
    dialog.bind("<Escape>", lambda e: dialog.destroy())

    app.wait_window(dialog)
    return result[0]

