#!/usr/bin/env python
"""Plain entry point so you can run the CLI as a script instead of `-m`.

    python main.py serve -v
    python main.py fetch --niche tech
    python main.py generate --niche tech

It's the exact same Typer app as `python -m opensocial`; this just saves you
typing the module flag.
"""

from opensocial.cli import main

if __name__ == "__main__":
    main()
