# PyVISA Oscilloscope Interface

This repository provides a Python implementation for communicating with oscilloscopes using the National Instruments (NI) VISA protocol. It leverages the PyVISA library to enable programmatic control and data acquisition from supported oscilloscope devices.

## Features

- Simple Python API for oscilloscope communication
- Support for querying waveforms, settings, and measurements
- Compatible with NI VISA-compliant instruments

## Requirements

- Python 3.x
- PyVISA library (`pip install pyvisa`)
- NI VISA runtime or compatible backend (e.g., PyVISA-py for open-source implementation)

## Usage

```python
import visa

# Open a resource manager
rm = visa.ResourceManager()

# Connect to an oscilloscope (replace with your device's address)
osc = rm.open_resource('TCPIP::192.168.1.100::INSTR')

# Example: Query the device ID
print(osc.query('*IDN?'))

# Close the connection
osc.close()
```

## Contributing

Feel free to fork and contribute improvements or additional features.

## License

This project is open-source. Please refer to the license file for details (if applicable).
