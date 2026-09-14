"""
Controllers Module (控制器層)
職責：將 App (God Object) 內龐大的 CRUD 操作、項目移動/複製/刪除、
動作組裝與測試試跑邏輯解耦為專屬控制器。

包含：
- BaseController: 提供通用清單操作 (_move_list_item, _duplicate_list_item, _delete_list_item, _clear_list_items, _insert_action_to_target, trigger_hot_reload)
- VarController: 變數管理 (表格刷新、增刪改移、動作組裝、加入主流程/組合)
- ComboController: 技能組合管理 (清單刷新、增刪改查、子動作管理、試跑、呼叫組合)
- StepController: 主步驟掛機流程 (步驟清單刷新、瞄準點擊/按鍵/等待/呼叫/變數動作插入、試跑、整體流程測試)
- PeriodicTaskController: 定時週期任務管理 (清單刷新、增刪改、啟用切換、試跑)
"""

import copy
import time
import uuid
import tkinter as tk
from tkinter import messagebox

from events import EventBus, AppEvents
import state
import engine
import dialogs
from state import format_action_summary


class BaseController:
    """控制器基底類別，持有一個 app 實例並提供通用清單操作工具"""
    def __init__(self, app):
        self.app = app

    def trigger_hot_reload(self):
        """若巨集運行中，同步最新草稿至背景實例快照，並於下一輪自動生效"""
        if state.is_running():
            state.get_state().snapshot_active(reload_requested=True)

    def _move_list_item(self, lst, idx, delta, refresh_cb, item_name="項目"):
        if idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, f"請先在清單點選要移動的{item_name}！")
        target = idx + delta
        if 0 <= target < len(lst):
            lst[idx], lst[target] = lst[target], lst[idx]
            refresh_cb(target)
            direction = "上移" if delta < 0 else "下移"
            EventBus.emit(AppEvents.STATUS_MESSAGE, f"已將{item_name} #{idx+1} {direction}至 #{target+1}")
            self.trigger_hot_reload()
        else:
            EventBus.emit(AppEvents.STATUS_MESSAGE, "已在清單最頂或最底，無法再移動！")

    def _duplicate_list_item(self, lst, idx, refresh_cb, item_name="項目"):
        if idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, f"請先在清單點選要複製的{item_name}！")
        lst.insert(idx + 1, copy.deepcopy(lst[idx]))
        refresh_cb(idx + 1)
        EventBus.emit(AppEvents.STATUS_MESSAGE, f"已複製{item_name} #{idx+1}")
        self.trigger_hot_reload()

    def _delete_list_item(self, lst, idx, refresh_cb, item_name="項目"):
        if idx is None or not (0 <= idx < len(lst)):
            return EventBus.emit(AppEvents.STATUS_MESSAGE, f"請先在清單點選要刪除的{item_name}！")
        removed_item = lst[idx]
        del lst[idx]
        new_sel = min(idx, len(lst) - 1) if lst else None
        refresh_cb(new_sel)

        item_desc = ""
        if isinstance(removed_item, dict):
            item_desc = f": {format_action_summary(removed_item)}"

        EventBus.emit(AppEvents.LOG_MESSAGE, "系統", f"🗑 已移除{item_name} #{idx+1}{item_desc}")
        self.trigger_hot_reload()

    def _clear_list_items(self, lst, confirm_msg, refresh_cb, status_msg):
        if not lst:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, f"{status_msg}本來就是空的")
        if messagebox.askyesno("清空確認", confirm_msg, parent=self.app):
            cnt = len(lst)
            lst.clear()
            refresh_cb(None)
            EventBus.emit(AppEvents.LOG_MESSAGE, "系統", f"🗑 已清空{status_msg}（共移除 {cnt} 個步驟/動作）")
            self.trigger_hot_reload()

    def _insert_action_to_target(self, action_dict, is_combo=False, success_msg=""):
        if is_combo:
            idx = self.app.get_selected_combo_idx()
            if idx is None:
                return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先選取一個組合！")
            actions = state.app_state.combos[idx].setdefault("actions", [])
            sel = self.app.get_selected_action_idx()
            ins = sel + 1 if sel is not None else len(actions)
            actions.insert(ins, action_dict)
            EventBus.emit(AppEvents.COMBO_ACTIONS_CHANGED, select_idx=ins)
            EventBus.emit(AppEvents.COMBOS_CHANGED, select_idx=idx)
            self.sync_combo_actions_to_main_steps(state.app_state.combos[idx]["name"], actions)
            if success_msg:
                EventBus.emit(AppEvents.STATUS_MESSAGE, success_msg)
            self.trigger_hot_reload()
            return ins
        else:
            ins = self.app.get_main_insert_index()
            state.app_state.steps.insert(ins, action_dict)
            EventBus.emit(AppEvents.STEPS_CHANGED, ins)
            if success_msg:
                EventBus.emit(AppEvents.STATUS_MESSAGE, success_msg)
            self.trigger_hot_reload()
            return ins


