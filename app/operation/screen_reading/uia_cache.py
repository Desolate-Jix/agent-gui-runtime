"""单次 UIA 扫描的原生属性缓存；不缓存跨帧目标或代替真实 pattern。"""
from math import isfinite
from types import SimpleNamespace


ACQUISITION_MODE = "native_cache_per_parent.v1"
_PROPERTIES = (
    "RuntimeId", "ProcessId", "FrameworkId", "NativeWindowHandle", "Name", "ControlType",
    "AutomationId", "ClassName", "BoundingRectangle", "IsEnabled", "IsOffscreen", "IsPassword",
    "IsKeyboardFocusable", "HasKeyboardFocus", "ScrollVerticallyScrollable", "ScrollHorizontallyScrollable",
    *["Is" + name + "PatternAvailable" for name in
      ("Invoke", "Value", "Text", "Selection", "SelectionItem", "ExpandCollapse", "Toggle", "Scroll")],
)
_INTERFACES = {
    "iface_invoke": "Invoke", "iface_value": "Value", "iface_text": "Text",
    "iface_selection": "Selection", "iface_selection_item": "SelectionItem",
    "iface_expand_collapse": "ExpandCollapse", "iface_toggle": "Toggle", "iface_scroll": "Scroll",
}
_UNREAD = object()
_REQUIRED_PROPERTIES = ("RuntimeId", "ProcessId", "ControlType", "BoundingRectangle", "IsEnabled", "IsOffscreen")


class UIACacheError(RuntimeError):
    def __init__(self, reason, *, field=None, error=None):
        self.reason = reason
        self.field = field
        self.error_type = type(error).__name__ if error is not None else None
        self.hresult = getattr(error, "hresult", None)
        super().__init__(reason + (":" + field if field else ""))

    def to_dict(self):
        return {"reason": self.reason,
                **({"property": self.field} if self.field else {}),
                **({"error_type": self.error_type} if self.error_type else {}),
                **({"hresult": self.hresult} if type(self.hresult) is int else {})}


def _primitive(value, api):
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and isfinite(value):
        return value
    if type(value) in (tuple, list):
        return tuple(_primitive(child, api) for child in value)
    # 只有 UIA 明确认定的保留值才是 unsupported；不以 COM 对象类型名代替值。
    unsupported = api.iuia.CheckNotSupported(value)
    if type(unsupported) in (bool, int) and unsupported == 1:
        return None
    raise ValueError("unknown_cached_property_value")


def _validate(values, api):
    for key in _REQUIRED_PROPERTIES:
        if values[key] is None:
            raise UIACacheError("cached_property_unavailable", field=key)
    rid = values["RuntimeId"]
    if (type(rid) is not tuple or not 1 <= len(rid) <= 64
            or any(type(item) is not int for item in rid)):
        raise UIACacheError("cached_property_invalid", field="RuntimeId")
    if type(values["ProcessId"]) is not int or values["ProcessId"] <= 0:
        raise UIACacheError("cached_property_invalid", field="ProcessId")
    kind = values["ControlType"]
    if type(kind) is not int or kind <= 0 or kind not in api.known_control_type_ids:
        raise UIACacheError("cached_property_invalid", field="ControlType")
    for key in ("Name", "AutomationId", "ClassName", "FrameworkId"):
        if values[key] is not None and type(values[key]) is not str:
            raise UIACacheError("cached_property_invalid", field=key)
    handle = values["NativeWindowHandle"]
    if handle is not None and (type(handle) is not int or handle < 0):
        raise UIACacheError("cached_property_invalid", field="NativeWindowHandle")
    box = values["BoundingRectangle"]
    if (type(box) is not tuple or len(box) != 4
            or any(type(item) not in (int, float) or not isfinite(item) for item in box)):
        raise UIACacheError("cached_property_invalid", field="BoundingRectangle")
    for key in _PROPERTIES[9:]:
        value = values[key]
        if value is not None and (type(value) not in (bool, int) or value not in (0, 1)):
            raise UIACacheError("cached_property_invalid", field=key)


def _read_native_pattern(element, name):
    from pywinauto.uia_defines import NoPatternInterfaceError, pattern_ids

    pattern_id, interface = pattern_ids[name]
    # 不使用会把所有 COMError 变成“不支持”的包装；失效、拒绝访问等异常必须上报。
    unknown = element.GetCurrentPattern(pattern_id)
    if not unknown:
        raise NoPatternInterfaceError()
    resolved = unknown.QueryInterface(interface)
    if not resolved:
        raise NoPatternInterfaceError()
    return resolved


