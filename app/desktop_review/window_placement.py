"""首次显示时保持窗口完整落在当前逻辑工作区。"""


def fit_initial_window(window):
    screen = window.screen()
    if screen is None or window.isMaximized() or window.isFullScreen():
        return
    available = screen.availableGeometry().adjusted(8, 8, -8, -8)
    frame = window.frameGeometry()
    # Qt 工作区与窗口尺寸都是逻辑像素，勿再次乘屏幕缩放率。
    decoration_width = max(0, frame.width() - window.width())
    decoration_height = max(0, frame.height() - window.height())
    window.resize(min(window.width(), max(1, available.width() - decoration_width)),
                  min(window.height(), max(1, available.height() - decoration_height)))
    frame = window.frameGeometry()
    x = max(available.left(), min(frame.left(), available.right() - frame.width() + 1))
    y = max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1))
    window.move(x, y)
