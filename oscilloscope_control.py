import datetime
import os
import time
from typing import Optional

import pyvisa
from pyvisa.errors import VisaIOError
from pyvisa.resources import MessageBasedResource

# CONFIGURATION CONSTANTS FOR COMMONLY TUNED SETTINGS
AUTOSCALE_ENABLE_COMMAND = ':AUToscale'
AUTOSCALE_DISABLE_COMMAND = ':AUToscale:STATE OFF'  # IMPORTANT: ADJUST IF YOUR OSCILLOSCOPE USES ANOTHER COMMAND TO DISABLE AUTOSCALE.
AUTOSCALE_DEFAULT_ENABLED = False  # SET TO FALSE TO KEEP MANUAL SETTINGS BEFORE SCREENSHOTS.
AUTOSCALE_WAIT_SECONDS = 3.0  # HOW LONG TO WAIT AFTER AUTOSCALE/ENABLE. USED WHEN AUTOSCALE IS TRUE.
TIMEBASE_SECONDS_PER_DIVISION = 0.001  # REQUIRED WHEN AUTOSCALE_DEFAULT_ENABLED IS FALSE (0.05 == 50MS PER DIVISION).


def open_scope(resource_name: str) -> MessageBasedResource:
    """
    Opens a connection to the oscilloscope and configures basic communication parameters.
    Returns a MessageBasedResource object to avoid warnings in PyCharm.
    """
    rm = pyvisa.ResourceManager()
    scope: MessageBasedResource = rm.open_resource(resource_name)

    # Increase timeout and chunk_size because screenshot transfers can be large
    scope.timeout = 20000
    scope.chunk_size = 102400

    scope.write_termination = '\n'
    scope.read_termination = '\n'

    # Disable additional SCPI headers if the oscilloscope sends them
    scope.write(':SYSTem:HEADer OFF')

    return scope


def autoscale_oscilloscope(resource_name: str, wait_time: float = AUTOSCALE_WAIT_SECONDS) -> None:
    """
    Opens a connection to the oscilloscope and issues the :AUToscale command.
    Then optionally waits 'wait_time' seconds so the waveform has time to settle.
    """
    scope = open_scope(resource_name)
    try:
        _set_autoscale_state(scope, enabled=True, wait_time=wait_time)
    finally:
        scope.close()


def read_binblock(scope: MessageBasedResource) -> bytes:
    """
    Reads a binblock formatted as '#NLLLL...(data)' in a loop
    until the entire specified number of bytes (LLLL) is retrieved.
    Returns raw bytes.
    """
    header = scope.read_bytes(2)
    if not header.startswith(b'#'):
        raise ValueError(f"Invalid binblock header (missing '#'): {header}")

    digits = int(header[1:2])
    length_str = scope.read_bytes(digits)
    data_length = int(length_str)

    data = bytearray()
    bytes_left = data_length
    chunk = 65536

    while bytes_left > 0:
        to_read = min(chunk, bytes_left)
        block = scope.read_bytes(to_read)
        data.extend(block)
        bytes_left -= len(block)

    return bytes(data)


def _set_autoscale_state(scope: MessageBasedResource, enabled: bool, wait_time: float = 0.0) -> None:
    """
    Enables or disables AutoScale on the already opened oscilloscope handle.
    When enabling, :AUToscale is executed and optional wait applied; disabling
    uses :AUToscale:STATE OFF (instrument must support this SCPI command).
    """
    command = AUTOSCALE_ENABLE_COMMAND if enabled else AUTOSCALE_DISABLE_COMMAND
    try:
        scope.write(command)
    except VisaIOError as error:
        direction = 'enable' if enabled else 'disable'
        raise RuntimeError(f"Failed to {direction} AutoScale via '{command}'.") from error

    if enabled and wait_time > 0:
        # Allow the instrument to settle after executing AutoScale
        time.sleep(wait_time)


