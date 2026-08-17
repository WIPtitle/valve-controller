import json
import os
import tempfile

DEFAULT_CONFIG_PATH = "/etc/valve-controller/config.json"
DEFAULT_CONFIG = {
    "port": 8686,
    "i2c_address": "0x10",
    "num_zones": 4
}


def load_config(path=None):
    config_path = path or os.environ.get("VALVE_CONTROLLER_CONFIG_PATH", DEFAULT_CONFIG_PATH)
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()


def _atomic_write_json(path, data):
    """Crash-safe JSON write: temp file + fsync + atomic rename + dir fsync.

    On power loss the target is left as either the complete old file or the
    complete new one -- never truncated.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        dir_fd = os.open(directory, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_config(config, path=None):
    config_path = path or os.environ.get("VALVE_CONTROLLER_CONFIG_PATH", DEFAULT_CONFIG_PATH)
    _atomic_write_json(config_path, config)


class ConfigManager:
    def __init__(self, config_path=None):
        self.config_path = config_path or os.environ.get("VALVE_CONTROLLER_CONFIG_PATH", DEFAULT_CONFIG_PATH)
        self.config = load_config(self.config_path)

    @property
    def port(self):
        return self.config.get("port", DEFAULT_CONFIG["port"])

    @property
    def num_zones(self):
        return self.config.get("num_zones", DEFAULT_CONFIG["num_zones"])

    @property
    def i2c_address(self):
        addr = self.config.get("i2c_address", DEFAULT_CONFIG["i2c_address"])
        if isinstance(addr, str):
            return int(addr, 16)
        return addr

    def save(self):
        save_config(self.config, self.config_path)
