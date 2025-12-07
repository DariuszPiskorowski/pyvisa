import datetime
import os
import time
from typing import Optional

import pyvisa
from pyvisa.errors import VisaIOError
from pyvisa.resources import MessageBasedResource

# CONFIGURATION CONSTANTS FOR COMMONLY TUNED SETTINGS
AUTOSCALE_DEFAULT_ENABLED = False  # SET TO FALSE TO KEEP MANUAL SETTINGS BEFORE SCREENSHOTS.
AUTOSCALE_WAIT_SECONDS = 3.0  # HOW LONG TO WAIT AFTER AUTOSCALE. USED WHEN AUTOSCALE IS TRUE.
TIMEBASE_SECONDS_PER_DIVISION = 0.001  # REQUIRED WHEN AUTOSCALE_DEFAULT_ENABLED IS FALSE (0.05 == 50MS PER DIVISION).

# VENDOR-SPECIFIC SCPI COMMANDS
VENDOR_COMMANDS = {
    'keysight': {
        'autoscale_enable': ':AUToscale',
        'autoscale_disable': ':AUToscale:STATE OFF',  # Some models may not support this
        'timebase_scale': ':TIMebase:SCALe',
        'timebase_format': '{value}',  # Keysight accepts plain number
    },
    'siglent': {
        'autoscale_enable': 'ASET',  # Siglent uses ASET command
        'autoscale_disable': None,  # Siglent doesn't have a disable command - just don't call autoscale
        'timebase_scale': 'TDIV',  # Siglent uses TDIV command
        'timebase_format': '{value}',  # e.g., TDIV 5E-3
    },
}

# KNOWN OSCILLOSCOPE USB VENDOR/PRODUCT IDS FOR AUTO-DETECTION
KNOWN_OSCILLOSCOPES = [
    '0x0957',   # Keysight / Agilent
    '0xF4EC',   # Siglent
]


def detect_oscilloscope() -> Optional[str]:
    """
    Scans available VISA resources and returns the first USB oscilloscope
    matching a known vendor ID from KNOWN_OSCILLOSCOPES that is actually reachable.
    Returns None if no known oscilloscope is found or responds.
    """
    rm = pyvisa.ResourceManager()
    resources = rm.list_resources()
    candidates = []
    for res in resources:
        if res.startswith('USB'):
            for vendor_id in KNOWN_OSCILLOSCOPES:
                if vendor_id.lower() in res.lower():
                    candidates.append(res)
                    break

    # Try to open each candidate and verify it responds
    for res in candidates:
        try:
            scope = rm.open_resource(res)
            scope.timeout = 5000
            scope.query('*IDN?')  # Check if device actually responds
            scope.close()
            print(f"Detected and verified oscilloscope: {res}")
            return res
        except Exception as e:
            print(f"Skipping {res} (not responding): {e}")
            continue

    print("No known oscilloscope detected or responding.")
    return None


def get_oscilloscope_vendor(resource_name: str) -> str:
    """
    Returns the vendor name based on the USB vendor ID in the resource name.
    Supported: 'keysight', 'siglent', 'unknown'
    """
    res_lower = resource_name.lower()
    if '0x0957' in res_lower:
        return 'keysight'
    elif '0xf4ec' in res_lower:
        return 'siglent'
    return 'unknown'


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

    # Disable additional SCPI headers if the oscilloscope sends them (Keysight only)
    vendor = get_oscilloscope_vendor(resource_name)
    if vendor == 'keysight':
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


