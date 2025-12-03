# PyVISA Oscilloscope Interface

This repository contains a Python script for controlling oscilloscopes via the VISA protocol using the PyVISA library. The main entry point is `oscilloscope_control.py`, which handles AutoScale toggling, manual time-base configuration, and screenshot capture.

## Features

- Connect to the oscilloscope and configure communication parameters
- Enable/disable AutoScale with configurable wait times
- Set a manual time-base (seconds per division)
- Capture oscilloscope screenshots via SCPI commands and save them locally

## Requirements

- Python 3.13 (or compatible)
- PyVISA library (`pip install pyvisa`)
- NI VISA runtime or a compatible backend such as PyVISA-py

## Quick Start

```bash
# Update configuration constants near the top of oscilloscope_control.py if needed
python oscilloscope_control.py
```

Key configuration constants in `oscilloscope_control.py`:

- `AUTOSCALE_DEFAULT_ENABLED`: set to `True` to run AutoScale before each screenshot, or `False` to keep manual settings.
- `AUTOSCALE_WAIT_SECONDS`: how long to wait after AutoScale completes.
- `TIMEBASE_SECONDS_PER_DIVISION`: default time-base used when AutoScale is disabled.

The script can also be imported and its helper functions (`set_autoscale_state`, `set_timebase_scale`, `capture_screenshot_display`) used directly inside other automation workflows.

## Running from VS Code

1. Open `oscilloscope_control.py`.
2. Ensure your VISA resource name is correct in the `main()` function or pass it to your own calls.
3. Press `F5` (Python File) or use the “Run Python File” button.

## Contributing

Pull requests with device-specific tweaks or additional tooling are welcome.

## License

This project is open-source.
