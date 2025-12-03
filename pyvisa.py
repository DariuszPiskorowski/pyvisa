import pyvisa
import datetime
import os
import time

from pyvisa.resources import MessageBasedResource

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

def autoscale_oscilloscope(resource_name: str, wait_time: float = 1.0) -> None:
    """
    Opens a connection to the oscilloscope and issues the :AUToscale command.
    Then optionally waits 'wait_time' seconds so the waveform has time to settle.
    """
    scope = open_scope(resource_name)
    try:
        scope.write(':AUToscale')
        # Adjust the wait time depending on the needs of your oscilloscope
        time.sleep(wait_time)
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
        raise ValueError(f"Niepoprawny nagłówek binblock (brak '#'): {header}")

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

def capture_screenshot_display(resource_name: str,
                               folder: str = r"C:\Users\35387\Pictures\Screenshots"
                               ) -> None:
    """
    Opens a connection to the oscilloscope, acquires a screenshot
    using the :DISPlay:DATA? PNG, COLOR command in binblock form, and saves a PNG file
    with a unique timestamped filename.
    """
    scope = open_scope(resource_name)

    try:
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


if __name__ == '__main__':
    resource_name = "USB0::0x0957::0x17A4::MY58250706::INSTR"

    # 1. Run auto-scale first and wait
    autoscale_oscilloscope(resource_name, wait_time=3.0)

    # 2. Then capture the screenshot
    capture_screenshot_display(resource_name)
