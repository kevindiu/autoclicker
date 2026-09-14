import threading

class EventBus:
    """簡單且執行緒安全的發布/訂閱 (Pub/Sub) 系統"""
    _subscribers = {}
    _lock = threading.Lock()

    @classmethod
    def subscribe(cls, event_type, callback):
        with cls._lock:
            if event_type not in cls._subscribers:
                cls._subscribers[event_type] = []
            if callback not in cls._subscribers[event_type]:
                cls._subscribers[event_type].append(callback)

    @classmethod
    def unsubscribe(cls, event_type, callback):
        with cls._lock:
            if event_type in cls._subscribers:
                if callback in cls._subscribers[event_type]:
                    cls._subscribers[event_type].remove(callback)

    @classmethod
    def emit(cls, event_type, *args, **kwargs):
        with cls._lock:
            subs = cls._subscribers.get(event_type, []).copy()
        
        for callback in subs:
            try:
                callback(*args, **kwargs)
            except Exception as e:
                print(f"[EventBus] Error executing callback for event '{event_type}': {e}")


class AppEvents:
    """定義全域事件常數"""
    VARS_CHANGED = "VARS_CHANGED"
    COMBOS_CHANGED = "COMBOS_CHANGED"
    COMBO_ACTIONS_CHANGED = "COMBO_ACTIONS_CHANGED"
    STEPS_CHANGED = "STEPS_CHANGED"
    PERIODIC_TASKS_CHANGED = "PERIODIC_TASKS_CHANGED"
    
    STATUS_MESSAGE = "STATUS_MESSAGE"
    LOG_MESSAGE = "LOG_MESSAGE"
    HOT_RELOAD = "HOT_RELOAD"

    HIGHLIGHT_STEP = "HIGHLIGHT_STEP"
    CLEAR_HIGHLIGHT_STEP = "CLEAR_HIGHLIGHT_STEP"
    HIGHLIGHT_PENDING_STEP = "HIGHLIGHT_PENDING_STEP"
    HIGHLIGHT_PERIODIC_TASK = "HIGHLIGHT_PERIODIC_TASK"
    CLEAR_HIGHLIGHT_PERIODIC_TASK = "CLEAR_HIGHLIGHT_PERIODIC_TASK"
    
    MACRO_STOPPED = "MACRO_STOPPED"