class VarController(BaseController):
    """變數管理控制器"""

    def add_variable_dialog(self):
        """新增變數入口"""
        self.app.prompt_variable_dialog(None)

    def edit_selected_variable(self):
        """修改所選變數入口"""
        sel = self.app.tree_vars.selection()
        if not sel:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在表格中選擇要修改的變數")
        var_name = sel[0]
        self.app.prompt_variable_dialog(var_name)

    def delete_selected_variable(self):
        """刪除所選變數"""
        sel = self.app.tree_vars.selection()
        if not sel:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在表格中選擇要刪除的變數")
        var_name = sel[0]
        if not messagebox.askyesno("刪除變數", f"請問是否確定刪除變數「{var_name}」？\n若已有動作引用此變數，執行時將自動回退至固定值。", parent=self.app):
            return
        state.app_state.variables.pop(var_name, None)
        self.trigger_hot_reload()
        EventBus.emit(AppEvents.VARS_CHANGED)
        EventBus.emit(AppEvents.COMBO_ACTIONS_CHANGED, )
        EventBus.emit(AppEvents.STEPS_CHANGED, )
        EventBus.emit(AppEvents.LOG_MESSAGE, "系統", f"🗑 已刪除變數：【{var_name}】")

    def move_variable(self, delta):
        sel = self.app.tree_vars.selection()
        if not sel:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在常用變數庫點選要移動的變數！")
        sel_name = sel[0]
        keys = list(state.app_state.variables.keys())
        if sel_name not in keys:
            return
        idx = keys.index(sel_name)
        target = idx + delta
        if 0 <= target < len(keys):
            keys[idx], keys[target] = keys[target], keys[idx]
            new_vars = {k: state.app_state.variables[k] for k in keys}
            state.app_state.variables.clear()
            state.app_state.variables.update(new_vars)
            with state.app_state.steps_lock:
                state.app_state.active_variables = copy.deepcopy(state.app_state.variables)
                state.app_state.reload_requested = True
            EventBus.emit(AppEvents.VARS_CHANGED, select_name=sel_name)
            direction = "上移" if delta < 0 else "下移"
            EventBus.emit(AppEvents.STATUS_MESSAGE, f"已將變數【{sel_name}】{direction}至 #{target+1}")
            self.trigger_hot_reload()
        else:
            EventBus.emit(AppEvents.STATUS_MESSAGE, "已在變數清單最頂或最底，無法再移動！")

    def _build_variable_action(self, var_name):
        """根據變數名稱與類型，組裝對應的動作字典與提示描述，若無效則回傳 (None, None)"""
        if not var_name or var_name not in state.app_state.variables:
            return None, None
        v_info = state.app_state.variables[var_name]
        v_type = v_info.get("type", "coord")
        v_val = v_info.get("value")

        if v_type == "coord":
            px = v_val.get("x", 0) if isinstance(v_val, dict) else 0
            py = v_val.get("y", 0) if isinstance(v_val, dict) else 0
            btn = v_val.get("btn", "left") if isinstance(v_val, dict) else "left"
            btn_cn = "右鍵" if btn == "right" else "左鍵"
            new_act = {
                "type": "click",
                "btn": btn,
                "x": px,
                "y": py,
                "rel": self.app.var_use_rel.get(),
                "var_name": var_name
            }
            desc = f"【{var_name}】({btn_cn}點擊)"
        elif v_type == "key":
            new_act = {
                "type": "key",
                "key": str(v_val),
                "var_name": var_name
            }
            desc = f"【{var_name}】(按鍵[{str(v_val).upper()}])"
        elif v_type == "wait":
            try:
                sec = float(v_val)
            except (ValueError, TypeError):
                sec = 1.0
            new_act = {
                "type": "wait",
                "sec": sec,
                "var_name": var_name
            }
            desc = f"【{var_name}】(停頓{sec}s)"
        else:
            return None, None

        return new_act, desc

    def add_variable_to_main_steps(self):
        """將表格中所選定的變數以引用方式直接加入掛機流程"""
        sel = self.app.tree_vars.selection()
        if not sel:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在表格中選擇要加入流程的變數！")
        var_name = sel[0]
        new_act, desc = self._build_variable_action(var_name)
        if not new_act:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "找不到所選變數或變數無效！")
        ins = self.app.get_main_insert_index()
        self._insert_action_to_target(new_act, is_combo=False, success_msg=f"已將變數{desc} 加入掛機流程 #{ins+1}")

    def combo_add_variable_action(self):
        """將選定的變數以引用方式加入當前選取組合"""
        var_name = self.app.var_combo_ref_var.get().strip()
        new_act, desc = self._build_variable_action(var_name)
        if not new_act:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先選擇要引用的變數！")
        if self.app.get_selected_combo_idx() is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在左邊清單選擇要加入動作的組合！")
        self._insert_action_to_target(new_act, is_combo=True, success_msg=f"已在組合加入引用變數{desc}")


