"""
discord_bot.py — Upwork Discord Bot entry point (Backward-compatible).

Usage:
  python discord_bot.py

This delegates directly to the new multi-platform runner (`main.py --platform upwork`).
You can also use:
  python main.py --platform upwork
  python main.py --platform all
"""

import sys
from main import run_platform, main

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # If user passed arguments like --platform, let main() parse them
        main()
    else:
        # Default behavior for `python discord_bot.py`: run Upwork
        run_platform(["upwork"])