class NativeUIACache:
    def __init__(self, *, api=None, wrap=None, read_pattern=None, no_pattern_error=None):
        if api is None:
            from pywinauto.uia_defines import IUIA
            api = IUIA()
        if wrap is None:
            from pywinauto.controls.uiawrapper import UIAWrapper
            from pywinauto.uia_element_info import UIAElementInfo
            wrap = lambda element: UIAWrapper(UIAElementInfo(element))
        if read_pattern is None or no_pattern_error is None:
            from pywinauto.uia_defines import NoPatternInterfaceError
            read_pattern = read_pattern or _read_native_pattern
            no_pattern_error = no_pattern_error or NoPatternInterfaceError
        self.api, self.wrap = api, wrap
        self.read_pattern, self.no_pattern_error = read_pattern, no_pattern_error
        self.by_name_type, self.by_runtime_id = {}, {}
        self.root_wrapper = None
        try:
            self.properties = {name: getattr(api.UIA_dll, "UIA_" + name + "PropertyId") for name in _PROPERTIES}
            self.request = api.iuia.CreateCacheRequest()
            self.request.TreeScope = api.tree_scope["element"]
            self.request.TreeFilter = api.iuia.ControlViewCondition
            # 保留真实 COM element；缓存属性不充当 pattern 接口或动作授权。
            self.request.AutomationElementMode = 1
            for property_id in self.properties.values():
                self.request.AddProperty(property_id)
        except Exception as error:
            raise UIACacheError("cache_request_failed", error=error) from error

    def root(self, wrapper):
        if self.root_wrapper is not None:
            raise UIACacheError("cache_root_already_bound")
        try:
            element = wrapper.element_info.element.BuildUpdatedCache(self.request)
        except Exception as error:
            raise UIACacheError("cache_root_acquisition_failed", error=error) from error
        self.root_wrapper = self._materialize(element, live=wrapper)
        return self.root_wrapper

    def _materialize(self, element, *, live=None):
        values = {}
        for name, property_id in self.properties.items():
            try:
                values[name] = _primitive(element.GetCachedPropertyValueEx(property_id, True), self.api)
            except Exception as error:
                raise UIACacheError("cached_property_read_failed", field=name, error=error) from error
        _validate(values, self.api)
        try:
            node = CachedUIAWrapper(self, live if live is not None else self.wrap(element), values)
        except Exception as error:
            raise UIACacheError("cached_element_materialization_failed", error=error) from error
        self.by_name_type.setdefault((values["Name"], node.element_info.control_type), []).append(node)
        self.by_runtime_id.setdefault(values["RuntimeId"], []).append(node)
        return node


class _CachedChildren:
    def __init__(self, cache, array):
        self.cache, self.array, self.nodes, self.errors = cache, array, {}, {}
        self.length = int(array.Length)
        if self.length < 0:
            raise UIACacheError("cached_children_length_invalid")

    def __len__(self):
        return self.length

    def __getitem__(self, index):
        if not 0 <= index < self.length:
            raise IndexError(index)
        if index in self.errors:
            raise self.errors[index]
        if index not in self.nodes:
            try:
                self.nodes[index] = self.cache._materialize(self.array.GetElement(index))
            except UIACacheError as error:
                self.errors[index] = error
                raise
            except Exception as error:
                self.errors[index] = UIACacheError("cached_child_acquisition_failed", error=error)
                raise self.errors[index] from error
        return self.nodes[index]


class _CachedInfo:
    def __init__(self, node):
        values = node.values
        self.node = node
        self.element = node.live_wrapper.element_info.element
        self.runtime_id, self.process_id = values["RuntimeId"], values["ProcessId"]
        self.control_type = node.cache.api.known_control_type_ids[values["ControlType"]]
        self.name, self.automation_id = values["Name"], values["AutomationId"]
        self.class_name, self.framework_id = values["ClassName"], values["FrameworkId"]
        self.handle = values["NativeWindowHandle"]

    @property
    def rich_text(self):
        return self.node.window_text()


