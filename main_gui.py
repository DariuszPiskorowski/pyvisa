"""
PyVISA Oscilloscope Screenshot Tool - GUI
A PyQt6-based GUI for capturing screenshots from multiple VISA instruments.
"""
import sys
import os
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, field

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QLineEdit, QScrollArea,
    QFrame, QSizePolicy, QTextEdit, QSpacerItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon, QPixmap

import pyvisa
from pyvisa.errors import VisaIOError

# Import functions from oscilloscope_control
from oscilloscope_control import (
    open_scope, capture_screenshot_display, read_binblock,
    AUTOSCALE_DEFAULT_ENABLED, AUTOSCALE_WAIT_SECONDS, TIMEBASE_SECONDS_PER_DIVISION
)


@dataclass
class Device:
    """Represents a VISA device."""
    id: str
    name: str
    device_type: str
    connected: bool = True
    enabled: bool = False


class ScanThread(QThread):
    """Thread for scanning VISA devices without blocking the UI."""
    devices_found = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def run(self):
        try:
            rm = pyvisa.ResourceManager()
            resources = rm.list_resources()
            devices = []
            for resource in resources:
                # Parse resource name to get device info
                device_type = "Unknown"
                name = resource
                if "USB" in resource:
                    device_type = "USB"
                    # Try to get IDN
                    try:
                        inst = rm.open_resource(resource)
                        inst.timeout = 2000
                        idn = inst.query("*IDN?").strip()
                        inst.close()
                        name = idn.split(",")[1] if "," in idn else idn[:30]
                    except:
                        name = resource.split("::")[3] if len(resource.split("::")) > 3 else resource
                elif "GPIB" in resource:
                    device_type = "GPIB"
                elif "TCPIP" in resource:
                    device_type = "TCP/IP"
                elif "ASRL" in resource:
                    device_type = "Serial"
                
                devices.append(Device(
                    id=resource,
                    name=name,
                    device_type=device_type,
                    connected=True,
                    enabled=False
                ))
            self.devices_found.emit(devices)
        except Exception as e:
            self.error_occurred.emit(str(e))


class CaptureThread(QThread):
    """Thread for capturing screenshots without blocking the UI."""
    capture_started = pyqtSignal(str)
    capture_completed = pyqtSignal(str, str)  # device_id, filepath
    capture_failed = pyqtSignal(str, str)  # device_id, error
    all_completed = pyqtSignal()

    def __init__(self, devices: List[Device], folder: str, mode: int, 
                 timebase: Optional[float] = None):
        super().__init__()
        self.devices = devices
        self.folder = folder
        self.mode = mode  # 0=As Is, 1=AutoScale, 2=Custom
        self.timebase = timebase

    def run(self):
        for device in self.devices:
            if not device.enabled:
                continue
            self.capture_started.emit(device.id)
            try:
                # Generate unique filename
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_name = device.name.replace(" ", "_").replace("/", "-")[:20]
                filename = f"scope_{safe_name}_{timestamp_str}.png"
                filepath = os.path.join(self.folder, filename)
                
                # Capture screenshot based on mode
                if self.mode == 0:
                    # As It Is - capture without any changes
                    self._capture_as_is(device.id, filepath)
                elif self.mode == 1:
                    # AutoScale mode
                    capture_screenshot_display(
                        resource_name=device.id,
                        folder=self.folder,
                        autoscale=True,
                        timebase_scale=None
                    )
                else:
                    # Custom Time Base mode
                    capture_screenshot_display(
                        resource_name=device.id,
                        folder=self.folder,
                        autoscale=False,
                        timebase_scale=self.timebase
                    )
                self.capture_completed.emit(device.id, filepath)
            except Exception as e:
                self.capture_failed.emit(device.id, str(e))
        self.all_completed.emit()

    def _capture_as_is(self, resource_name: str, filepath: str):
        """Capture screenshot without changing any oscilloscope settings."""
        scope = open_scope(resource_name)
        try:
            # Just capture, no AutoScale, no TimeBase changes
            scope.write(':DISPlay:DATA? PNG, COLOR')
            image_data = read_binblock(scope)
            
            with open(filepath, 'wb') as f:
                f.write(image_data)
        finally:
            scope.close()


