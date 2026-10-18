#!/usr/bin/env python3
"""Compare two frozen persona run directories without contacting a service."""
import argparse
from importlib import import_module
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
report = import_module('evaluation.persona-ux.report')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--output', type=Path, help='Markdown path under evaluation/')
    args = parser.parse_args(argv)
    if args.output and not args.output.resolve().is_relative_to((ROOT / 'evaluation').resolve()):
        parser.error('--output 必须位于 evaluation/ 下')
    try:
        markdown = report.render_comparison([report.load_run(args.before), report.load_run(args.after)])
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(markdown, encoding='utf-8')
        else:
            print(markdown, end='')
    except (ValueError, OSError) as error:
        parser.error(type(error).__name__)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
