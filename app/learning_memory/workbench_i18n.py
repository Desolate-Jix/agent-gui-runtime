"""工作台显式文案绑定；语言切换不重新读取库或执行动作。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import weakref

from PySide6.QtCore import QEvent, QObject, QLocale, QStandardPaths, QTranslator, Signal
from PySide6.QtWidgets import QApplication, QLabel
from shiboken6 import isValid

_manager = None
_bindings = {}
_RESOURCES = Path(__file__).with_name("translations")


class LocalizedText(str):
    def __new__(cls, source, values=None):
        obj = str.__new__(cls, _render(source, values or {}))
        obj.source, obj.values = source, values or {}
        return obj

    def render(self):
        return _render(self.source, self.values)

    def __add__(self, other):
        return tr("{left}{right}", left=self, right=other)

    def __radd__(self, other):
        return tr("{left}{right}", left=other, right=self)


class JoinedText(LocalizedText):
    def __new__(cls, separator, values):
        parts = tuple(values)
        obj = str.__new__(cls, str(separator).join(str(value) for value in parts))
        obj.separator, obj.parts = separator, parts
        return obj

    def render(self):
        separator = self.separator.render() if isinstance(self.separator, LocalizedText) else self.separator
        return separator.join(value.render() if isinstance(value, LocalizedText) else str(value) for value in self.parts)


def _render(source, values):
    text = QApplication.translate("Workbench", source) if QApplication.instance() else source
    return text.format(**{key: value.render() if isinstance(value, LocalizedText) else value
                          for key, value in values.items()}) if values else text


def tr(source, **values):
    if isinstance(source, LocalizedText):
        if not values:
            return source
        return LocalizedText(source.source, {**source.values, **values})
    if not isinstance(source, str):
        return source
    return LocalizedText(source, values)


def _update_binding(key, *, initial=False):
    reference, setter, prefix, text, previous = _bindings[key]
    owner = reference()
    if owner is None or not isValid(owner):
        _bindings.pop(key, None)
        return
    getters = {"setText": "text", "setWindowTitle": "windowTitle", "setToolTip": "toolTip",
               "setAccessibleName": "accessibleName", "setPlaceholderText": "placeholderText",
               "setPlainText": "toPlainText",
               "setLabelText": "labelText",
               "setSuffix": "suffix",
               "setTitle": "title", "showMessage": "currentMessage", "setItemText": "itemText",
               "setTabText": "tabText"}
    getter = getters.get(setter)
    if not initial and getter and getattr(owner, getter)(*prefix) != previous:
        # 外部已清除状态或装入用户内容时，旧显示绑定不得覆盖它。
        _bindings.pop(key, None)
        return
    blocked = owner.blockSignals(True) if hasattr(owner, "blockSignals") else None
    try:
        rendered = text.render()
        getattr(owner, setter)(*prefix, rendered)
        _bindings[key] = (reference, setter, prefix, text, rendered)
    finally:
        if blocked is not None:
            owner.blockSignals(blocked)


def bind_text(owner, setter, source, *setter_args, **values):
    text = source if isinstance(source, LocalizedText) else tr(source, **values)
    key = (id(owner), setter, tuple(setter_args))
    _bindings[key] = (weakref.ref(owner), setter, setter_args, text, None)
    _update_binding(key, initial=True)
    return owner


def bound_text(owner, setter="setText", *setter_args):
    binding = _bindings.get((id(owner), setter, tuple(setter_args)))
    return binding[3] if binding else owner.text(*setter_args)


def user_text(callable_, *args, **kwargs):
    """装入用户文字时明确解除旧界面标签绑定，包括文字恰好相同的情况。"""
    owner = callable_.__self__
    setter = callable_.__name__
    prefix = tuple(args[:-1]) if setter in {'setText', 'setItemText', 'setTabText'} else ()
    _bindings.pop((id(owner), setter, prefix), None)
    return callable_(*args, **kwargs)


def join_text(separator, values):
    return JoinedText(separator, values)


def translated_dialog(callable_, parent, title, message, *args, **kwargs):
    """只绑定本次应用弹窗的标题和提示；原生文件选择器不经过此入口。"""
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    class DialogBinding(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Show and watched.parent() is parent:
                if isinstance(watched, QMessageBox):
                    self.dialog = watched
                    bind_text(watched, 'setWindowTitle', title)
                    bind_text(watched, 'setText', message)
                elif isinstance(watched, QInputDialog):
                    self.dialog = watched
                    bind_text(watched, 'setWindowTitle', title)
                    bind_text(watched, 'setLabelText', message)
            return False
    application = QApplication.instance()
    observer = DialogBinding()
    application.installEventFilter(observer)
    try:
        return callable_(parent, title, message, *args, **kwargs)
    finally:
        application.removeEventFilter(observer)


def ui(callable_, *args, **kwargs):
    """只用于明确的显示文字调用，不处理控件树或用户资产。"""
    owner = getattr(callable_, "__self__", None)
    name = getattr(callable_, "__name__", "")
    positions = {"setText": -1, "setWindowTitle": 0, "setToolTip": 0,
                 "setAccessibleName": 0, "setPlaceholderText": 0, "setTitle": 0, "setItemText": -1,
                 "showMessage": 0, "setPlainText": 0, "addItem": 0, "addRow": 0, "addTab": -1,
                 "addMenu": 0, "addAction": -1}
    if owner is None:
        widget = callable_(*args, **kwargs)
        if args and isinstance(args[0], str):
            bind_text(widget, "setText" if hasattr(widget, "setText") else "setTitle", args[0])
        return widget
    if name == "addRow" and args and isinstance(args[0], str):
        label = ui(QLabel, args[0])
        return callable_(label, *args[1:], **kwargs)
    if name == "addItems":
        for text in args[0]:
            ui(owner.addItem, text)
        return None
    if name == "insertItem" and len(args) >= 2 and isinstance(args[1], str):
        result = callable_(*args, **kwargs)
        bind_text(owner, "setItemText", args[1], args[0])
        return result
    if name == "setHeaderLabels":
        result = callable_([str(value) for value in args[0]])
        for index, text in enumerate(args[0]):
            bind_text(owner.headerItem(), "setText", text, index)
        return result
    if name == "setHorizontalHeaderLabels":
        result = callable_([str(value) for value in args[0]])
        for index, text in enumerate(args[0]):
            bind_text(owner.horizontalHeaderItem(index), "setText", text)
        return result
    result = callable_(*args, **kwargs)
    if name == "addItem" and args and isinstance(args[0], str):
        bind_text(owner, "setItemText", args[0], owner.count() - 1)
    elif name == "addTab" and isinstance(args[-1], str):
        bind_text(owner, "setTabText", args[-1], result)
    elif name in {"addMenu", "addAction"}:
        text = next((arg for arg in args if isinstance(arg, str)), None)
        if text is not None:
            bind_text(result, "setTitle" if name == "addMenu" else "setText", text)
    elif name in positions:
        position = positions[name]
        if args and isinstance(args[position], str):
            bind_text(owner, name, args[position], *args[:position] if position == -1 else ())
    return result


class LanguageManager(QObject):
    languageChanged = Signal(str)

    def __init__(self, application, preferences_path, system_locale=None):
        super().__init__(application)
        self.application = application
        self.preferences_path = Path(preferences_path)
        self.translator = QTranslator(self)
        self.language = ""
        locale = (system_locale or QLocale.system().name()).replace("_", "-")
        language = "zh-CN" if locale in {"zh-CN", "zh-Hans", "zh-Hans-CN"} else "en-US"
        if self.preferences_path.exists():
            try:
                value = json.loads(self.preferences_path.read_text(encoding="utf-8"))
                if not isinstance(value, dict) or set(value) != {"language"} or value["language"] not in {"zh-CN", "en-US"}:
                    raise ValueError("expected language zh-CN or en-US")
                language = value["language"]
            except (ValueError, OSError) as error:
                raise ValueError(f"Invalid workbench language preferences: {self.preferences_path}: {error}") from error
        self.set_language(language, persist=False)

    def set_language(self, language, *, persist=True):
        if language not in {"zh-CN", "en-US"}:
            raise ValueError(f"Unsupported workbench language: {language}")
        replacement = QTranslator(self) if self.language != language else None
        if replacement is not None and not replacement.load(str(_RESOURCES / (language + ".qm"))):
            raise RuntimeError(f"Cannot load workbench translation resource: {language}")
        if persist:
            self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.preferences_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps({"language": language}, ensure_ascii=False) + "\n", encoding="utf-8")
            temporary.replace(self.preferences_path)
        if self.language == language:
            return
        previous_translator = self.translator
        self.application.removeTranslator(previous_translator)
        self.translator = replacement
        previous_translator.deleteLater()
        self.application.installTranslator(replacement)
        self.language = language
        for key in list(_bindings):
            _update_binding(key)
        self.application.sendPostedEvents(None, QEvent.Type.LanguageChange)
        self.languageChanged.emit(language)


def initialize_i18n(application, preferences_path=None, system_locale=None):
    global _manager
    if _manager is not None and _manager.application is application and (preferences_path is None or _manager.preferences_path == Path(preferences_path)):
        return _manager
    previous = _manager
    path = preferences_path or Path(os.environ.get("LOCALAPPDATA") or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation)) / "AgentGUIRuntime" / "workbench-preferences.json"
    _manager = LanguageManager(application, path, system_locale)
    if previous is not None:
        application.removeTranslator(previous.translator)
    return _manager


def language_manager():
    return _manager