def set_autoscale_state(resource_name: str, enabled: bool, wait_time: float = AUTOSCALE_WAIT_SECONDS) -> None:
    """
    Opens the oscilloscope connection and enables or disables AutoScale.
    Use this when you need to preserve manual settings before a screenshot.
    """
    scope = open_scope(resource_name)
    try:
        _set_autoscale_state(scope, enabled=enabled, wait_time=wait_time)
    finally:
        scope.close()


def _set_timebase_scale(scope: MessageBasedResource,
                        seconds_per_division: float = TIMEBASE_SECONDS_PER_DIVISION) -> None:
    """
    Sets the time base scale (seconds per division) on an opened oscilloscope handle.
    """
    if seconds_per_division <= 0:
        raise ValueError('seconds_per_division must be greater than zero.')
    # IMPORTANT: SET TIMEBASE HERE USING SECONDS PER DIVISION (E.G., 0.05 FOR 50MS), OR TUNE TIMEBASE_SECONDS_PER_DIVISION ABOVE.
    scope.write(f':TIMebase:SCALe {seconds_per_division}')


def set_timebase_scale(resource_name: str,
                       seconds_per_division: float = TIMEBASE_SECONDS_PER_DIVISION) -> None:
    """
    Opens the oscilloscope connection and sets a manual time base scale.
    Useful before taking screenshots when AutoScale is disabled.
    """
    scope = open_scope(resource_name)
    try:
        _set_timebase_scale(scope, seconds_per_division=seconds_per_division)
    finally:
        scope.close()


def capture_screenshot_display(resource_name: str,
                               folder: str = r"C:\Users\35387\Pictures\Screenshots",
                               autoscale: Optional[bool] = None,
                               autoscale_wait: Optional[float] = None,
                               timebase_scale: Optional[float] = None
                               ) -> None:
    """
    Opens a connection to the oscilloscope, acquires a screenshot
    using the :DISPlay:DATA? PNG, COLOR command in binblock form, and saves a PNG file
    with a unique timestamped filename. AutoScale and timebase behaviour default
    to the configuration constants defined at the top of this module unless the
    optional parameters override them.
    """
    scope = open_scope(resource_name)

    try:
        autoscale_setting = AUTOSCALE_DEFAULT_ENABLED if autoscale is None else autoscale
        wait_setting = AUTOSCALE_WAIT_SECONDS if autoscale_wait is None else autoscale_wait

        if autoscale_setting:
            _set_autoscale_state(scope, enabled=True, wait_time=wait_setting)
            if timebase_scale is not None:
                _set_timebase_scale(scope, seconds_per_division=timebase_scale)
        else:
            _set_autoscale_state(scope, enabled=False)
            manual_scale = timebase_scale if timebase_scale is not None else TIMEBASE_SECONDS_PER_DIVISION
            if manual_scale is None:
                raise ValueError('Provide timebase_scale argument or configure TIMEBASE_SECONDS_PER_DIVISION when AutoScale is disabled.')
            _set_timebase_scale(scope, seconds_per_division=manual_scale)

        # Command to retrieve the screenshot in PNG format, in color
        scope.write(':DISPlay:DATA? PNG, COLOR')

        # Read the binblock
        image_data = read_binblock(scope)

        # Build a unique filename with date and time
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"scope_screenshot_{timestamp_str}.png"

        # Ensure the target folder exists
        os.makedirs(folder, exist_ok=True)

        full_path = os.path.join(folder, filename)
        with open(full_path, 'wb') as f:
            f.write(image_data)

        print(f"Screenshot zapisany do: {full_path}")

    finally:
        scope.close()


def main() -> None:
    resource_name = "USB0::0x0957::0x17A4::MY58250706::INSTR"

    # Example: capture using configuration constants declared at the top of the file
    capture_screenshot_display(resource_name)

    # Example overrides:
    # capture_screenshot_display(resource_name, autoscale=False, timebase_scale=0.002)
    # set_autoscale_state(resource_name, enabled=True)
    # set_timebase_scale(resource_name, seconds_per_division=0.01)


if __name__ == '__main__':
    main()
