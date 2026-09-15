import threading


class EventBus:
    """簡單且執行緒安全的發布/訂閱 (Pub/Sub) 系統。

    支援 scope 隔離，避免跨 app instance 彼此污染訂閱表。
    兼容舊 API：未指定 scope 時，使用預設 scope='default'。
    """
    _subscribers = {}
    _lock = threading.Lock()

    @classmethod
    def _scope_key(cls, scope=None):
        return scope if scope is not None else "default"

    @classmethod
    def subscribe(cls, event_type, callback, scope=None):
        scope_name = cls._scope_key(scope)
        with cls._lock:
            bucket = cls._subscribers.setdefault(event_type, {})
            scope_subs = bucket.setdefault(scope_name, [])
            if callback not in scope_subs:
                scope_subs.append(callback)

    @classmethod
    def unsubscribe(cls, event_type, callback, scope=None):
        scope_name = cls._scope_key(scope)
        with cls._lock:
            bucket = cls._subscribers.get(event_type)
            if not bucket:
                return
            scope_subs = bucket.get(scope_name, [])
            if callback in scope_subs:
                scope_subs.remove(callback)
            if not scope_subs:
                bucket.pop(scope_name, None)
            if not bucket:
                cls._subscribers.pop(event_type, None)

    @classmethod
    def emit(cls, event_type, *args, **kwargs):
        scope = kwargs.pop("scope", "default")
        with cls._lock:
            bucket = cls._subscribers.get(event_type, {})
            subs = []
            for scope_name in (scope, "default"):
                if scope_name in bucket:
                    subs.extend(bucket[scope_name])
            subs = list(dict.fromkeys(subs))

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
