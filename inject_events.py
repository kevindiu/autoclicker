import re
import os

with open('/Users/kevindiu/go/src/github.com/kevindiu/autoclicker/controllers.py', 'r', encoding='utf-8') as f:
    ctrl_content = f.read()

with open('/Users/kevindiu/go/src/github.com/kevindiu/autoclicker/autoclicker.py', 'r', encoding='utf-8') as f:
    app_content = f.read()

# I am going to dynamically insert EventBus.subscribe into the __init__ of App in autoclicker.py
# and add the handlers. Since controllers.py is so big and moving methods might break lots of things, 
# a safer refactoring is:
# 1. Leave the UI manipulating logic in controllers.py, BUT decouple it by making the controllers subscribe to EventBus.
# Wait! No, controllers shouldn't manipulate UI directly. The UI manipulating logic belongs to the View (App).
# Let's extract the methods using a script.

# This approach is getting complicated. I will just use sed to do targeted replacements for the most critical parts, or manually move them.
# Let's just fix the event dispatching first in autoclicker.py.

if 'from events import EventBus, AppEvents' not in app_content:
    app_content = app_content.replace('import state', 'from events import EventBus, AppEvents\nimport state')

# In App.__init__, add EventBus subscriptions.
sub_code = """
        # EventBus Subscriptions
        EventBus.subscribe(AppEvents.VARS_CHANGED, self._on_vars_changed)
        EventBus.subscribe(AppEvents.COMBOS_CHANGED, self._on_combos_changed)
        EventBus.subscribe(AppEvents.COMBO_ACTIONS_CHANGED, self._on_combo_actions_changed)
        EventBus.subscribe(AppEvents.STEPS_CHANGED, self._on_steps_changed)
        EventBus.subscribe(AppEvents.PERIODIC_TASKS_CHANGED, self._on_periodic_tasks_changed)
        EventBus.subscribe(AppEvents.STATUS_MESSAGE, self.set_status)
        EventBus.subscribe(AppEvents.LOG_MESSAGE, self.append_log)
"""
if 'EventBus.subscribe' not in app_content:
    app_content = app_content.replace('self.poll_ui_queues()', f'self.poll_ui_queues()\n{sub_code}')

handlers = """
    def _on_vars_changed(self, select_name=None):
        self.var_ctrl.refresh_variables_table(select_name)
    def _on_combos_changed(self, select_idx=None):
        self.combo_ctrl.refresh_combo_list(select_idx)
    def _on_combo_actions_changed(self, select_idx=None):
        self.combo_ctrl.refresh_combo_actions_list(select_idx)
    def _on_steps_changed(self, select_idx=None):
        self.step_ctrl.update_step_list(select_idx)
    def _on_periodic_tasks_changed(self, select_idx=None):
        self.periodic_ctrl.update_periodic_list(select_idx)
"""
if '_on_vars_changed' not in app_content:
    app_content = app_content.replace('    def on_close(self):', f'{handlers}\n    def on_close(self):')

with open('/Users/kevindiu/go/src/github.com/kevindiu/autoclicker/autoclicker.py', 'w', encoding='utf-8') as f:
    f.write(app_content)
