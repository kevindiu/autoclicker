from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Variable:
    type: str  # 'coord', 'key', 'wait'
    value: Any

    def to_dict(self) -> dict:
        return {"type": self.type, "value": self.value}

    @staticmethod
    def from_dict(data: dict) -> 'Variable':
        if not data:
            return Variable(type="coord", value={"x": 0, "y": 0, "btn": "left", "rel": True})

        v_type = data.get("type", "coord")
        raw_val = data.get("value")

        if v_type == "coord":
            if isinstance(raw_val, dict):
                value = {
                    "x": _safe_int(raw_val.get("x", 0)),
                    "y": _safe_int(raw_val.get("y", 0)),
                    "btn": str(raw_val.get("btn", "left")),
                    "rel": bool(raw_val.get("rel", True))
                }
            else:
                value = {"x": 0, "y": 0, "btn": "left", "rel": True}
        elif v_type == "key":
            value = str(raw_val) if raw_val is not None else ""
        elif v_type == "wait":
            try:
                value = float(raw_val)
            except (ValueError, TypeError):
                value = 1.0
        else:
            value = raw_val

        return Variable(type=v_type, value=value)

@dataclass
class Action:
    type: str
    var_name: Optional[str] = None

    def to_dict(self) -> dict:
        data = {"type": self.type, "var_name": self.var_name}
        for key, value in self.__dict__.items():
            if key not in {"type", "var_name"} and value is not None:
                data[key] = value
        return data

    @staticmethod
    def from_dict(data: dict) -> Optional['Action']:
        if not data:
            return None
        act_type = data.get("type")
        var_name = data.get("var_name")

        handlers = {
            "click": lambda d: ClickAction(
                var_name=var_name,
                x=_safe_int(d.get("x", 0)),
                y=_safe_int(d.get("y", 0)),
                btn=d.get("btn", "left"),
                rel=bool(d.get("rel", True))
            ),
            "key": lambda d: KeyAction(
                var_name=var_name,
                key=str(d.get("key", ""))
            ),
            "wait": lambda d: WaitAction(
                var_name=var_name,
                sec=_safe_float(d.get("sec", 0.0))
            ),
            "call_combo": lambda d: CallComboAction(
                var_name=var_name,
                target_name=str(d.get("target_name", ""))
            ),
            "combo": lambda d: ComboAction(
                var_name=var_name,
                name=str(d.get("name", "")),
                actions=[Action.from_dict(a) for a in d.get("actions", []) if a]
            )
        }

        handler = handlers.get(act_type)
        if handler:
            return handler(data)
        return Action(type=str(act_type), var_name=var_name)

@dataclass
class ClickAction(Action):
    type: str = "click"
    x: int = 0
    y: int = 0
    btn: str = "left"
    rel: bool = True

@dataclass
class KeyAction(Action):
    type: str = "key"
    key: str = ""

@dataclass
class WaitAction(Action):
    type: str = "wait"
    sec: float = 0.0

@dataclass
class CallComboAction(Action):
    type: str = "call_combo"
    target_name: str = ""

@dataclass
class ComboAction(Action):
    type: str = "combo"
    name: str = ""
    actions: List[Action] = field(default_factory=list)

@dataclass
class Combo:
    name: str
    actions: List[Action] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "actions": [a.to_dict() if hasattr(a, "to_dict") else a for a in self.actions],
        }

    @staticmethod
    def from_dict(data: dict) -> 'Combo':
        return Combo(
            name=str(data.get("name", "")),
            actions=[Action.from_dict(a) for a in data.get("actions", []) if a]
        )

@dataclass
class PeriodicTask:
    id: str
    name: str
    trigger_mode: str = "interval"
    interval: float = 1.0
    round_interval: int = 1
    enabled: bool = True
    run_on_start: bool = False
    action: Optional[Action] = None
    last_run: float = 0.0
    last_run_round: int = 0

    def to_dict(self) -> dict:
        payload = {
            "id": self.id,
            "name": self.name,
            "trigger_mode": self.trigger_mode,
            "interval": self.interval,
            "round_interval": self.round_interval,
            "enabled": self.enabled,
            "run_on_start": self.run_on_start,
            "last_run": self.last_run,
            "last_run_round": self.last_run_round,
        }
        if self.action is not None:
            payload["action"] = self.action.to_dict() if hasattr(self.action, "to_dict") else self.action
        return payload

    @staticmethod
    def from_dict(data: dict) -> 'PeriodicTask':
        return PeriodicTask(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            trigger_mode=str(data.get("trigger_mode", "interval")),
            interval=_safe_float(data.get("interval", 1.0), default=1.0),
            round_interval=_safe_int(data.get("round_interval", 1), default=1),
            enabled=bool(data.get("enabled", True)),
            run_on_start=bool(data.get("run_on_start", False)),
            action=Action.from_dict(data.get("action", {})) if data.get("action") else None,
            last_run=_safe_float(data.get("last_run", 0.0), default=0.0),
            last_run_round=_safe_int(data.get("last_run_round", 0), default=0),
        )
