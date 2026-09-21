"""原子 JSON 快照；Windows 读句柄短暂占用时只重试文件发布，不重试动作。"""
from pathlib import Path
import json
import time
from uuid import uuid4


def read_json_snapshot(path):
    # 先关闭文件再解析，缩短占用时间；读到的字节始终属于同一已发布版本。
    data = Path(path).read_bytes()
    return json.loads(data.decode("utf-8"))


def write_json_snapshot(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    deadline = time.monotonic() + .5
    while True:
        try:
            temporary.replace(path)
            return
        except OSError as error:
            # 仅覆盖 Windows 的短时占用；持久权限错误到期抛出，保留临时文件供诊断。
            if getattr(error, "winerror", None) not in {5, 32, 33} or time.monotonic() >= deadline:
                raise
            time.sleep(.01)
