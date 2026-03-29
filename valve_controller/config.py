import json
import os

DEFAULT_CONFIG_PATH = "/etc/valve-controller/config.json"
DEFAULT_CONFIG = {
    "port": 8890,
    "relay_pins": {
        "1": 21,
        "2": 20,
        "3": 16,
        "4": 12
    },
    "active_low": True
}


def load_config(path=None):
    config_path = path or os.environ.get("VALVE_CONTROLLER_CONFIG_PATH", DEFAULT_CONFIG_PATH)
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()


def save_config(config, path=None):
    config_path = path or os.environ.get("VALVE_CONTROLLER_CONFIG_PATH", DEFAULT_CONFIG_PATH)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


class ConfigManager:
    def __init__(self, config_path=None):
        self.config_path = config_path or os.environ.get("VALVE_CONTROLLER_CONFIG_PATH", DEFAULT_CONFIG_PATH)
        self.config = load_config(self.config_path)

    @property
    def port(self):
        return self.config.get("port", DEFAULT_CONFIG["port"])

    @property
    def relay_pins(self):
        return self.config.get("relay_pins", DEFAULT_CONFIG["relay_pins"])

    @property
    def active_low(self):
        return self.config.get("active_low", DEFAULT_CONFIG["active_low"])

    def save(self):
        save_config(self.config, self.config_path)