class ComboController(BaseController):
    """技能組合管理控制器"""

    def get_selected_combo_idx(self):
        if not hasattr(self.app, "combo_listbox"):
            return None
        sel = self.app.combo_listbox.curselection()
        return sel[0] if sel and 0 <= sel[0] < len(state.app_state.combos) else None

    def on_combo_select(self, event=None):
        idx = self.get_selected_combo_idx()
        if idx is None:
            if hasattr(self.app, "lbl_combo_editing"):
                self.app.lbl_combo_editing.config(text="【組合動作: 未選取】")
            if hasattr(self.app, "combo_act_listbox"):
                self.app.combo_act_listbox.delete(0, tk.END)
            self.app._refresh_call_combo_dropdown()
            return
        c = state.app_state.combos[idx]
        self.app.var_combo_name.set(c["name"])
        if hasattr(self.app, "lbl_combo_editing"):
            self.app.lbl_combo_editing.config(text=f"【編輯: {c['name']}】")
        EventBus.emit(AppEvents.COMBO_ACTIONS_CHANGED)
        self.app._refresh_call_combo_dropdown()

    def add_new_combo(self):
        name = self.app.var_combo_name.get().strip()
        if not name:
            count = len(state.app_state.combos) + 1
            name = f"組合{count}"
            while any(c["name"] == name for c in state.app_state.combos):
                count += 1
                name = f"組合{count}"
        elif any(c["name"] == name for c in state.app_state.combos):
            messagebox.showwarning("名稱重覆", f"組合名稱「{name}」已存在！請使用其他名稱。", parent=self.app)
            return

        state.app_state.combos.append({"name": name, "actions": []})
        EventBus.emit(AppEvents.COMBOS_CHANGED, select_idx=len(state.app_state.combos)-1)
        EventBus.emit(AppEvents.STATUS_MESSAGE, f"已建立新組合: [{name}]")
        self.trigger_hot_reload()

    def duplicate_selected_combo(self):
        idx = self.get_selected_combo_idx()
        if idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在左邊清單點選要複製的組合！")
        orig = state.app_state.combos[idx]
        base_name = orig["name"]
        new_name = f"{base_name}_副本"
        count = 1
        while any(c["name"] == new_name for c in state.app_state.combos):
            count += 1
            new_name = f"{base_name}_副本{count}"

        state.app_state.combos.insert(idx + 1, {"name": new_name, "actions": copy.deepcopy(orig.get("actions", []))})
        EventBus.emit(AppEvents.COMBOS_CHANGED, select_idx=idx + 1)
        EventBus.emit(AppEvents.STATUS_MESSAGE, f"已複製組合 [{base_name}] 為 [{new_name}]")
        self.trigger_hot_reload()

    def rename_selected_combo(self):
        idx = self.get_selected_combo_idx()
        if idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在左邊點選要改名的組合！")
        new_name = self.app.var_combo_name.get().strip()
        if not new_name:
            messagebox.showwarning("名稱錯誤", "組合名稱不能為空！", parent=self.app)
            return
        old_name = state.app_state.combos[idx]["name"]
        if new_name == old_name:
            EventBus.emit(AppEvents.STATUS_MESSAGE, f"組合名稱未變更: [{old_name}]")
            return
        if any(c["name"] == new_name for c in state.app_state.combos):
            messagebox.showwarning("名稱重覆", f"組合名稱「{new_name}」已存在！請使用其他名稱。", parent=self.app)
            return

        state.app_state.combos[idx]["name"] = new_name

        for c in state.app_state.combos:
            for act in c.get("actions", []):
                if act.get("type") == "call_combo" and act.get("target_name") == old_name:
                    act["target_name"] = new_name

        sync_cnt = 0
        for s in state.app_state.steps:
            if s.get("type") == "call_combo" and s.get("target_name") == old_name:
                s["target_name"] = new_name
                sync_cnt += 1
            elif s.get("type") == "combo":
                if s.get("name") == old_name:
                    s["name"] = new_name
                    sync_cnt += 1
                for act in s.get("actions", []):
                    if act.get("type") == "call_combo" and act.get("target_name") == old_name:
                        act["target_name"] = new_name

        if sync_cnt > 0:
            EventBus.emit(AppEvents.STEPS_CHANGED, )
        EventBus.emit(AppEvents.COMBOS_CHANGED, select_idx=idx)
        EventBus.emit(AppEvents.STATUS_MESSAGE, f"已將組合改名為 [{new_name}]，同步刷新了關聯步驟")
        self.trigger_hot_reload()

    def delete_selected_combo(self):
        idx = self.get_selected_combo_idx()
        if idx is None:
            return
        name = state.app_state.combos[idx]["name"]
        act_cnt = len(state.app_state.combos[idx].get("actions", []))
        if not messagebox.askyesno("刪除組合確認", f"確定要刪除組合【{name}】嗎？組合內的所有動作將會一併清除！", parent=self.app):
            return
        del state.app_state.combos[idx]
        new_sel = min(idx, len(state.app_state.combos) - 1) if state.app_state.combos else None
        EventBus.emit(AppEvents.COMBOS_CHANGED, select_idx=new_sel)
        self.on_combo_select()
        EventBus.emit(AppEvents.STEPS_CHANGED, )
        EventBus.emit(AppEvents.LOG_MESSAGE, "系統", f"🗑 已刪除技能組合【{name}】（內含 {act_cnt} 個動作）")
        self.trigger_hot_reload()

    def add_combo_to_main_steps(self):
        idx = self.get_selected_combo_idx()
        if idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在左邊選擇要加入的組合！")
        c = state.app_state.combos[idx]
        if not c.get("actions"):
            return EventBus.emit(AppEvents.STATUS_MESSAGE, f"組合 [{c['name']}] 內尚未加入任何動作！")

        ins = self.app.get_main_insert_index()
        state.app_state.steps.insert(ins, {"type": "combo", "name": c["name"], "actions": copy.deepcopy(c["actions"])})
        EventBus.emit(AppEvents.STEPS_CHANGED, select_idx=ins)
        EventBus.emit(AppEvents.STATUS_MESSAGE, f"已將組合 [{c['name']}] 加入掛機流程 #{ins+1}")
        self.trigger_hot_reload()

    def move_combo(self, delta):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在組合清單點選要移動的組合！")
        def _refresh(target):
            EventBus.emit(AppEvents.COMBOS_CHANGED, select_idx=target)
        self._move_list_item(state.app_state.combos, c_idx, delta, _refresh, item_name="技能組合")

    # ================= 組合動作管理 =================
    def get_selected_action_idx(self):
        if not hasattr(self.app, "combo_act_listbox"):
            return None
        sel = self.app.combo_act_listbox.curselection()
        return sel[0] if sel else None

    def sync_combo_actions_to_main_steps(self, combo_name, new_actions):
        sync_cnt = 0
        for s in state.app_state.steps:
            if s.get("type") == "combo" and s.get("name") == combo_name:
                s["actions"] = copy.deepcopy(new_actions)
                sync_cnt += 1
        if sync_cnt > 0:
            EventBus.emit(AppEvents.STEPS_CHANGED, )

    def test_run_selected_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        a_idx = self.get_selected_action_idx()
        if c_idx is None or a_idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先選擇要試跑的組合動作！")
        act = state.app_state.combos[c_idx]["actions"][a_idx]
        self.app.run_in_test_thread(f"組合動作 #{a_idx+1}", lambda: self.app.execute_single_action(act, f"組合動作#{a_idx+1}"))

    def test_run_current_combo(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先選擇要試跑的組合！")
        c = state.app_state.combos[c_idx]
        sub_actions = c.get("actions", [])
        if not sub_actions:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, f"組合 [{c['name']}] 內無任何動作可試跑！")

        def _run():
            for a_idx, act in enumerate(sub_actions):
                if state.app_state.stop_event.is_set():
                    break
                self.app.execute_single_action(act, f"[{c['name']}#{a_idx+1}]")

        self.app.run_in_test_thread(f"組合 [{c['name']}]", _run)

    def edit_selected_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        a_idx = self.get_selected_action_idx()
        if c_idx is None or a_idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先選擇組合動作！")

        act = state.app_state.combos[c_idx]["actions"][a_idx]
        curr_combo_name = state.app_state.combos[c_idx]["name"]
        avail_combos = [c["name"] for c in state.app_state.combos if c["name"] != curr_combo_name]

        if self.app.prompt_edit_action(act, available_combos=avail_combos):
            EventBus.emit(AppEvents.COMBO_ACTIONS_CHANGED, select_idx=a_idx)
            self.sync_combo_actions_to_main_steps(state.app_state.combos[c_idx]["name"], state.app_state.combos[c_idx]["actions"])
            EventBus.emit(AppEvents.STATUS_MESSAGE, f"已成功更新組合動作 #{a_idx+1}")
            self.trigger_hot_reload()

    def move_combo_action(self, delta):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在左邊清單選取一個組合！")
        a_idx = self.get_selected_action_idx()
        actions = state.app_state.combos[c_idx]["actions"]
        def _refresh(target):
            EventBus.emit(AppEvents.COMBO_ACTIONS_CHANGED, select_idx=target)
            self.sync_combo_actions_to_main_steps(state.app_state.combos[c_idx]["name"], actions)
        self._move_list_item(actions, a_idx, delta, _refresh, item_name="組合動作")

    def duplicate_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在左邊清單選取一個組合！")
        a_idx = self.get_selected_action_idx()
        actions = state.app_state.combos[c_idx]["actions"]
        def _refresh(target):
            EventBus.emit(AppEvents.COMBO_ACTIONS_CHANGED, select_idx=target)
            EventBus.emit(AppEvents.COMBOS_CHANGED, select_idx=c_idx)
            self.sync_combo_actions_to_main_steps(state.app_state.combos[c_idx]["name"], actions)
        self._duplicate_list_item(actions, a_idx, _refresh, item_name="組合動作")

    def delete_combo_action(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在左邊清單選取一個組合！")
        a_idx = self.get_selected_action_idx()
        actions = state.app_state.combos[c_idx]["actions"]
        def _refresh(target):
            EventBus.emit(AppEvents.COMBO_ACTIONS_CHANGED, select_idx=target)
            EventBus.emit(AppEvents.COMBOS_CHANGED, select_idx=c_idx)
            self.sync_combo_actions_to_main_steps(state.app_state.combos[c_idx]["name"], actions)
        self._delete_list_item(actions, a_idx, _refresh, item_name="組合動作")

    def clear_combo_actions(self):
        c_idx = self.get_selected_combo_idx()
        if c_idx is None:
            return
        actions = state.app_state.combos[c_idx].get("actions", [])
        def _refresh(_):
            EventBus.emit(AppEvents.COMBO_ACTIONS_CHANGED)
            EventBus.emit(AppEvents.COMBOS_CHANGED, select_idx=c_idx)
            self.sync_combo_actions_to_main_steps(state.app_state.combos[c_idx]["name"], [])
        self._clear_list_items(actions, f"請問是否清空組合 [{state.app_state.combos[c_idx]['name']}] 的所有動作？", _refresh, "組合所有動作")

    def combo_add_call_action(self):
        idx = self.get_selected_combo_idx()
        if idx is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先選取一個組合！")
        target_name = self.app.var_combo_to_call.get().strip()
        if not target_name:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在下拉選單選擇要呼叫的組合！")
        if target_name == state.app_state.combos[idx]["name"]:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "不能在組合內呼叫自己！")
        self._insert_action_to_target({"type": "call_combo", "target_name": target_name}, is_combo=True, success_msg=f"已在組合加入呼叫: [{target_name}]")


