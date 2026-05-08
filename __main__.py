#!/usr/bin/env python3
"""Allow running ScribeFTS directly from the repository root.

Usage:
    python __main__.py          # defaults to CLI mode
    python __main__.py --cli    # explicit CLI mode
    python __main__.py --gui    # browser-based GUI mode
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="ScribeFTS",
        description="Document cataloging tool with full-text search",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--cli", action="store_true", help="Launch interactive CLI (default)")
    group.add_argument("--gui", action="store_true", help="Launch browser-based GUI")
    args = parser.parse_args()

    if args.gui:
        from gui.app import run_gui
        run_gui()
    else:
        from bin.ScribeFTS import main as cli_main
        cli_main()


if __name__ == "__main__":
    main()
