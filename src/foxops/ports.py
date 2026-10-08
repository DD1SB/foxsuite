"""Enumeration is evidence about USB identity, not FoxIdent firmware detection."""

from dataclasses import asdict, dataclass

from serial.tools import list_ports

from .settings import Device


@dataclass(frozen=True)
class Port:
    port: str
    device: Device

    @property
    def label(self) -> str:
        return self.port + " — " + (self.device.description or "Serial device")

    def json(self) -> dict[str, object]:
        return {"port": self.port, "label": self.label, "device": asdict(self.device)}


def enumerate_ports() -> list[Port]:
    return [
        Port(
            info.device,
            Device(
                info.vid,
                info.pid,
                info.serial_number,
                info.description,
                info.manufacturer,
                info.product,
            ),
        )
        for info in sorted(list_ports.comports())
    ]


def relocated(device: Device, old_port: str, ports: list[Port]) -> Port | None:
    if device.vid is None or device.pid is None or not device.serial_number:
        return None
    matches = [
        port
        for port in ports
        if (port.device.vid, port.device.pid, port.device.serial_number)
        == (device.vid, device.pid, device.serial_number)
    ]
    return matches[0] if len(matches) == 1 and matches[0].port != old_port else None
