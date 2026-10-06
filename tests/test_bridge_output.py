import asyncio
import os
import select
from pathlib import Path
from unittest.mock import patch

import pytest

from foxbridge.config import OutputConfig
from foxbridge.output import FileOutput, SerialOutput
from foxbridge.sportident import PunchTime, SportIdentEncoder, SportIdentPunch, validate_frame


def test_file_capture(tmp_path: Path) -> None:
    async def check() -> None:
        path = tmp_path / "capture.bin"
        output = FileOutput(path)
        frame = SportIdentEncoder().encode_punch(SportIdentPunch(912345, 31, PunchTime(2, 100)))
        await output.connect()
        await output.write(frame)
        await output.close()
        await output.connect()
        await output.write(frame)
        await output.close()
        assert path.read_bytes() == frame + frame
        assert not output.connected

    asyncio.run(check())


@pytest.mark.skipif(
    os.name != "posix", reason="Optional Unix serial capture; Windows does not depend on PTYs"
)
def test_serial_capture_through_os_device() -> None:
    async def check() -> None:
        master, slave = os.openpty()
        path = os.ttyname(slave)
        output = SerialOutput(OutputConfig(port=path))
        frame = bytes.fromhex("02D30D002C000BDF77270E8D27000B70BE7103")
        try:
            await output.connect()
            assert output.connected
            await output.write(frame)
            ready, _, _ = select.select([master], [], [], 1)
            assert ready
            captured = os.read(master, 4096)
            assert captured == frame
            validate_frame(captured)
        finally:
            await output.close()
            os.close(master)
            os.close(slave)

    asyncio.run(check())


def test_serial_output_partial_write_is_failure() -> None:
    class Device:
        def write(self, data: bytes) -> int:
            return 1

        def close(self) -> None:
            pass

    async def check() -> None:
        output = SerialOutput(OutputConfig(port="FAKE"))
        with patch("foxcore.serial.serial.Serial", return_value=Device()):
            await output.connect()
            with pytest.raises(OSError, match="Incomplete"):
                await output.write(b"19-byte-punch-frame!")
            await output.close()

    asyncio.run(check())
