class HotReloadService:
    """熱重載觸發邏輯的專門服務，讓 App 只處理 UI 層入口與回饋。"""

    def __init__(self, app):
        self.app = app

    def trigger_hot_reload(self):
        app_state = getattr(self.app, "app_state", None)
        if app_state is None:
            return False
        if app_state.is_running():
            try:
                app_state.snapshot_active(reload_requested=True)
                return True
            except Exception:
                return False
        return False