class StepController(BaseController):
    """主步驟掛機流程控制器"""

    def get_main_insert_index(self):
        if not hasattr(self.app, "step_listbox"):
            return len(state.app_state.steps)
        sel = self.app.step_listbox.curselection()
        return sel[0] + 1 if sel else len(state.app_state.steps)

    def add_click_action(self, is_combo=False):
        if state.is_running():
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "巨集正在循環執行中，為免干擾滑鼠瞄準，請先停止運行再取點！")
        if is_combo and self.app.get_selected_combo_idx() is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先選取一個組合！")
        btn_var = self.app.var_combo_btn if is_combo else self.app.var_step_btn
        target_btn = "right" if btn_var.get() == "右鍵" else "left"
        btn_cn = "右鍵" if target_btn == "right" else "左鍵"

        def cb(x, y, rel):
            if is_combo:
                msg = f"已在組合加入{btn_cn}點擊 ({x},{y})"
            else:
                ins = self.get_main_insert_index()
                msg = f"已成功新增{btn_cn}點擊位置到第 #{ins+1} 步"
            self._insert_action_to_target({"type": "click", "btn": target_btn, "x": x, "y": y, "rel": rel}, is_combo=is_combo, success_msg=msg)

        self.app.capture_pos_space(cb, btn=target_btn)

    def add_manual_click(self, is_combo=False):
        if is_combo and self.app.get_selected_combo_idx() is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先選取一個組合！")
        var_x = self.app.var_combo_manual_x if is_combo else self.app.var_step_manual_x
        var_y = self.app.var_combo_manual_y if is_combo else self.app.var_step_manual_y
        try:
            x = int(var_x.get().strip())
            y = int(var_y.get().strip())
        except ValueError:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "X 和 Y 必須輸入整數！")

        btn_var = self.app.var_combo_btn if is_combo else self.app.var_step_btn
        target_btn = "right" if btn_var.get() == "右鍵" else "left"
        btn_cn = "右鍵" if target_btn == "right" else "左鍵"

        if is_combo:
            msg = f"已手動在組合加入{btn_cn}點擊: ({x}, {y})"
        else:
            ins = self.get_main_insert_index()
            msg = f"已手動插入{btn_cn}點擊到掛機流程 #{ins+1}: ({x}, {y})"

        self._insert_action_to_target({"type": "click", "btn": target_btn, "x": x, "y": y, "rel": self.app.var_use_rel.get()}, is_combo=is_combo, success_msg=msg)

    def add_key_action(self, is_combo=False):
        if is_combo and self.app.get_selected_combo_idx() is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先選取一個組合！")
        key_var = self.app.var_combo_act_key if is_combo else self.app.var_step_key
        key = key_var.get().strip().lower()
        if not key:
            return
        if is_combo:
            msg = f"已在組合加入按鍵 [{key.upper()}]"
        else:
            ins = self.get_main_insert_index()
            msg = f"已插入按鍵到掛機流程 #{ins+1}: [{key.upper()}]"
        self._insert_action_to_target({"type": "key", "key": key}, is_combo=is_combo, success_msg=msg)

    def add_wait_action(self, is_combo=False):
        if is_combo and self.app.get_selected_combo_idx() is None:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先選取一個組合！")
        wait_var = self.app.var_combo_act_wait if is_combo else self.app.var_step_wait
        try:
            sec = float(wait_var.get())
            if sec <= 0:
                raise ValueError
        except ValueError:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "停頓秒數必須大於0！")
        if is_combo:
            msg = f"已在組合加入停頓 {sec} 秒"
        else:
            ins = self.get_main_insert_index()
            msg = f"已插入等待到掛機流程 #{ins+1}: {sec} 秒"
        self._insert_action_to_target({"type": "wait", "sec": sec}, is_combo=is_combo, success_msg=msg)

    def step_add_call_combo_action(self):
        """在掛機流程中加入呼叫組合步驟"""
        target_name = self.app.var_step_combo_to_call.get().strip()
        if not target_name:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在下拉選單選擇要呼叫的組合！")
        ins = self.get_main_insert_index()
        self._insert_action_to_target(
            {"type": "call_combo", "target_name": target_name},
            is_combo=False,
            success_msg=f"已插入呼叫組合到掛機流程 #{ins+1}: [{target_name}]"
        )

    def step_add_variable_action(self):
        """在掛機流程中加入引用變數動作"""
        var_name = self.app.var_step_ref_var.get().strip()
        new_act, desc = self.app._build_variable_action(var_name)
        if not new_act:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在下拉選單選擇要引用的變數！")
        ins = self.get_main_insert_index()
        self._insert_action_to_target(new_act, is_combo=False, success_msg=f"已插入引用變數到掛機流程 #{ins+1}: {desc}")

    def test_run_selected_main_step(self):
        sel = self.app.step_listbox.curselection() if hasattr(self.app, "step_listbox") else None
        if not sel:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在清單中選擇要試跑的主步驟！")
        idx = sel[0]
        s = state.app_state.steps[idx]

        def _run():
            if s.get("type") == "combo":
                c_name = s.get("name", "組合")
                sub_actions = s.get("actions", [])
                if not sub_actions:
                    return EventBus.emit(AppEvents.STATUS_MESSAGE, f"組合 [{c_name}] 內無任何動作！")
                for sub_idx, sub_act in enumerate(sub_actions):
                    if state.app_state.stop_event.is_set():
                        break
                    self.app.execute_single_action(sub_act, f"[{c_name}#{sub_idx+1}]")
            else:
                self.app.execute_single_action(s, f"步驟#{idx+1}")

        self.app.run_in_test_thread(f"步驟 #{idx+1}", _run)

    def test_run_execution_flow(self):
        """一次性試跑整個掛機執行流程（所有主步驟依序執行一輪）"""
        if not state.app_state.steps:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "掛機流程清單內無任何步驟可試跑！")
        self.app.run_in_test_thread("掛機流程", lambda: engine.test_run_execution_flow_worker())

    def edit_selected_main_step(self):
        sel = self.app.step_listbox.curselection() if hasattr(self.app, "step_listbox") else None
        if not sel:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在掛機流程選擇步驟！")
        idx = sel[0]
        if self.app.prompt_edit_action(state.app_state.steps[idx], step_idx=idx):
            EventBus.emit(AppEvents.STEPS_CHANGED, idx)
            EventBus.emit(AppEvents.STATUS_MESSAGE, f"已成功更新主步驟 #{idx+1}")
            self.trigger_hot_reload()

    def move_main_step(self, delta):
        sel = self.app.step_listbox.curselection() if hasattr(self.app, "step_listbox") else None
        idx = sel[0] if sel else None
        self._move_list_item(state.app_state.steps, idx, delta, lambda target: EventBus.emit(AppEvents.STEPS_CHANGED, select_idx=target), item_name="主步驟")

    def duplicate_main_step(self):
        sel = self.app.step_listbox.curselection() if hasattr(self.app, "step_listbox") else None
        idx = sel[0] if sel else None
        self._duplicate_list_item(state.app_state.steps, idx, lambda target: EventBus.emit(AppEvents.STEPS_CHANGED, select_idx=target), item_name="主步驟")

    def delete_main_step(self):
        sel = self.app.step_listbox.curselection() if hasattr(self.app, "step_listbox") else None
        idx = sel[0] if sel else None
        self._delete_list_item(state.app_state.steps, idx, lambda target: EventBus.emit(AppEvents.STEPS_CHANGED, select_idx=target), item_name="主步驟")

    def clear_main_steps(self):
        self._clear_list_items(state.app_state.steps, "請問是否清空整個掛機流程？\n清空後未儲存的內容無法還原！", lambda _: EventBus.emit(AppEvents.STEPS_CHANGED), "掛機流程")