def _set_autoscale_state(scope: MessageBasedResource, enabled: bool, vendor: str = 'keysight', wait_time: float = 0.0) -> None:
    """
    Enables or disables AutoScale on the already opened oscilloscope handle.
    Uses vendor-specific commands from VENDOR_COMMANDS dictionary.
    """
    commands = VENDOR_COMMANDS.get(vendor, VENDOR_COMMANDS['keysight'])
    
    if enabled:
        command = commands['autoscale_enable']
    else:
        command = commands['autoscale_disable']
        if command is None:
            # Vendor doesn't support disable command - just skip
            print(f"Note: {vendor} doesn't support AutoScale disable, skipping.")
            return
    
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
    Automatically detects vendor and uses appropriate SCPI commands.
    """
    vendor = get_oscilloscope_vendor(resource_name)
    scope = open_scope(resource_name)
    try:
        _set_autoscale_state(scope, enabled=enabled, vendor=vendor, wait_time=wait_time)
    finally:
        scope.close()


def _set_timebase_scale(scope: MessageBasedResource,
                        seconds_per_division: float = TIMEBASE_SECONDS_PER_DIVISION,
                        vendor: str = 'keysight') -> None:
    """
    Sets the time base scale (seconds per division) on an opened oscilloscope handle.
    Uses vendor-specific SCPI commands.
    """
    if seconds_per_division <= 0:
        raise ValueError('seconds_per_division must be greater than zero.')
    
    commands = VENDOR_COMMANDS.get(vendor, VENDOR_COMMANDS['keysight'])
    cmd = commands['timebase_scale']
    
    # Format the command with the value
    full_command = f'{cmd} {seconds_per_division}'
    print(f"Setting timebase: {full_command}")
    scope.write(full_command)


def set_timebase_scale(resource_name: str,
                       seconds_per_division: float = TIMEBASE_SECONDS_PER_DIVISION) -> None:
    """
    Opens the oscilloscope connection and sets a manual time base scale.
    Useful before taking screenshots when AutoScale is disabled.
    Automatically detects vendor and uses appropriate SCPI commands.
    """
    vendor = get_oscilloscope_vendor(resource_name)
    scope = open_scope(resource_name)
    try:
        _set_timebase_scale(scope, seconds_per_division=seconds_per_division, vendor=vendor)
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
        vendor = get_oscilloscope_vendor(resource_name)

        if autoscale_setting:
            _set_autoscale_state(scope, enabled=True, vendor=vendor, wait_time=wait_setting)
            if timebase_scale is not None:
                _set_timebase_scale(scope, seconds_per_division=timebase_scale, vendor=vendor)
        else:
            # For Siglent: just don't run autoscale, it will keep manual settings
            # For Keysight: try to disable autoscale explicitly
            if vendor != 'siglent':
                _set_autoscale_state(scope, enabled=False, vendor=vendor)
            manual_scale = timebase_scale if timebase_scale is not None else TIMEBASE_SECONDS_PER_DIVISION
            if manual_scale is None:
                raise ValueError('Provide timebase_scale argument or configure TIMEBASE_SECONDS_PER_DIVISION when AutoScale is disabled.')
            _set_timebase_scale(scope, seconds_per_division=manual_scale, vendor=vendor)

        # Determine vendor and use appropriate screenshot command
        vendor = get_oscilloscope_vendor(resource_name)
        
        if vendor == 'siglent':
            # Siglent uses :SCDP command for screen dump (returns BMP by default)
            scope.write(':SCDP')
            # Siglent returns raw data without binblock header, read all available
            time.sleep(1)  # Give oscilloscope time to prepare data
            image_data = scope.read_raw()
        else:
            # Keysight/Agilent uses :DISPlay:DATA? PNG, COLOR
            scope.write(':DISPlay:DATA? PNG, COLOR')
            image_data = read_binblock(scope)

        # Build a unique filename with date and time
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = 'bmp' if vendor == 'siglent' else 'png'
        filename = f"scope_screenshot_{timestamp_str}.{ext}"

        # Ensure the target folder exists
        os.makedirs(folder, exist_ok=True)

        full_path = os.path.join(folder, filename)
        with open(full_path, 'wb') as f:
            f.write(image_data)

        print(f"Screenshot zapisany do: {full_path}")

    finally:
        scope.close()


def main() -> None:
    # Auto-detect connected oscilloscope or fall back to manual address
    resource_name = detect_oscilloscope()
    if resource_name is None:
        print("ERROR: No oscilloscope found. Check USB connection.")
        return

    # Capture using configuration constants declared at the top of the file
    capture_screenshot_display(resource_name)

    # Example overrides:
    # capture_screenshot_display(resource_name, autoscale=False, timebase_scale=0.002)
    # set_autoscale_state(resource_name, enabled=True)
    # set_timebase_scale(resource_name, seconds_per_division=0.01)


if __name__ == '__main__':
    main()
