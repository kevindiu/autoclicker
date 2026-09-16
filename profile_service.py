import os
from tkinter import messagebox, simpledialog

import config_manager
from theme import CONFIG_EXT


class ProfileService:
    """設定檔管理邏輯的專門服務，讓 App 只保留 UI 互動與入口。"""

    def __init__(self, app):
        self.app = app

    def _profile_path(self, name):
        return os.path.join(config_manager._DEFAULT_DIR, f"{name}{CONFIG_EXT}")

    def get_profile_files(self):
        return config_manager.get_profile_files(CONFIG_EXT)

    def refresh_profiles(self, select_name=None):
        config_manager.ensure_default_profile(CONFIG_EXT)
        profiles = self.get_profile_files()
        if not profiles:
            profiles = ["default"]

        self.app.cbo_profile["values"] = profiles
        if select_name and select_name in profiles:
            self.app.cbo_profile.set(select_name)
        elif self.app.var_profile_name.get() in profiles:
            self.app.cbo_profile.set(self.app.var_profile_name.get())
        else:
            self.app.cbo_profile.current(0)

    def set_active_profile(self, name):
        if name:
            self.app.var_profile_name.set(name)
            self.app.cbo_profile.set(name)
        return name

    def create_new_profile(self):
        if self.app.app_state.is_running() or self.app.app_state.is_testing:
            return self.app.set_status("巨集正在執行或試跑中，請先停止再新建設定檔！")
        name = simpledialog.askstring("新建設定檔", "請輸入新設定檔名稱 (毋須輸入副檔名):", parent=self.app)
        if not name or not name.strip():
            return
        name = name.strip()
        fn = self._profile_path(name)
        if os.path.exists(fn):
            if not messagebox.askyesno("檔案覆蓋確認", f"設定檔「{name}」已存在！\n請問是否確認覆蓋原有設定？", parent=self.app):
                return
        try:
            config_manager.save_profile_file(name, self.app.app_state, CONFIG_EXT)
            self.refresh_profiles(select_name=name)
            self.app.last_saved_snapshot = self.app.get_current_data_snapshot()
            self.app.set_status(f"已新建並儲存至 {fn}")
        except Exception as e:
            self.app.set_status(f"新建失敗: {e}")
            self.app.append_log("警示", f"新建設定檔失敗: {e}")

    def save_config(self):
        name = self.app.var_profile_name.get().strip()
        if not name:
            return self.app.set_status("請先選擇或新建設定檔")
        fn = self._profile_path(name)
        if os.path.exists(fn):
            if not messagebox.askyesno("檔案覆蓋確認", f"請問是否確認覆蓋「{name}」的原有設定？", parent=self.app):
                return self.app.set_status("已取消儲存")
        try:
            config_manager.save_profile_file(name, self.app.app_state, CONFIG_EXT)
            self.app.set_status(f"已成功儲存至 {fn}")
            self.refresh_profiles(select_name=name)
            self.app.last_saved_snapshot = self.app.get_current_data_snapshot()
        except Exception as e:
            self.app.set_status(f"儲存失敗: {e}")
            self.app.append_log("警示", f"儲存設定檔失敗: {e}")

    def load_config(self):
        if self.app.app_state.is_running() or self.app.app_state.is_testing:
            return self.app.set_status("巨集正在執行或試跑中，請先停止再載入設定檔！")
        name = self.app.var_profile_name.get().strip()
        if not name:
            return
        fn = self._profile_path(name)
        if not os.path.exists(fn):
            return self.app.set_status(f"找不到檔案：{fn}")
        try:
            config_manager.load_profile_file(name, self.app.app_state, CONFIG_EXT)
            self.app.refresh_variables_table()
            self.app.refresh_combo_list()
            self.app.refresh_combo_actions_list()
            self.app.update_step_list()
            self.app.update_periodic_list()
            self.app.last_saved_snapshot = self.app.get_current_data_snapshot()
            self.app.set_status(f"成功載入設定檔：{name}")
        except Exception as e:
            self.app.set_status(f"載入失敗: {e}")
            self.app.append_log("警示", f"載入設定檔失敗: {e}")
