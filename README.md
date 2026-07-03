# PyVISA Oscilloscope Screenshot Tool

A Python application with GUI for capturing screenshots from multiple VISA instruments simultaneously.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

- 🔌 **Auto-detect VISA devices** - Automatically scans for connected USB, GPIB, TCP/IP instruments
- 📷 **Simultaneous capture** - Trigger multiple instruments from one action
- 🏭 **Multi-vendor support** - Works with Keysight/Agilent, Siglent, and Keithley instruments
- ⚙️ **Configurable settings** - Oscilloscope capture mode/time-base and DMM6500 measurement type/range
- 🖥️ **Modern dark UI** - Clean, professional interface
- 📦 **Single .exe** - Builds to a standalone Windows executable

## Supported Instruments

### Oscilloscopes

| Vendor | Models | Tested |
|--------|--------|--------|
| **Keysight / Agilent** | InfiniiVision series (e.g., DSOX, MSOX) | ✅ |
| **Siglent** | SDS1000X-E, SDS2000X-E, SDS800X-HD | ✅ SDS1104X-E |

### Multimeters

| Vendor | Models | Tested |
|--------|--------|--------|
| **Keithley** | DMM6500 | ✅ |

The tool auto-detects instrument type and uses the appropriate SCPI commands:

| Feature | Keysight | Siglent |
|---------|----------|---------|
| AutoScale | `:AUToscale` | `ASET` |
| Timebase | `:TIMebase:SCALe` | `TDIV` |
| Screenshot | `:DISPlay:DATA? PNG` | `:SCDP` (BMP) |

Keithley DMM6500 support includes:

- Measurement function selection (`VOLT:DC`, `VOLT:AC`, `CURR:DC`, `CURR:AC`, `RES`, `FRES`, `FREQ`)
- Measurement range configuration (numeric manual range or Auto range)
- Single reading via `:READ?`, saved to timestamped `.txt` files

## Requirements

### For running from source:
- Python 3.11+
- PyQt6
- PyVISA
- **NI-VISA runtime** installed on Windows

### For running .exe:
- **NI-VISA runtime** installed on Windows (download from [ni.com](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html))

## Installation

### Option 1: Download pre-built executable
Download the latest `OscilloscopeScreenshotTool.exe` from [Releases](../../releases).

### Option 2: Run from source
```bash
# Clone the repository
git clone https://github.com/DariuszPiskorowski/pyvisa.git
cd pyvisa

# Install dependencies
pip install -r requirements.txt

# Run the GUI
python main_gui.py
```

### Option 3: Build executable yourself
```bash
pip install -r requirements.txt
pyinstaller oscilloscope_tool.spec --clean
# Executable will be in dist/OscilloscopeScreenshotTool.exe
```

## Usage

### GUI Application
1. Launch `main_gui.py` or the `.exe` file
2. Click the refresh button to scan for VISA devices
3. Check the devices you want to capture from
4. Configure settings:
    - Oscilloscope: Capture mode (As Is / AutoScale / Custom TimeBase)
    - Keithley DMM6500: Measurement type and range (Auto or manual)
5. Click **"Take a Shot"** to trigger selected instruments

Outputs are saved to `~/Pictures/Oscilloscope/` with timestamped filenames:

- Oscilloscope screenshot files (`.png` / `.bmp`)
- DMM6500 measurement result files (`.txt`)

### Command Line (oscilloscope_control.py)
```python
from oscilloscope_control import capture_screenshot_display, measure_dmm6500

# Basic capture
capture_screenshot_display("USB0::0x0957::0x17A4::MY58250706::INSTR")

# With options
capture_screenshot_display(
    resource_name="USB0::...",
    folder="C:/Screenshots",
    autoscale=False,
    timebase_scale=0.001  # 1ms/div
)

# DMM6500 single measurement
value = measure_dmm6500(
    resource_name="USB0::...",
    measurement_function="VOLT:DC",
    measurement_range=None  # Auto range
)
print(value)
```

## Configuration

Key constants in `oscilloscope_control.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `AUTOSCALE_DEFAULT_ENABLED` | `False` | Run AutoScale before capture |
| `AUTOSCALE_WAIT_SECONDS` | `3.0` | Wait time after AutoScale |
| `TIMEBASE_SECONDS_PER_DIVISION` | `0.0002` | Default time-base (0.2ms/div) |

### Adding Support for New Oscilloscopes

To add a new vendor, update `VENDOR_COMMANDS` dictionary in `oscilloscope_control.py`:

```python
VENDOR_COMMANDS = {
    'keysight': {
        'autoscale_enable': ':AUToscale',
        'autoscale_disable': ':AUToscale:STATE OFF',
        'timebase_scale': ':TIMebase:SCALe',
    },
    'siglent': {
        'autoscale_enable': 'ASET',
        'autoscale_disable': None,
        'timebase_scale': 'TDIV',
    },
    # Add your vendor here...
}
```

And add the USB vendor ID to `KNOWN_OSCILLOSCOPES` list.

## Building with GitHub Actions

The repository includes a GitHub Actions workflow that automatically builds the Windows executable:

- **On push to `main` or `guibranch`**: Builds and uploads artifact
- **On tag `v*`**: Creates a GitHub Release with the executable

To create a release:
```bash
git tag v1.0.0
git push origin v1.0.0
```

## Project Structure

```
pyvisa/
├── main_gui.py              # PyQt6 GUI application
├── oscilloscope_control.py  # Core VISA control functions
├── style.qss                # Dark theme stylesheet
├── requirements.txt         # Python dependencies
├── oscilloscope_tool.spec   # PyInstaller configuration
├── .github/
│   └── workflows/
│       └── build.yml        # GitHub Actions workflow
└── README.md
```

## Contributing

Pull requests welcome! Please create a new branch for your changes.

## License

This project is open-source under the MIT License.