class PeriodicTaskController(BaseController):
    """定時週期任務控制器"""

    def add_new_periodic_task(self):
        new_pt = dialogs.prompt_edit_periodic_task(self.app, task=None)
        if new_pt:
            state.app_state.periodic_tasks.append(new_pt)
            new_idx = len(state.app_state.periodic_tasks) - 1
            EventBus.emit(AppEvents.PERIODIC_TASKS_CHANGED, new_idx)
            EventBus.emit(AppEvents.STATUS_MESSAGE, f"已新增定時任務：【{new_pt.get('name')}】(每 {new_pt.get('interval')} 秒)")
            self.trigger_hot_reload()

    def edit_selected_periodic_task(self):
        sel = self.app.periodic_listbox.curselection() if hasattr(self.app, "periodic_listbox") else None
        if not sel:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在定時任務清單中選擇任務！")
        idx = sel[0]
        updated_pt = dialogs.prompt_edit_periodic_task(self.app, task=state.app_state.periodic_tasks[idx])
        if updated_pt:
            state.app_state.periodic_tasks[idx] = updated_pt
            EventBus.emit(AppEvents.PERIODIC_TASKS_CHANGED, idx)
            EventBus.emit(AppEvents.STATUS_MESSAGE, f"已更新定時任務 #{idx+1}：【{updated_pt.get('name')}】")
            self.trigger_hot_reload()

    def toggle_selected_periodic_task(self):
        sel = self.app.periodic_listbox.curselection() if hasattr(self.app, "periodic_listbox") else None
        if not sel:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在定時任務清單中選擇要開關的任務！")
        idx = sel[0]
        pt = state.app_state.periodic_tasks[idx]
        pt["enabled"] = not pt.get("enabled", True)
        st_text = "啟用" if pt["enabled"] else "停用"
        EventBus.emit(AppEvents.PERIODIC_TASKS_CHANGED, idx)
        EventBus.emit(AppEvents.STATUS_MESSAGE, f"已將定時任務【{pt.get('name')}】切換為 [{st_text}]")
        self.trigger_hot_reload()

    def duplicate_selected_periodic_task(self):
        sel = self.app.periodic_listbox.curselection() if hasattr(self.app, "periodic_listbox") else None
        if not sel:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在定時任務清單中選擇要複製的任務！")
        idx = sel[0]
        copied_pt = copy.deepcopy(state.app_state.periodic_tasks[idx])
        copied_pt["id"] = f"pt_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        copied_pt["name"] = f"{copied_pt.get('name', '任務')}_副本"
        state.app_state.periodic_tasks.insert(idx + 1, copied_pt)
        EventBus.emit(AppEvents.PERIODIC_TASKS_CHANGED, idx + 1)
        EventBus.emit(AppEvents.STATUS_MESSAGE, f"已複製定時任務至 #{idx+2}")
        self.trigger_hot_reload()

    def delete_selected_periodic_task(self):
        sel = self.app.periodic_listbox.curselection() if hasattr(self.app, "periodic_listbox") else None
        if not sel:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在定時任務清單中選擇要刪除的任務！")
        idx = sel[0]
        name = state.app_state.periodic_tasks[idx].get("name", "未命名")
        if not messagebox.askyesno("刪除定時任務確認", f"確定要刪除定時任務【{name}】嗎？\n刪除後無法還原！", parent=self.app):
            return
        del state.app_state.periodic_tasks[idx]
        new_sel = min(idx, len(state.app_state.periodic_tasks) - 1) if state.app_state.periodic_tasks else None
        EventBus.emit(AppEvents.PERIODIC_TASKS_CHANGED, new_sel)
        EventBus.emit(AppEvents.LOG_MESSAGE, "系統", f"🗑 已刪除定時任務 #{idx+1}：【{name}】")
        self.trigger_hot_reload()

    def test_run_selected_periodic_task(self):
        sel = self.app.periodic_listbox.curselection() if hasattr(self.app, "periodic_listbox") else None
        if not sel:
            return EventBus.emit(AppEvents.STATUS_MESSAGE, "請先在定時任務清單中選擇要試跑的任務！")
        idx = sel[0]
        pt = state.app_state.periodic_tasks[idx]
        t_name = pt.get("name", "定時任務")
        act = pt.get("action", {})

        def _do_test_pt():
            try:
                self.app.highlight_active_periodic_task(idx)
                self.app.execute_single_action(act, f"[定時試跑: {t_name}]")
            finally:
                self.app.clear_active_periodic_task_highlight()

        self.app.run_in_test_thread(f"定時任務【{t_name}】", _do_test_pt)
