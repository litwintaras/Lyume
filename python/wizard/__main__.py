"""Allow running wizard as: python -m wizard"""
import sys
from pathlib import Path

from wizard import run_wizard

config_path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent.parent / "config.yaml")
run_wizard(config_path)