class DeviceWidget(QFrame):
    """Widget representing a single device in the list."""
    toggled = pyqtSignal(str, bool)

    def __init__(self, device: Device, parent=None):
        super().__init__(parent)
        self.device = device
        self.setup_ui()

    def setup_ui(self):
        self.setObjectName("deviceWidget")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Checkbox
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(self.device.enabled)
        self.checkbox.stateChanged.connect(self._on_checkbox_changed)
        layout.addWidget(self.checkbox)

        # Status indicator
        self.status_indicator = QFrame()
        self.status_indicator.setFixedSize(8, 8)
        self.status_indicator.setObjectName("statusIndicator")
        self.status_indicator.setProperty("connected", self.device.connected)
        layout.addWidget(self.status_indicator)

        # Monitor icon placeholder (using text emoji for simplicity)
        icon_label = QLabel("🖥")
        icon_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(icon_label)

        # Device info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        name_label = QLabel(self.device.name)
        name_label.setObjectName("deviceName")
        info_layout.addWidget(name_label)
        
        details_label = QLabel(f"{self.device.device_type} • {self.device.id}")
        details_label.setObjectName("deviceDetails")
        info_layout.addWidget(details_label)
        
        layout.addLayout(info_layout, 1)

        self.update_style()

    def _on_checkbox_changed(self, state):
        self.device.enabled = state == Qt.CheckState.Checked.value
        self.update_style()
        self.toggled.emit(self.device.id, self.device.enabled)

    def update_style(self):
        if self.device.enabled:
            self.setProperty("selected", True)
        else:
            self.setProperty("selected", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        self.checkbox.setChecked(not self.checkbox.isChecked())


class DevicePanel(QFrame):
    """Panel showing detected VISA devices."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.devices: List[Device] = []
        self.device_widgets: List[DeviceWidget] = []
        self.setup_ui()

    def setup_ui(self):
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("panelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)

        icon_label = QLabel("🔌")
        icon_label.setStyleSheet("font-size: 14px;")
        header_layout.addWidget(icon_label)

        title_label = QLabel("Detected Devices")
        title_label.setObjectName("panelTitle")
        header_layout.addWidget(title_label)

        self.count_label = QLabel("(0/0 active)")
        self.count_label.setObjectName("deviceCount")
        header_layout.addWidget(self.count_label)

        header_layout.addStretch()

        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setObjectName("iconButton")
        self.refresh_btn.setFixedSize(28, 28)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout.addWidget(self.refresh_btn)

        layout.addWidget(header)

        # Device list scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("deviceScrollArea")
        scroll_area.setMaximumHeight(200)

        self.device_container = QWidget()
        self.device_layout = QVBoxLayout(self.device_container)
        self.device_layout.setContentsMargins(8, 8, 8, 8)
        self.device_layout.setSpacing(8)
        self.device_layout.addStretch()

        # Empty state label
        self.empty_label = QLabel("No devices found")
        self.empty_label.setObjectName("emptyLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.device_layout.insertWidget(0, self.empty_label)

        scroll_area.setWidget(self.device_container)
        layout.addWidget(scroll_area)

    def set_devices(self, devices: List[Device]):
        # Clear existing widgets
        for widget in self.device_widgets:
            self.device_layout.removeWidget(widget)
            widget.deleteLater()
        self.device_widgets.clear()
        self.devices = devices

        self.empty_label.setVisible(len(devices) == 0)

        for device in devices:
            widget = DeviceWidget(device)
            widget.toggled.connect(self._on_device_toggled)
            self.device_widgets.append(widget)
            self.device_layout.insertWidget(self.device_layout.count() - 1, widget)

        self.update_count()

    def _on_device_toggled(self, device_id: str, enabled: bool):
        self.update_count()

    def update_count(self):
        enabled_count = sum(1 for d in self.devices if d.enabled)
        total_count = len(self.devices)
        self.count_label.setText(f"({enabled_count}/{total_count} active)")

    def get_enabled_devices(self) -> List[Device]:
        return [d for d in self.devices if d.enabled]

    def set_scanning(self, scanning: bool):
        self.refresh_btn.setEnabled(not scanning)
        if scanning:
            self.empty_label.setText("Scanning for devices...")
        else:
            self.empty_label.setText("No devices found")


class ControlPanel(QFrame):
    """Panel with capture button and oscilloscope settings."""
    capture_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # Capture section
        capture_panel = QFrame()
        capture_panel.setObjectName("panel")
        capture_layout = QVBoxLayout(capture_panel)
        capture_layout.setContentsMargins(0, 0, 0, 0)
        capture_layout.setSpacing(0)

        # Capture header
        capture_header = QFrame()
        capture_header.setObjectName("panelHeader")
        header_layout = QHBoxLayout(capture_header)
        header_layout.setContentsMargins(16, 12, 16, 12)

        icon_label = QLabel("📷")
        icon_label.setStyleSheet("font-size: 14px;")
        header_layout.addWidget(icon_label)

        title_label = QLabel("Capture All")
        title_label.setObjectName("panelTitle")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        capture_layout.addWidget(capture_header)

        # Capture button container
        btn_container = QWidget()
        btn_layout = QVBoxLayout(btn_container)
        btn_layout.setContentsMargins(16, 16, 16, 16)

        self.capture_btn = QPushButton("⚡ Take a Shot")
        self.capture_btn.setObjectName("captureButton")
        self.capture_btn.setFixedHeight(56)
        self.capture_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.capture_btn.clicked.connect(self.capture_requested.emit)
        btn_layout.addWidget(self.capture_btn)

        self.capture_status = QLabel("Enable at least one device")
        self.capture_status.setObjectName("captureStatus")
        self.capture_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(self.capture_status)

        capture_layout.addWidget(btn_container)
        layout.addWidget(capture_panel)

        # Settings section
        settings_panel = QFrame()
        settings_panel.setObjectName("panel")
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(0)

        # Settings header
        settings_header = QFrame()
        settings_header.setObjectName("panelHeader")
        header_layout2 = QHBoxLayout(settings_header)
        header_layout2.setContentsMargins(16, 12, 16, 12)

        icon_label2 = QLabel("⚙")
        icon_label2.setStyleSheet("font-size: 14px;")
        header_layout2.addWidget(icon_label2)

        title_label2 = QLabel("Oscilloscope Settings")
        title_label2.setObjectName("panelTitle")
        header_layout2.addWidget(title_label2)
        header_layout2.addStretch()

        settings_layout.addWidget(settings_header)

        # Settings content
        settings_content = QWidget()
        content_layout = QVBoxLayout(settings_content)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(16)

        # Capture Mode label
        mode_label = QLabel("Capture Mode")
        mode_label.setObjectName("settingLabel")
        content_layout.addWidget(mode_label)

        # Three mode buttons in a row
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)
        
        self.mode_btn_asis = QPushButton("As It Is")
        self.mode_btn_asis.setObjectName("modeButton")
        self.mode_btn_asis.setProperty("active", True)
        self.mode_btn_asis.setFixedHeight(36)
        self.mode_btn_asis.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_btn_asis.clicked.connect(lambda: self._on_mode_changed(0))
        buttons_layout.addWidget(self.mode_btn_asis)
        
        self.mode_btn_auto = QPushButton("AutoScale")
        self.mode_btn_auto.setObjectName("modeButton")
        self.mode_btn_auto.setProperty("active", False)
        self.mode_btn_auto.setFixedHeight(36)
        self.mode_btn_auto.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_btn_auto.clicked.connect(lambda: self._on_mode_changed(1))
        buttons_layout.addWidget(self.mode_btn_auto)
        
        self.mode_btn_custom = QPushButton("Custom Time Base")
        self.mode_btn_custom.setObjectName("modeButton")
        self.mode_btn_custom.setProperty("active", False)
        self.mode_btn_custom.setFixedHeight(36)
        self.mode_btn_custom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_btn_custom.clicked.connect(lambda: self._on_mode_changed(2))
        buttons_layout.addWidget(self.mode_btn_custom)
        
        content_layout.addLayout(buttons_layout)
        
        self.current_mode = 0  # 0=As Is, 1=AutoScale, 2=Custom

        # TimeBase input (hidden by default)
        self.timebase_container = QWidget()
        self.timebase_container.setVisible(False)  # Hidden by default
        timebase_layout = QVBoxLayout(self.timebase_container)
        timebase_layout.setContentsMargins(0, 0, 0, 0)
        timebase_layout.setSpacing(8)

        timebase_label = QLabel("Time Base (sec/div)")
        timebase_label.setObjectName("settingLabel")
        timebase_layout.addWidget(timebase_label)

        self.timebase_input = QLineEdit()
        self.timebase_input.setObjectName("settingInput")
        self.timebase_input.setPlaceholderText("0.001 (default)")
        timebase_layout.addWidget(self.timebase_input)

        timebase_hint = QLabel("Leave empty for default (1ms/div)")
        timebase_hint.setObjectName("settingHint")
        timebase_layout.addWidget(timebase_hint)

        content_layout.addWidget(self.timebase_container)

        settings_layout.addWidget(settings_content)
        layout.addWidget(settings_panel)

    def _on_mode_changed(self, mode: int):
        """Handle mode change: 0=As Is, 1=AutoScale, 2=Custom"""
        self.current_mode = mode
        
        # Update button states
        self.mode_btn_asis.setProperty("active", mode == 0)
        self.mode_btn_auto.setProperty("active", mode == 1)
        self.mode_btn_custom.setProperty("active", mode == 2)
        
        # Refresh button styles
        for btn in [self.mode_btn_asis, self.mode_btn_auto, self.mode_btn_custom]:
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        
        # Show/hide timebase input - only visible for Custom mode
        self.timebase_container.setVisible(mode == 2)

    def update_capture_button(self, enabled_count: int, is_capturing: bool):
        if is_capturing:
            self.capture_btn.setText("⏳ Capturing...")
            self.capture_btn.setEnabled(False)
            self.capture_status.setText("Please wait...")
            self.capture_status.setObjectName("captureStatus")
        elif enabled_count == 0:
            self.capture_btn.setEnabled(False)
            self.capture_status.setText("Enable at least one device")
            self.capture_status.setObjectName("captureStatus")
        else:
            self.capture_btn.setText("⚡ Take a Shot")
            self.capture_btn.setEnabled(True)
            device_word = "device" if enabled_count == 1 else "devices"
            self.capture_status.setText(f"{enabled_count} {device_word} will be triggered simultaneously")
            self.capture_status.setObjectName("captureStatusActive")
        self.capture_status.style().unpolish(self.capture_status)
        self.capture_status.style().polish(self.capture_status)

    def get_mode(self) -> int:
        """Returns current mode: 0=As Is, 1=AutoScale, 2=Custom"""
        return self.current_mode

    def get_autoscale(self) -> bool:
        """Deprecated - use get_mode() instead"""
        return self.current_mode == 1

    def get_timebase(self) -> Optional[float]:
        text = self.timebase_input.text().strip()
        if text:
            try:
                return float(text)
            except ValueError:
                return None
        return None


class TerminalPanel(QFrame):
    """Panel showing console output/logs."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("panelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)

        icon_label = QLabel("💻")
        icon_label.setStyleSheet("font-size: 14px;")
        header_layout.addWidget(icon_label)

        title_label = QLabel("Console Output")
        title_label.setObjectName("panelTitle")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        self.clear_btn = QPushButton("🗑")
        self.clear_btn.setObjectName("iconButton")
        self.clear_btn.setFixedSize(28, 28)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self.clear_logs)
        header_layout.addWidget(self.clear_btn)

        layout.addWidget(header)

        # Terminal content
        self.terminal = QTextEdit()
        self.terminal.setObjectName("terminal")
        self.terminal.setReadOnly(True)
        self.terminal.setMinimumHeight(180)
        layout.addWidget(self.terminal)

        # Initial message
        self.add_log("info", "Ready. Waiting for commands...")

    def add_log(self, log_type: str, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        colors = {
            "info": "#8B949E",
            "success": "#3FB950",
            "error": "#F85149",
            "warning": "#D29922"
        }
        prefixes = {
            "info": "[INFO]",
            "success": "[OK]",
            "error": "[ERROR]",
            "warning": "[WARN]"
        }
        
        color = colors.get(log_type, colors["info"])
        prefix = prefixes.get(log_type, prefixes["info"])
        
        html = f'<span style="color: #6E7681;">[{timestamp}]</span> <span style="color: {color};">{prefix}</span> <span style="color: #C9D1D9;">{message}</span><br>'
        self.terminal.insertHtml(html)
        self.terminal.verticalScrollBar().setValue(self.terminal.verticalScrollBar().maximum())

    def clear_logs(self):
        self.terminal.clear()
        self.add_log("info", "Console cleared. Ready...")


class MainWindow(QMainWindow):
    """Main application window."""
    def __init__(self):
        super().__init__()
        self.scan_thread: Optional[ScanThread] = None
        self.capture_thread: Optional[CaptureThread] = None
        self.setup_ui()
        self.load_stylesheet()
        
        # Auto-scan on startup
        QTimer.singleShot(500, self.scan_devices)

    def setup_ui(self):
        self.setWindowTitle("Oscilloscope Screenshot Tool")
        self.setMinimumSize(500, 700)
        self.resize(520, 750)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(20)

        # Header
        header = QFrame()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 16)

        icon_container = QFrame()
        icon_container.setObjectName("headerIconContainer")
        icon_container.setFixedSize(44, 44)
        icon_layout = QVBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_label = QLabel("📊")
        icon_label.setStyleSheet("font-size: 20px;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(icon_label)
        header_layout.addWidget(icon_container)

        title_container = QVBoxLayout()
        title_container.setSpacing(2)
        
        title = QLabel("Oscilloscope Screenshot Tool")
        title.setObjectName("appTitle")
        title_container.addWidget(title)
        
        subtitle = QLabel("Simultaneous capture from multiple VISA instruments")
        subtitle.setObjectName("appSubtitle")
        title_container.addWidget(subtitle)
        
        header_layout.addLayout(title_container)
        header_layout.addStretch()

        main_layout.addWidget(header)

        # Separator
        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFixedHeight(1)
        main_layout.addWidget(separator)

        # Device panel
        self.device_panel = DevicePanel()
        self.device_panel.refresh_btn.clicked.connect(self.scan_devices)
        main_layout.addWidget(self.device_panel)

        # Control panel
        self.control_panel = ControlPanel()
        self.control_panel.capture_requested.connect(self.capture_screenshots)
        main_layout.addWidget(self.control_panel)

        # Terminal panel
        self.terminal_panel = TerminalPanel()
        main_layout.addWidget(self.terminal_panel, 1)

        # Footer
        footer = QLabel("PyVISA Multi-Instrument Control • v1.0")
        footer.setObjectName("footer")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(footer)

        # Credits with GitHub link
        credits = QLabel('Created by Dariusz Piskorowski • <a href="https://github.com/DariuszPiskorowski/pyvisa.git" style="color: #484F58;">https://github.com/DariuszPiskorowski/pyvisa.git</a>')
        credits.setObjectName("credits")
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits.setOpenExternalLinks(True)  # Allow clicking the link to open in browser
        credits.setStyleSheet("color: #484F58; font-size: 10px;")
        main_layout.addWidget(credits)

        # Connect device toggle to update capture button
        for widget in self.device_panel.device_widgets:
            widget.toggled.connect(self._update_capture_button)

    def load_stylesheet(self):
        style_path = os.path.join(os.path.dirname(__file__), "style.qss")
        if os.path.exists(style_path):
            with open(style_path, "r") as f:
                self.setStyleSheet(f.read())
        else:
            # Fallback inline stylesheet
            self.setStyleSheet(DARK_STYLESHEET)

    def _update_capture_button(self):
        enabled_count = len(self.device_panel.get_enabled_devices())
        is_capturing = self.capture_thread is not None and self.capture_thread.isRunning()
        self.control_panel.update_capture_button(enabled_count, is_capturing)

    def scan_devices(self):
        if self.scan_thread and self.scan_thread.isRunning():
            return

        self.device_panel.set_scanning(True)
        self.terminal_panel.add_log("info", "Scanning for VISA instruments...")

        self.scan_thread = ScanThread()
        self.scan_thread.devices_found.connect(self._on_devices_found)
        self.scan_thread.error_occurred.connect(self._on_scan_error)
        self.scan_thread.start()

    def _on_devices_found(self, devices: List[Device]):
        self.device_panel.set_scanning(False)
        self.device_panel.set_devices(devices)
        
        # Reconnect toggle signals
        for widget in self.device_panel.device_widgets:
            widget.toggled.connect(self._update_capture_button)
        
        if devices:
            self.terminal_panel.add_log("success", f"Found {len(devices)} device(s)")
        else:
            self.terminal_panel.add_log("warning", "No VISA devices found")
        
        self._update_capture_button()

    def _on_scan_error(self, error: str):
        self.device_panel.set_scanning(False)
        self.terminal_panel.add_log("error", f"Scan failed: {error}")

    def capture_screenshots(self):
        enabled_devices = self.device_panel.get_enabled_devices()
        if not enabled_devices:
            return

        # Get settings
        mode = self.control_panel.get_mode()
        timebase = self.control_panel.get_timebase()
        
        # Default save folder
        folder = os.path.join(os.path.expanduser("~"), "Pictures", "Oscilloscope")
        os.makedirs(folder, exist_ok=True)

        self.terminal_panel.add_log("info", f"Starting capture on {len(enabled_devices)} device(s)...")
        
        if mode == 0:
            self.terminal_panel.add_log("info", "Mode: As It Is (no changes)")
        elif mode == 1:
            self.terminal_panel.add_log("info", "Mode: AutoScale enabled")
        else:
            tb = timebase if timebase else TIMEBASE_SECONDS_PER_DIVISION
            self.terminal_panel.add_log("info", f"Mode: Custom TimeBase ({tb} sec/div)")

        self._update_capture_button()

        self.capture_thread = CaptureThread(enabled_devices, folder, mode, timebase)
        self.capture_thread.capture_started.connect(self._on_capture_started)
        self.capture_thread.capture_completed.connect(self._on_capture_completed)
        self.capture_thread.capture_failed.connect(self._on_capture_failed)
        self.capture_thread.all_completed.connect(self._on_all_captures_completed)
        self.capture_thread.start()

        self.control_panel.update_capture_button(len(enabled_devices), True)

    def _on_capture_started(self, device_id: str):
        self.terminal_panel.add_log("info", f"Capturing from {device_id}...")

    def _on_capture_completed(self, device_id: str, filepath: str):
        self.terminal_panel.add_log("success", f"Screenshot saved: {os.path.basename(filepath)}")

    def _on_capture_failed(self, device_id: str, error: str):
        self.terminal_panel.add_log("error", f"Failed {device_id}: {error}")

    def _on_all_captures_completed(self):
        self.terminal_panel.add_log("success", "All captures completed!")
        self._update_capture_button()


# Fallback dark stylesheet (loaded from style.qss if available)
DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0D1117;
    color: #C9D1D9;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}

#appTitle {
    font-size: 18px;
    font-weight: 600;
    color: #F0F6FC;
}

