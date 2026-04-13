"""Load YAML configuration files."""
import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def load_config(filename: str) -> dict:
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def get_scoring_rules(format: str = "half_ppr") -> dict:
    rules = load_config("scoring_rules.yaml")
    if format not in rules:
        raise ValueError(f"Unknown scoring format: {format}. Options: {list(rules.keys())}")
    return rules[format]


def get_roster_config() -> dict:
    return load_config("roster_config.yaml")
