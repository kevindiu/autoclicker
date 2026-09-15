import tkinter as tk

from theme import UITheme


class UIFeedbackService:
    """處理執行狀態在主畫面清單上的視覺回饋。"""

    def __init__(self, app):
        self.app = app

    def clear_active_step_highlight(self):
        def clear():
            if self.app.is_closing:
                return
            if hasattr(self.app, "step_listbox") and self.app.step_listbox.winfo_exists():
                last_idx = getattr(self.app, "last_active_step_idx", None)
                if last_idx is not None and 0 <= last_idx < self.app.step_listbox.size():
                    try:
                        self.app.step_listbox.itemconfigure(
                            last_idx,
                            background=UITheme.BG_DARK,
                            foreground=UITheme.TEXT_MAIN,
                        )
                    except tk.TclError:
                        pass
                self.app.last_active_step_idx = None

        self.app.run_on_ui_thread(clear)

    def highlight_active_step(self, idx, sub_idx=None):
        if idx is None:
            return self.clear_active_step_highlight()

        def highlight():
            if self.app.is_closing:
                return
            if not hasattr(self.app, "step_listbox") or not self.app.step_listbox.winfo_exists():
                return

            listbox = self.app.step_listbox
            listbox_size = listbox.size()
            last_idx = getattr(self.app, "last_active_step_idx", None)
            if last_idx is not None and 0 <= last_idx < listbox_size and last_idx != idx:
                try:
                    listbox.itemconfigure(
                        last_idx,
                        background=UITheme.BG_DARK,
                        foreground=UITheme.TEXT_MAIN,
                    )
                except tk.TclError:
                    pass

            if 0 <= idx < listbox_size:
                try:
                    listbox.itemconfigure(
                        idx,
                        background=UITheme.STEP_ACTIVE_BG,
                        foreground=UITheme.STEP_ACTIVE_FG,
                    )
                    self.app.last_active_step_idx = idx
                    listbox.see(idx)
                except tk.TclError:
                    pass

        self.app.run_on_ui_thread(highlight)

    def highlight_pending_step(self, idx):
        def highlight():
            if self.app.is_closing:
                return
            if not hasattr(self.app, "step_listbox") or not self.app.step_listbox.winfo_exists():
                return

            listbox = self.app.step_listbox
            listbox_size = listbox.size()
            last_idx = getattr(self.app, "last_active_step_idx", None)
            if last_idx is not None and 0 <= last_idx < listbox_size and last_idx != idx:
                try:
                    listbox.itemconfigure(
                        last_idx,
                        background=UITheme.BG_DARK,
                        foreground=UITheme.TEXT_MAIN,
                    )
                except tk.TclError:
                    pass

            if 0 <= idx < listbox_size:
                try:
                    listbox.itemconfigure(
                        idx,
                        background=UITheme.STEP_PENDING_BG,
                        foreground=UITheme.STEP_PENDING_FG,
                    )
                    self.app.last_active_step_idx = idx
                    listbox.see(idx)
                except tk.TclError:
                    pass

        self.app.run_on_ui_thread(highlight)

    def highlight_active_periodic_task(self, idx):
        def highlight():
            if self.app.is_closing:
                return
            if hasattr(self.app, "periodic_listbox") and hasattr(
                self.app.periodic_listbox, "highlight_active_task"
            ):
                self.app.periodic_listbox.highlight_active_task(idx)

        self.app.run_on_ui_thread(highlight)

    def clear_active_periodic_task_highlight(self):
        def clear():
            if self.app.is_closing:
                return
            if hasattr(self.app, "periodic_listbox") and hasattr(
                self.app.periodic_listbox, "clear_active_highlight"
            ):
                self.app.periodic_listbox.clear_active_highlight()

        self.app.run_on_ui_thread(clear)