#appSubtitle {
    font-size: 12px;
    color: #8B949E;
}

#headerIconContainer {
    background-color: rgba(56, 139, 253, 0.15);
    border-radius: 10px;
}

#separator {
    background-color: #21262D;
}

#panel {
    background-color: #161B22;
    border: 1px solid #30363D;
    border-radius: 12px;
}

#panelHeader {
    border-bottom: 1px solid #21262D;
}

#panelTitle {
    font-weight: 500;
    color: #C9D1D9;
}

#deviceCount {
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 11px;
    color: #58A6FF;
}

#iconButton {
    background-color: transparent;
    border: none;
    border-radius: 6px;
    font-size: 14px;
}

#iconButton:hover {
    background-color: #21262D;
}

#deviceScrollArea {
    background-color: transparent;
    border: none;
}

#deviceWidget {
    background-color: #21262D;
    border: 1px solid #30363D;
    border-radius: 8px;
}

#deviceWidget:hover {
    border-color: #58A6FF;
}

#deviceWidget[selected="true"] {
    background-color: rgba(56, 139, 253, 0.1);
    border-color: #58A6FF;
}

#statusIndicator {
    border-radius: 4px;
}

#statusIndicator[connected="true"] {
    background-color: #3FB950;
}

#statusIndicator[connected="false"] {
    background-color: #F85149;
}

