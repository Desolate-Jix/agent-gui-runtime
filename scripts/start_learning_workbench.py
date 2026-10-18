"""普通学习工作台启动入口。"""
from pathlib import Path
import sys

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.learning_memory.workbench_launch import main


def entrypoint(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if '--check-image-feature' not in args:
        return main(argv)
    import argparse
    import json
    parser = argparse.ArgumentParser(description='Offline image feature dependency check')
    parser.add_argument('--check-image-feature', required=True, type=Path)
    parsed = parser.parse_args(args)
    try:
        from scripts.check_learning_image_feature import check
        evidence = check()
    except Exception as error:
        evidence = {'passed': False, 'error_type': type(error).__name__, 'error': str(error),
                    'input_executed': False, 'host_started': False}
    evidence['frozen'] = bool(getattr(sys, 'frozen', False))
    evidence['runtime_root'] = str(Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])).resolve())
    parsed.check_image_feature.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(entrypoint())
