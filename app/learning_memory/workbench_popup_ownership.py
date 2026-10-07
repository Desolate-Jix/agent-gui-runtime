"""只为当前工作台可证明的 Qt 浮层声明原生窗口关联。"""
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtWidgets import QComboBox, QWidget
from PySide6.QtGui import QGuiApplication, QPlatformSurfaceEvent
from shiboken6 import getCppPointer, isValid
import ctypes
import logging
import weakref

logger = logging.getLogger(__name__)


def _popup_trace(event, *, owner=None, popup=None, handle=None, hook=None, **fields):
    """只读既有对象与内部句柄，不因诊断创建 HWND 或保留 wrapper。"""
    application = QCoreApplication.instance()
    trace = getattr(application, '_workbench_startup_trace', None)
    if trace is None:
        return
    for name, obj in (('owner', owner), ('popup', popup), ('handle', handle), ('hook', hook)):
        fields[name + '_wrapper_id'] = id(obj) if obj is not None else None
        valid = obj is not None and isValid(obj)
        fields[name + '_valid'] = valid
        fields[name + '_cpp'] = int(getCppPointer(obj)[0]) if valid else None
    if popup is not None and isValid(popup):
        fields['popup_internal_hwnd'] = int(popup.internalWinId())
        fields['popup_visible'] = popup.isVisible()
    if owner is not None and isValid(owner):
        fields['owner_internal_hwnd'] = int(owner.internalWinId())
    trace._observe('popup_' + event, **fields)


class WindowsPopupBackend:
    """指针宽度与错误码明确的原生 owner 接口。"""
    def __init__(self):
        from ctypes import wintypes
        self.api = ctypes.WinDLL('user32', use_last_error=True)
        self.api.IsWindow.argtypes = [wintypes.HWND]
        self.api.IsWindow.restype = wintypes.BOOL
        self.api.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        self.api.GetWindow.restype = wintypes.HWND
        self.api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.api.GetAncestor.restype = wintypes.HWND
        self.api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.api.GetWindowThreadProcessId.restype = wintypes.DWORD
        pointer = ctypes.sizeof(ctypes.c_void_p) == 8
        self.get_long = getattr(self.api, 'GetWindowLongPtrW' if pointer else 'GetWindowLongW')
        self.set_long = getattr(self.api, 'SetWindowLongPtrW' if pointer else 'SetWindowLongW')
        self.get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        self.get_long.restype = ctypes.c_ssize_t
        self.set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self.set_long.restype = ctypes.c_ssize_t

    def valid(self, hwnd):
        return bool(self.api.IsWindow(hwnd))

    def identity(self, hwnd):
        from ctypes import wintypes
        process = wintypes.DWORD()
        thread = self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
        return int(thread), int(process.value)

    def style(self, hwnd):
        return self.get_long(hwnd, -16)

    def owner(self, hwnd):
        return int(self.api.GetWindow(hwnd, 4) or 0)

    def root_owner(self, hwnd):
        return int(self.api.GetAncestor(hwnd, 3) or 0)

    def set_owner(self, hwnd, owner):
        ctypes.set_last_error(0)
        previous = self.set_long(hwnd, -8, owner)
        error = ctypes.get_last_error()
        if previous == 0 and error:
            raise ctypes.WinError(error)


def bind_native_popup(owner_hwnd, popup_hwnd, *, backend=None):
    """调用者先证明 Qt 祖先链；此层拒绝错误原生身份与其它 root。"""
    native = backend if backend is not None else WindowsPopupBackend()
    try:
        if (not owner_hwnd or not popup_hwnd or owner_hwnd == popup_hwnd
                or not native.valid(owner_hwnd) or not native.valid(popup_hwnd)):
            raise ValueError('invalid popup/owner HWND')
        identity = native.identity(owner_hwnd)
        if not all(identity) or native.identity(popup_hwnd) != identity:
            raise ValueError('popup PID/thread differs from owner')
        if native.style(popup_hwnd) & 0x40000000:
            raise ValueError('popup is WS_CHILD')
        if native.root_owner(owner_hwnd) != owner_hwnd:
            raise ValueError('main owner has another root')
        previous = native.owner(popup_hwnd)
        _popup_trace('native_bind', stage='before', owner_hwnd=owner_hwnd,
                     popup_hwnd=popup_hwnd, previous_owner=previous,
                     previous_root=native.root_owner(popup_hwnd))
        if previous and native.root_owner(popup_hwnd) != owner_hwnd:
            raise ValueError('popup already belongs to another root')
        native.set_owner(popup_hwnd, owner_hwnd)
        actual_owner, actual_root = native.owner(popup_hwnd), native.root_owner(popup_hwnd)
        _popup_trace('native_bind', stage='after', owner_hwnd=owner_hwnd,
                     popup_hwnd=popup_hwnd, actual_owner=actual_owner, actual_root=actual_root)
        if actual_owner != owner_hwnd or actual_root != owner_hwnd:
            raise ValueError('popup native owner readback mismatch')
        return True
    except (OSError, ValueError) as error:
        _popup_trace('native_bind_rejected', owner_hwnd=owner_hwnd, popup_hwnd=popup_hwnd,
                     error_type=type(error).__name__, error=str(error))
        logger.warning('Qt popup native ownership rejected (popup=%s owner=%s): %s',
                       popup_hwnd, owner_hwnd, error)
        return False


