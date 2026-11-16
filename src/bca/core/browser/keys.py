"""Deliberately bounded US logical-key mapping; Unicode uses insertText."""

from dataclasses import dataclass

from bca.core.errors import ValidationError


@dataclass(frozen=True)
class Key:
    key: str
    code: str
    vk: int
    modifier: int = 0
    text: str = ""


_NAMED = {
    "Enter": Key("Enter", "Enter", 13, text="\r"),
    "Tab": Key("Tab", "Tab", 9),
    "Escape": Key("Escape", "Escape", 27),
    "Backspace": Key("Backspace", "Backspace", 8),
    "Delete": Key("Delete", "Delete", 46),
    "ArrowLeft": Key("ArrowLeft", "ArrowLeft", 37),
    "ArrowUp": Key("ArrowUp", "ArrowUp", 38),
    "ArrowRight": Key("ArrowRight", "ArrowRight", 39),
    "ArrowDown": Key("ArrowDown", "ArrowDown", 40),
    "Home": Key("Home", "Home", 36),
    "End": Key("End", "End", 35),
    "PageUp": Key("PageUp", "PageUp", 33),
    "PageDown": Key("PageDown", "PageDown", 34),
    "Shift": Key("Shift", "ShiftLeft", 16, 8),
    "Control": Key("Control", "ControlLeft", 17, 2),
    "Alt": Key("Alt", "AltLeft", 18, 1),
    "Meta": Key("Meta", "MetaLeft", 91, 4),
    " ": Key(" ", "Space", 32, text=" "),
}


def resolve_key(name: str, *, shift: bool = False) -> Key:
    name = {"Ctrl": "Control", "Space": " "}.get(name, name)
    if name in _NAMED:
        return _NAMED[name]
    if len(name) == 1 and name.isascii():
        if name.isalpha():
            value = name.upper() if shift else name
            return Key(value, "Key" + name.upper(), ord(name.upper()), text=value)
        if name.isdigit():
            value = ")!@#$%^&*("[int(name)] if shift else name
            return Key(value, "Digit" + name, ord(name), text=value)
    raise ValidationError("unsupported logical key; use TEXT_INPUT for arbitrary text")
