"""命令行入口：python3 -m review [records] [annotations] [--json]"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .annotations import load_statements
from .engine import evaluate
from .model import Ledger
from .report import render


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python3 -m review", description="寒区文字试车记录复核")
    parser.add_argument("records", nargs="?", default="data/records.json",
                        help="台账路径（默认 data/records.json）")
    parser.add_argument("annotations", nargs="?", default="data/annotations.json",
                        help="解读层路径（默认 data/annotations.json）")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args(argv)

    ledger = Ledger.load(args.records)
    statements = load_statements(args.annotations, ledger)
    result = evaluate(ledger, statements)
    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print(render(ledger, statements, result))


if __name__ == "__main__":
    main()
