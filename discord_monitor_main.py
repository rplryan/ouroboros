"""Render entry point for Discord monitor bot."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from agent_economy.discord_monitor.bot import run

if __name__ == "__main__":
    run()
