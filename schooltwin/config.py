"""Load the three YAML files and apply scenario overrides."""
import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(config_dir=None):
    d = Path(config_dir) if config_dir else ROOT / "config"
    cfg = {}
    for name in ("school", "map", "behavior"):
        with open(d / f"{name}.yaml", encoding="utf-8") as f:
            cfg[name] = yaml.safe_load(f)
    return cfg


def apply_overrides(cfg, overrides):
    """overrides = {"school.finance.monthly_fee": 6000, "behavior.patrol.stay_minutes": [3, 5]}"""
    cfg = copy.deepcopy(cfg)
    for dotted, value in (overrides or {}).items():
        keys = dotted.split(".")
        node = cfg
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return cfg
