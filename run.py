#!/usr/bin/env python3
"""MinionDesk entry point."""
import sys
import os

# Ensure repo root on path
sys.path.insert(0, os.path.dirname(__file__))

from miniondesk.run import cli

if __name__ == "__main__":
    cli()
