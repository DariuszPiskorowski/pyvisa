# PyVISA Oscilloscope Screenshot Tool

A Python application with GUI for capturing screenshots from multiple VISA instruments simultaneously.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

- 🔌 **Auto-detect VISA devices** - Automatically scans for connected USB, GPIB, TCP/IP instruments
- 📷 **Simultaneous capture** - Take screenshots from multiple oscilloscopes at once
- ⚙️ **Configurable settings** - AutoScale toggle and manual time-base control
- 🖥️ **Modern dark UI** - Clean, professional interface
- 📦 **Single .exe** - Builds to a standalone Windows executable

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
4. Configure AutoScale (ON/OFF) and TimeBase if needed
5. Click **"Take a Shot"** to capture screenshots

Screenshots are saved to `~/Pictures/Oscilloscope/` with timestamped filenames.

### Command Line (oscilloscope_control.py)
```python
from oscilloscope_control import capture_screenshot_display

# Basic capture
capture_screenshot_display("USB0::0x0957::0x17A4::MY58250706::INSTR")

# With options
capture_screenshot_display(
    resource_name="USB0::...",
    folder="C:/Screenshots",
    autoscale=False,
    timebase_scale=0.001  # 1ms/div
)
```

## Configuration

Key constants in `oscilloscope_control.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `AUTOSCALE_DEFAULT_ENABLED` | `False` | Run AutoScale before capture |
| `AUTOSCALE_WAIT_SECONDS` | `3.0` | Wait time after AutoScale |
| `TIMEBASE_SECONDS_PER_DIVISION` | `0.001` | Default time-base (1ms/div) |

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
