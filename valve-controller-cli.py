#!/usr/bin/env python3
"""Valve Controller CLI - manage the valve-controller service."""

import sys
import os
import subprocess
import json

SERVICE_NAME = "valve-controller"
CONFIG_PATH = os.environ.get("VALVE_CONTROLLER_CONFIG_PATH", "/etc/valve-controller/config.json")


def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"port": 8890, "relay_pins": {"1": 21, "2": 20, "3": 16, "4": 12}, "active_low": True}


def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.returncode


def cmd_status():
    config = load_config()
    print(f"Valve Controller Service")
    print(f"  Port: {config.get('port', 8890)}")
    print(f"  Config: {CONFIG_PATH}")
    print(f"  Relay pins: {config.get('relay_pins', {})}")
    print(f"  Active low: {config.get('active_low', True)}")
    output, rc = run_cmd(f"systemctl is-active {SERVICE_NAME}")
    print(f"  Service: {output}")


def cmd_set_port(port):
    try:
        port = int(port)
        if port < 1 or port > 65535:
            raise ValueError
    except ValueError:
        print(f"Error: invalid port number: {port}")
        sys.exit(1)

    config = load_config()
    config["port"] = port
    save_config(config)
    print(f"Port set to {port}")

    output, rc = run_cmd(f"systemctl is-active {SERVICE_NAME}")
    if output == "active":
        run_cmd(f"systemctl restart {SERVICE_NAME}")
        print("Service restarted")


def cmd_set_pins(args):
    """Set relay pins: valve-controller set-pins 1=21 2=20 3=16 4=12"""
    config = load_config()
    pins = config.get("relay_pins", {})
    for arg in args:
        if "=" not in arg:
            print(f"Error: invalid format '{arg}', use ZONE=PIN (e.g., 1=21)")
            sys.exit(1)
        zone, pin = arg.split("=", 1)
        try:
            int(pin)
        except ValueError:
            print(f"Error: invalid pin number: {pin}")
            sys.exit(1)
        pins[zone] = int(pin)
    config["relay_pins"] = pins
    save_config(config)
    print(f"Relay pins updated: {pins}")


def cmd_help():
    print("Usage: valve-controller <command> [args]")
    print()
    print("Commands:")
    print("  status              Show service status and configuration")
    print("  set-port <port>     Change server port")
    print("  set-pins Z=P ...    Set relay pin mapping (e.g., 1=21 2=20)")
    print("  restart             Restart the service")
    print("  stop                Stop the service")
    print("  start               Start the service")
    print("  logs                Show service logs")
    print("  help                Show this help")


def main():
    if len(sys.argv) < 2:
        cmd_help()
        sys.exit(1)

    command = sys.argv[1]

    if command == "status":
        cmd_status()
    elif command == "set-port":
        if len(sys.argv) < 3:
            print("Usage: valve-controller set-port <port>")
            sys.exit(1)
        cmd_set_port(sys.argv[2])
    elif command == "set-pins":
        if len(sys.argv) < 3:
            print("Usage: valve-controller set-pins 1=21 2=20 3=16 4=12")
            sys.exit(1)
        cmd_set_pins(sys.argv[2:])
    elif command == "restart":
        os.system(f"systemctl restart {SERVICE_NAME}")
    elif command == "stop":
        os.system(f"systemctl stop {SERVICE_NAME}")
    elif command == "start":
        os.system(f"systemctl start {SERVICE_NAME}")
    elif command == "logs":
        os.system(f"journalctl -u {SERVICE_NAME} -f")
    elif command == "help":
        cmd_help()
    else:
        print(f"Unknown command: {command}")
        cmd_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