def _proven_popup(owner, widget):
    if (not isinstance(widget, QWidget) or widget is owner or widget.window() is not widget
            or widget.windowType() != Qt.WindowType.Popup):
        return False
    ancestor = widget.parentWidget()
    while ancestor is not None and ancestor is not owner:
        ancestor = ancestor.parentWidget()
    return ancestor is owner


def prepare_owned_popup(owner, widget):
    """只在 HWND 创建前准备阴影标志；不隐藏或重开已有浮层。"""
    if not _proven_popup(owner, widget):
        return False
    hint = Qt.WindowType.NoDropShadowWindowHint
    if widget.windowFlags() & hint:
        return True
    if widget.windowHandle() is not None or widget.isVisible():
        logger.warning('Qt popup shadow preparation rejected: native handle already exists or popup visible')
        return False
    widget.setWindowFlags(widget.windowFlags() | hint)
    return bool(widget.windowFlags() & hint)


def prepare_owned_combo_popup(owner, combo):
    """先证明 combo 归属，再取隐藏私有浮层做创建前准备。"""
    if not isinstance(combo, QComboBox):
        return False
    ancestor = combo.parentWidget()
    while ancestor is not None and ancestor is not owner:
        ancestor = ancestor.parentWidget()
    if ancestor is not owner:
        return False
    return prepare_owned_popup(owner, combo.view().window())


class _PopupLifecycleHook(QObject):
    """QWindow 保留而 HWND 重建时，重新验证当前归属。"""
    def __init__(self, handle, owner, popup):
        super().__init__(handle)
        self.owner_ref = weakref.ref(owner)
        self.popup_ref = weakref.ref(popup)
        self.rechecking = False
        self.surface_destroying = False
        hook_ref = weakref.ref(self)
        def popup_gone(_reference):
            current = hook_ref()
            if current is not None and isValid(current):
                _popup_trace('wrapper_gone', owner=current.owner_ref(), handle=current.parent(), hook=current)
        self.popup_ref = weakref.ref(popup, popup_gone)
        _popup_trace('hook_created', owner=owner, popup=popup, handle=handle, hook=self)

    def recheck(self, *_args):
        _popup_trace('hook_recheck', owner=self.owner_ref(), popup=self.popup_ref(),
                     handle=self.parent(), hook=self, recursive=self.rechecking)
        if self.rechecking:
            return
        owner, popup = self.owner_ref(), self.popup_ref()
        if owner is None or popup is None or not isValid(owner) or not isValid(popup):
            _popup_trace('hook_skipped', hook=self, reason='weakref_missing_or_invalid')
            return
        handle = popup.windowHandle()
        if handle is not self.parent() or not _proven_popup(owner, popup):
            _popup_trace('hook_skipped', owner=owner, popup=popup, handle=handle, hook=self,
                         reason='handle_changed_or_foreign')
            return
        self.rechecking = True
        try:
            associate_owned_popup(owner, popup)
        finally:
            self.rechecking = False

    def visible_changed(self, visible):
        _popup_trace('hook_visible', owner=self.owner_ref(), popup=self.popup_ref(),
                     handle=self.parent(), hook=self, visible=visible)
        if visible:
            self.recheck()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.PlatformSurface:
            self.surface_destroying = event.surfaceEventType() == QPlatformSurfaceEvent.SurfaceEventType.SurfaceAboutToBeDestroyed
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.PlatformSurface):
            _popup_trace('hook_event', owner=self.owner_ref(), popup=self.popup_ref(),
                         handle=watched, hook=self, qt_event=event.type().name,
                         surface_event=event.surfaceEventType().name if event.type() == QEvent.Type.PlatformSurface else None)
        if event.type() == QEvent.Type.Show or (event.type() == QEvent.Type.PlatformSurface
                and event.surfaceEventType() == QPlatformSurfaceEvent.SurfaceEventType.SurfaceCreated):
            self.recheck()
        return False


def associate_owned_popup(owner, widget):
    if not _proven_popup(owner, widget):
        return False
    _popup_trace('associate_enter', owner=owner, popup=widget, handle=widget.windowHandle())
    owner_handle = owner.windowHandle()
    if owner_handle is None:
        return False
    if widget.windowHandle() is None:
        widget.winId()
    popup_handle = widget.windowHandle()
    if popup_handle is None:
        return False
    hook = getattr(popup_handle, '_workbench_lifecycle_hook', None)
    if (hook is not None and hook.surface_destroying) or not owner.internalWinId():
        _popup_trace('associate_skipped', owner=owner, popup=widget, handle=popup_handle,
                     reason='surface_destroying_or_owner_without_native_window')
        return False
    if hook is None and not widget.internalWinId():
        return False
    native = QGuiApplication.platformName() == 'windows'
    # QWidget 可能仍缓存旧 HWND；创建后只读当前 QWindow 的原生身份。
    if native and not bind_native_popup(int(owner_handle.winId()), int(popup_handle.winId())):
        return False
    if getattr(popup_handle, '_workbench_lifecycle_hook', None) is None:
        hook = _PopupLifecycleHook(popup_handle, owner, widget)
        popup_handle.installEventFilter(hook)
        popup_handle.transientParentChanged.connect(hook.recheck)
        popup_handle.visibleChanged.connect(hook.visible_changed)
        popup_handle._workbench_lifecycle_hook = hook
    popup_handle.setTransientParent(owner_handle)
    if popup_handle.transientParent() is not owner_handle:
        logger.warning('Qt popup transient parent readback mismatch')
        return False
    if native:
        return bind_native_popup(int(owner_handle.winId()), int(popup_handle.winId()))
    return True
