"""OS detection and platform-specific instructions."""
import platform
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum


class OS(Enum):
    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"


class Distro(Enum):
    ARCH = "arch"
    UBUNTU = "ubuntu"
    DEBIAN = "debian"
    FEDORA = "fedora"
    RHEL = "rhel"
    UNKNOWN = "unknown"


@dataclass
class PlatformInfo:
    os: OS
    distro: Distro
    docker_installed: bool
    docker_running: bool


def detect_platform() -> PlatformInfo:
    """Detect current OS, distro, and Docker status."""
    system = platform.system().lower()

    if system == "darwin":
        os_type = OS.MACOS
        distro = Distro.UNKNOWN
    elif system == "windows":
        os_type = OS.WINDOWS
        distro = Distro.UNKNOWN
    else:
        os_type = OS.LINUX
        distro = _detect_linux_distro()

    docker_installed = shutil.which("docker") is not None
    docker_running = False
    if docker_installed:
        try:
            subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=5)
            docker_running = True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return PlatformInfo(os=os_type, distro=distro, docker_installed=docker_installed, docker_running=docker_running)


def _detect_linux_distro() -> Distro:
    """Detect Linux distribution from /etc/os-release."""
    try:
        text = open("/etc/os-release").read().lower()
        if "arch" in text:
            return Distro.ARCH
        elif "ubuntu" in text:
            return Distro.UBUNTU
        elif "debian" in text:
            return Distro.DEBIAN
        elif "fedora" in text:
            return Distro.FEDORA
        elif "rhel" in text or "red hat" in text:
            return Distro.RHEL
    except FileNotFoundError:
        pass
    return Distro.UNKNOWN


def docker_install_instructions(info: PlatformInfo) -> str:
    """Return platform-specific Docker install instructions."""
    if info.os == OS.LINUX:
        cmds = {
            Distro.ARCH: "sudo pacman -S docker docker-compose\nsudo systemctl enable --now docker\nsudo usermod -aG docker $USER",
            Distro.UBUNTU: "curl -fsSL https://get.docker.com | sh\nsudo usermod -aG docker $USER",
            Distro.DEBIAN: "curl -fsSL https://get.docker.com | sh\nsudo usermod -aG docker $USER",
            Distro.FEDORA: "sudo dnf install docker-ce docker-compose-plugin\nsudo systemctl enable --now docker\nsudo usermod -aG docker $USER",
        }
        instructions = cmds.get(info.distro, "curl -fsSL https://get.docker.com | sh\nsudo usermod -aG docker $USER")
        return f"Run these commands:\n\n  {instructions.replace(chr(10), chr(10) + '  ')}\n\nThen log out and back in (or reboot) for group changes."
    elif info.os == OS.MACOS:
        return "Install Docker Desktop:\n\n  brew install --cask docker\n\nOr download from: https://docs.docker.com/desktop/install/mac-install/"
    elif info.os == OS.WINDOWS:
        return "Install Docker Desktop:\n\n  winget install Docker.DockerDesktop\n\nOr download from: https://docs.docker.com/desktop/install/windows-install/\n\nAfter install, restart your computer."
    return "Visit https://docs.docker.com/engine/install/ for instructions."


def compose_install_instructions(info: PlatformInfo) -> str:
    """Return platform-specific Docker Compose install instructions."""
    if info.os == OS.LINUX:
        cmds = {
            Distro.ARCH: "sudo pacman -S docker-compose",
            Distro.UBUNTU: "sudo apt install docker-compose-plugin",
            Distro.DEBIAN: "sudo apt install docker-compose-plugin",
            Distro.FEDORA: "sudo dnf install docker-compose-plugin",
            Distro.RHEL: "sudo dnf install docker-compose-plugin",
        }
        cmd = cmds.get(info.distro, "sudo apt install docker-compose-plugin")
        return f"Install Docker Compose:\n\n  {cmd}"
    elif info.os == OS.MACOS:
        return "Docker Compose is included with Docker Desktop. Reinstall Docker Desktop if missing."
    elif info.os == OS.WINDOWS:
        return "Docker Compose is included with Docker Desktop. Reinstall Docker Desktop if missing."
    return "Visit https://docs.docker.com/compose/install/ for instructions."


def docker_install_url(info: PlatformInfo) -> str:
    """Return Docker install URL for the platform."""
    if info.os == OS.MACOS:
        return "https://docs.docker.com/desktop/install/mac-install/"
    elif info.os == OS.WINDOWS:
        return "https://docs.docker.com/desktop/install/windows-install/"
    return "https://docs.docker.com/engine/install/"


def service_setup_commands(info: PlatformInfo, venv_python: str, proxy_script: str, working_dir: str, agent_name: str = "lyume") -> dict:
    """Return platform-specific commands for auto-start service setup.
    Returns dict with keys: setup_cmds (list[str]), status_cmd, logs_cmd, service_name
    """
    import re
    slug = re.sub(r"[^a-z0-9]", "-", agent_name.lower()).strip("-") or "lyume"
    svc_name = f"lyume-proxy-{slug}"

    if info.os == OS.LINUX:
        unit = f"""[Unit]
Description={agent_name} — Lyume Memory Proxy
After=network.target

[Service]
Type=simple
WorkingDirectory={working_dir}
ExecStart={venv_python} {proxy_script}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target"""
        unit_path = f"~/.config/systemd/user/{svc_name}.service"
        return {
            "unit_content": unit,
            "unit_path": unit_path,
            "service_name": svc_name,
            "status_cmd": f"systemctl --user status {svc_name}",
            "logs_cmd": f"journalctl --user -u {svc_name} -f",
        }
    elif info.os == OS.MACOS:
        label = f"com.lyume.proxy.{slug}"
        plist_path = f"~/Library/LaunchAgents/{label}.plist"
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{venv_python}</string>
        <string>{proxy_script}</string>
    </array>
    <key>WorkingDirectory</key><string>{working_dir}</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/tmp/{svc_name}.log</string>
    <key>StandardErrorPath</key><string>/tmp/{svc_name}.err</string>
</dict>
</plist>"""
        return {
            "plist_content": plist,
            "plist_path": plist_path,
            "service_name": label,
            "status_cmd": f"launchctl list | grep {slug}",
            "logs_cmd": f"tail -f /tmp/{svc_name}.log",
        }
    else:  # Windows
        task_name = f"LyumeProxy-{slug}"
        return {
            "setup_cmds": [
                f'schtasks /create /tn "{task_name}" /tr "{venv_python} {proxy_script}" /sc onlogon /rl highest /f',
                f'schtasks /run /tn "{task_name}"',
            ],
            "service_name": task_name,
            "status_cmd": f'schtasks /query /tn "{task_name}"',
            "logs_cmd": "Check proxy output in terminal",
        }
