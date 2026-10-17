"""Command line: actual-transfer-linker -c config.yaml [--apply] [--sync]"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import ConfigError, load


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="actual-transfer-linker",
        description="Link the two sides of money moved between your own accounts in Actual Budget as one transfer.")
    ap.add_argument("-c", "--config", default="config.yaml", help="settings file (default: config.yaml)")
    ap.add_argument("--apply", action="store_true", help="write the changes (without it: dry run, nothing is changed)")
    ap.add_argument("--sync", action="store_true", help="run Actual's bank sync first")
    ap.add_argument("-q", "--quiet", action="store_true", help="print nothing when there is nothing to do")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)

    try:
        cfg = load(args.config)
    except (OSError, ConfigError) as e:
        print(f"config: {e}", file=sys.stderr)
        return 2

    from .ledger import run
    try:
        report = run(cfg, dry_run=not args.apply, sync=args.sync)
    except Exception as e:  # noqa: BLE001  (connection, password, sync errors: one line, no traceback)
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    verb = "Linked" if args.apply else "Would link"
    fix = "Repaired" if args.apply else "Would repair"
    out = [f"{verb}: {x}" for x in report.linked] + [f"{fix}: {x}" for x in report.repaired]
    out += [f"Skipped: {x}" for x in report.skipped] + [f"Problem: {x}" for x in report.problems]
    if out:
        print("\n".join(out))
    elif not args.quiet:
        print("Nothing to link.")
    if not args.apply and report.changed:
        print("(dry run: nothing was changed; add --apply to write)")
    return 3 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