class CachedUIAWrapper:
    def __init__(self, cache, live, values):
        self.cache, self.live_wrapper, self.values = cache, live, values
        self.element_info = _CachedInfo(self)
        self.cache_errors, self._interfaces = [], {}
        self._children, self._text = _UNREAD, _UNREAD
        self._children_error, self._text_error = None, None

    def cached_children(self):
        if self._children_error is not None:
            raise self._children_error
        if self._children is _UNREAD:
            try:
                # 保持生产遍历的有限直接子数组，不在取得属性时提前遍历整棵树。
                array = self.element_info.element.FindAllBuildCache(self.cache.api.tree_scope["children"],
                    self.cache.api.true_condition, self.cache.request)
                self._children = _CachedChildren(self.cache, array)
            except UIACacheError as error:
                self._children_error = error
                raise
            except Exception as error:
                self._children_error = UIACacheError("cached_children_acquisition_failed", error=error)
                raise self._children_error from error
        return self._children

    def __getattr__(self, name):
        if name not in _INTERFACES:
            return getattr(self.live_wrapper, name)
        if name not in self._interfaces:
            try:
                pattern = _INTERFACES[name]
                available = self.values["Is" + pattern + "PatternAvailable"]
                if available is not None and not bool(available):
                    raise self.cache.no_pattern_error()
                self._interfaces[name] = self.cache.read_pattern(self.element_info.element, pattern)
            except self.cache.no_pattern_error as error:
                self._interfaces[name] = error
            except Exception as error:
                self.cache_errors.append({**UIACacheError("cached_interface_read_failed", error=error).to_dict(),
                                          "pattern": _INTERFACES[name]})
                self._interfaces[name] = error
        value = self._interfaces[name]
        if isinstance(value, Exception):
            raise value
        return value

    def rectangle(self):
        x, y, width, height = self.values["BoundingRectangle"]
        return SimpleNamespace(left=int(x), top=int(y), right=int(x + width), bottom=int(y + height))

    def window_text(self):
        if self._text_error is not None:
            raise self._text_error
        if self._text is _UNREAD:
            if not self.element_info.class_name:
                self._text = self.element_info.name
            else:
                try:
                    self._text = self.iface_text.DocumentRange.GetText(-1)
                    if self._text is not None and type(self._text) is not str:
                        raise TypeError("invalid_rich_text_value")
                except self.cache.no_pattern_error:
                    self._text = self.element_info.name
                except Exception as error:
                    if not any(item.get("pattern") == "Text" for item in self.cache_errors):
                        self.cache_errors.append(UIACacheError("cached_rich_text_read_failed", error=error).to_dict())
                    self._text_error = UIACacheError("cached_rich_text_read_failed", error=error)
                    raise self._text_error from error
        return self._text

    def friendly_class_name(self):
        return self.element_info.control_type

    def class_name(self):
        return self.element_info.class_name

    def is_enabled(self):
        value = self.values["IsEnabled"]
        return None if value is None else bool(value)

    def is_visible(self):
        value = self.values["IsOffscreen"]
        return None if value is None else not bool(value)

    def parent(self):
        try:
            return self.live_wrapper.parent()
        except Exception as error:
            self.cache_errors.append(UIACacheError("cached_parent_read_failed", error=error).to_dict())
            raise

    def scroll_axes(self):
        return {"current_" + axis: None if self.values[key] is None else bool(self.values[key])
                for axis, key in (("vertical", "ScrollVerticallyScrollable"),
                                  ("horizontal", "ScrollHorizontallyScrollable"))}


def cached_root(wrapper):
    try:
        element = getattr(getattr(wrapper, "element_info", None), "element", None)
        # 非 COM 的注入适配器沿用原契约；真实 UIA element 的缓存异常不得退回 Current 属性。
        if element is None or not callable(getattr(element, "BuildUpdatedCache", None)):
            if type(wrapper).__module__.startswith("pywinauto."):
                raise UIACacheError("cache_capability_unavailable")
            return wrapper
        return NativeUIACache().root(wrapper)
    except UIACacheError:
        raise
    except Exception as error:
        raise UIACacheError("cache_initialization_failed", error=error) from error


def cached_graph_identity(wrapper, read_identity):
    if not isinstance(wrapper, CachedUIAWrapper):
        return read_identity(wrapper)
    try:
        identity = read_identity(wrapper.live_wrapper)
    except Exception as error:
        raise UIACacheError("cache_live_identity_unavailable", error=error) from error
    if identity[:5] != (wrapper.element_info.runtime_id, wrapper.element_info.process_id,
            wrapper.element_info.control_type, wrapper.element_info.framework_id, wrapper.element_info.handle):
        raise UIACacheError("cached_identity_changed")
    return identity
