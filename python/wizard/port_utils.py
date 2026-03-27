"""Port availability utilities."""
import socket


def is_port_in_use(host: str, port: int) -> bool:
    """Check if a TCP port is in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def find_free_port(host: str, start: int, max_attempts: int = 10) -> int | None:
    """Find the first free port starting from `start`.
    Returns the port number or None if all checked ports are in use.
    """
    for offset in range(max_attempts):
        port = start + offset
        if not is_port_in_use(host, port):
            return port
    return None