#deviceName {
    font-weight: 500;
    color: #C9D1D9;
}

#deviceDetails {
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 11px;
    color: #8B949E;
}

#emptyLabel {
    color: #8B949E;
    padding: 24px;
}

#captureButton {
    background-color: #238636;
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
}

#captureButton:hover {
    background-color: #2EA043;
}

#captureButton:disabled {
    background-color: #21262D;
    color: #484F58;
}

#captureStatus {
    font-size: 11px;
    color: #8B949E;
    margin-top: 8px;
}

#captureStatusActive {
    font-size: 11px;
    color: #58A6FF;
    font-weight: 500;
    margin-top: 8px;
}

#settingLabel {
    font-weight: 500;
    color: #C9D1D9;
}

#toggleLabel {
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 11px;
    color: #C9D1D9;
}

#toggleLabelInactive {
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 11px;
    color: #484F58;
}

#toggleSwitch::indicator {
    width: 36px;
    height: 20px;
}

#settingInput {
    background-color: #21262D;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 8px 12px;
    color: #C9D1D9;
    font-family: 'Consolas', 'Monaco', monospace;
}

#settingInput:focus {
    border-color: #58A6FF;
}

#settingHint {
    font-size: 11px;
    color: #8B949E;
}

#terminal {
    background-color: #0D1117;
    border: none;
    border-top: 1px solid #21262D;
    padding: 12px;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 12px;
}

#footer {
    font-size: 11px;
    color: #484F58;
    padding-top: 12px;
    border-top: 1px solid #21262D;
}

QScrollBar:vertical {
    background-color: #0D1117;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background-color: #30363D;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #484F58;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #30363D;
    background-color: #21262D;
}

QCheckBox::indicator:checked {
    background-color: #58A6FF;
    border-color: #58A6FF;
}
"""


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
