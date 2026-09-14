import re

with open('/Users/kevindiu/go/src/github.com/kevindiu/autoclicker/controllers.py', 'r', encoding='utf-8') as f:
    content = f.read()

if 'from events import EventBus, AppEvents' not in content:
    content = content.replace('import state', 'from events import EventBus, AppEvents\nimport state')

replacements = [
    (r'self\.app\.set_status\((.*?)\)', r'EventBus.emit(AppEvents.STATUS_MESSAGE, \1)'),
    (r'self\.app\.append_log\((.*?)\)', r'EventBus.emit(AppEvents.LOG_MESSAGE, \1)'),
    
    (r'self\.app\.refresh_variables_table\((.*?)\)', r'EventBus.emit(AppEvents.VARS_CHANGED, \1)'),
    (r'self\.app\.refresh_combo_list\((.*?)\)', r'EventBus.emit(AppEvents.COMBOS_CHANGED, \1)'),
    (r'self\.app\.refresh_combo_actions_list\((.*?)\)', r'EventBus.emit(AppEvents.COMBO_ACTIONS_CHANGED, \1)'),
    (r'self\.app\.update_step_list\((.*?)\)', r'EventBus.emit(AppEvents.STEPS_CHANGED, \1)'),
    (r'self\.update_step_list\((.*?)\)', r'EventBus.emit(AppEvents.STEPS_CHANGED, \1)'),
    (r'self\.app\.update_periodic_list\((.*?)\)', r'EventBus.emit(AppEvents.PERIODIC_TASKS_CHANGED, \1)'),
    (r'self\.update_periodic_list\((.*?)\)', r'EventBus.emit(AppEvents.PERIODIC_TASKS_CHANGED, \1)'),
    
    (r'self\.app\.sync_combo_actions_to_main_steps\((.*?)\)', r'self.sync_combo_actions_to_main_steps(\1)'),
]

for pattern, repl in replacements:
    content = re.sub(pattern, repl, content)

with open('/Users/kevindiu/go/src/github.com/kevindiu/autoclicker/controllers.py', 'w', encoding='utf-8') as f:
    f.write(content)
