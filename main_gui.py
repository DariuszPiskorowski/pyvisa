"""
PyVISA Instrument Capture Tool - GUI
A PyQt6-based GUI for screenshots and measurements from multiple VISA instruments.
"""
import sys
import os
import time
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QLineEdit, QScrollArea,
    QFrame, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings

import pyvisa

from oscilloscope_control import (
    TIMEBASE_SECONDS_PER_DIVISION,
    capture_screenshot_display,
    detect_supported_instrument_type,
    get_dmm6500_unit,
    get_oscilloscope_vendor,
    measure_dmm6500,
    open_scope,
    read_binblock,
)


@dataclass
class Device:
    """Represents a VISA device."""
    id: str
    name: str
    interface_type: str
    instrument_type: str = "unknown"
    idn: str = ""
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
                interface_type = self._detect_interface_type(resource)
                idn = ""
                name = resource
                inst = None

                try:
                    inst = rm.open_resource(resource)
                    inst.timeout = 2000
                    inst.write_termination = '\n'
                    inst.read_termination = '\n'
                    idn = inst.query("*IDN?").strip()
                    name = self._extract_display_name(idn, resource)
                except Exception:
                    name = resource.split("::")[3] if len(resource.split("::")) > 3 else resource
                finally:
                    if inst is not None:
                        try:
                            inst.close()
                        except Exception:
                            pass

                instrument_type = detect_supported_instrument_type(resource, idn)
                
                devices.append(Device(
                    id=resource,
                    name=name,
                    interface_type=interface_type,
                    instrument_type=instrument_type,
                    idn=idn,
                    connected=True,
                    enabled=False
                ))
            self.devices_found.emit(devices)
        except Exception as e:
            self.error_occurred.emit(str(e))

    @staticmethod
    def _detect_interface_type(resource: str) -> str:
        if "USB" in resource:
            return "USB"
        if "GPIB" in resource:
            return "GPIB"
        if "TCPIP" in resource:
            return "TCP/IP"
        if "ASRL" in resource:
            return "Serial"
        return "Unknown"

    @staticmethod
    def _extract_display_name(idn: str, resource: str) -> str:
        if not idn:
            return resource
        parts = [part.strip() for part in idn.split(',')]
        if len(parts) >= 2 and parts[1]:
            return parts[1]
        return idn[:30]


class CaptureThread(QThread):
    """Thread for capturing data from enabled instruments without blocking the UI."""
    capture_started = pyqtSignal(str)
    capture_completed = pyqtSignal(str, str)  # device_id, filepath
    capture_failed = pyqtSignal(str, str)  # device_id, error
    all_completed = pyqtSignal()

    def __init__(self,
                 devices: List[Device],
                 folder: str,
                 mode: int,
                 timebase: Optional[float] = None,
                 dmm_measurement_function: str = 'VOLT:DC',
                 dmm_measurement_range: Optional[float] = None,
                 dmm_apply_configuration: bool = True):
        super().__init__()
        self.devices = devices
        self.folder = folder
        self.mode = mode  # 0=As Is, 1=AutoScale, 2=Custom
        self.timebase = timebase
        self.dmm_measurement_function = dmm_measurement_function
        self.dmm_measurement_range = dmm_measurement_range
        self.dmm_apply_configuration = dmm_apply_configuration

    def run(self):
        for device in self.devices:
            if not device.enabled:
                continue
            self.capture_started.emit(device.id)
            try:
                if device.instrument_type == 'dmm6500':
                    filepath = self._capture_dmm_measurement(device)
                else:
                    filepath = self._capture_oscilloscope(device)

                self.capture_completed.emit(device.id, filepath)
            except Exception as e:
                self.capture_failed.emit(device.id, str(e))
        self.all_completed.emit()

    def _capture_oscilloscope(self, device: Device) -> str:
        if self.mode == 0:
            return self._capture_scope_as_is(device)
        if self.mode == 1:
            return capture_screenshot_display(
                resource_name=device.id,
                folder=self.folder,
                autoscale=True,
                timebase_scale=None,
            )
        return capture_screenshot_display(
            resource_name=device.id,
            folder=self.folder,
            autoscale=False,
            timebase_scale=self.timebase,
        )

    def _capture_scope_as_is(self, device: Device) -> str:
        """Capture oscilloscope screenshot without changing any settings."""
        vendor = get_oscilloscope_vendor(device.id)
        ext = 'bmp' if vendor == 'siglent' else 'png'
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = self._safe_name(device.name)
        filename = f"scope_{safe_name}_{timestamp_str}.{ext}"
        filepath = os.path.join(self.folder, filename)

        os.makedirs(self.folder, exist_ok=True)
        scope = open_scope(device.id)
        try:
            if vendor == 'siglent':
                scope.write(':SCDP')
                time.sleep(1.0)
                image_data = scope.read_raw()
            else:
                scope.write(':DISPlay:DATA? PNG, COLOR')
                image_data = read_binblock(scope)

            with open(filepath, 'wb') as f:
                f.write(image_data)
        finally:
            scope.close()

        return filepath

    def _capture_dmm_measurement(self, device: Device) -> str:
        """Capture a single DMM6500 reading and save it to a text file."""
        timestamp = datetime.now()
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        safe_name = self._safe_name(device.name)
        filename = f"dmm6500_{safe_name}_{timestamp_str}.txt"
        filepath = os.path.join(self.folder, filename)

        os.makedirs(self.folder, exist_ok=True)

        value = measure_dmm6500(
            resource_name=device.id,
            measurement_function=self.dmm_measurement_function,
            measurement_range=self.dmm_measurement_range,
            apply_configuration=self.dmm_apply_configuration,
        )
        unit = get_dmm6500_unit(self.dmm_measurement_function)
        if not self.dmm_apply_configuration:
            mode_text = 'CUSTOM (AS IS)'
            function_text = 'AS_IS'
            range_text = 'AS_IS'
        else:
            mode_text = 'AUTO'
            function_text = self.dmm_measurement_function
            range_text = 'AUTO' if self.dmm_measurement_range is None else str(self.dmm_measurement_range)

        with open(filepath, 'w', encoding='utf-8') as result_file:
            result_file.write(f"Timestamp: {timestamp.isoformat()}\n")
            result_file.write(f"Device: {device.id}\n")
            result_file.write(f"IDN: {device.idn or 'N/A'}\n")
            result_file.write(f"DMM Mode: {mode_text}\n")
            result_file.write(f"Measurement Function: {function_text}\n")
            result_file.write(f"Measurement Range: {range_text}\n")
            result_file.write(f"Value: {value} {unit}\n")

        return filepath

    @staticmethod
    def _safe_name(value: str) -> str:
        return value.replace(" ", "_").replace("/", "-")[:20]


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

        icon_text = "📏" if self.device.instrument_type == 'dmm6500' else "🖥"
        icon_label = QLabel(icon_text)
        icon_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(icon_label)

        # Device info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        name_label = QLabel(self.device.name)
        name_label.setObjectName("deviceName")
        info_layout.addWidget(name_label)
        
        instrument_label = self._get_instrument_label()
        details_label = QLabel(f"{instrument_label} • {self.device.interface_type} • {self.device.id}")
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

    def _get_instrument_label(self) -> str:
        if self.device.instrument_type == 'oscilloscope':
            return 'Oscilloscope'
        if self.device.instrument_type == 'dmm6500':
            return 'Keithley DMM6500'
        return 'Unknown Instrument'


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
    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_instrument_type = 'oscilloscope'
        self._dmm_mm_mode = 'auto'  # auto|custom
        self._dmm_mm_function = 'V'
        self._dmm_mm_signal = 'DC'
        self._dmm_mixed_function = 'CURR:DC'
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Capture section
        capture_panel = QFrame()
        capture_panel.setObjectName("panel")
        capture_layout = QVBoxLayout(capture_panel)
        capture_layout.setContentsMargins(0, 0, 0, 0)
        capture_layout.setSpacing(0)

        # Capture button container
        btn_container = QWidget()
        btn_layout = QVBoxLayout(btn_container)
        btn_layout.setContentsMargins(14, 12, 14, 12)

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

        # Settings content
        settings_content = QWidget()
        content_layout = QVBoxLayout(settings_content)
        content_layout.setContentsMargins(14, 12, 14, 12)
        content_layout.setSpacing(12)

        # Active instrument label
        self.instrument_label = QLabel("Active Instrument: Oscilloscope")
        self.instrument_label.setObjectName("settingLabel")
        content_layout.addWidget(self.instrument_label)

        # Oscilloscope settings container
        self.scope_settings_container = QWidget()
        scope_settings_layout = QVBoxLayout(self.scope_settings_container)
        scope_settings_layout.setContentsMargins(0, 0, 0, 0)
        scope_settings_layout.setSpacing(16)

        mode_label = QLabel("Capture Mode")
        mode_label.setObjectName("settingLabel")
        scope_settings_layout.addWidget(mode_label)

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

        scope_settings_layout.addLayout(buttons_layout)

        self.current_mode = 0  # 0=As Is, 1=AutoScale, 2=Custom

        self.timebase_container = QWidget()
        self.timebase_container.setVisible(False)
        timebase_layout = QVBoxLayout(self.timebase_container)
        timebase_layout.setContentsMargins(0, 0, 0, 0)
        timebase_layout.setSpacing(8)

        timebase_label = QLabel("Time Base (sec/div)")
        timebase_label.setObjectName("settingLabel")
        timebase_layout.addWidget(timebase_label)

        self.timebase_input = QLineEdit()
        self.timebase_input.setObjectName("settingInput")
        self.timebase_input.setPlaceholderText("0.001 (default)")
        self.timebase_input.textChanged.connect(self.settings_changed.emit)
        timebase_layout.addWidget(self.timebase_input)

        timebase_hint = QLabel("Leave empty for default (1ms/div)")
        timebase_hint.setObjectName("settingHint")
        timebase_layout.addWidget(timebase_hint)

        scope_settings_layout.addWidget(self.timebase_container)
        content_layout.addWidget(self.scope_settings_container)

        # DMM6500 settings container (multimeter only)
        self.dmm_settings_container = QWidget()
        dmm_layout = QVBoxLayout(self.dmm_settings_container)
        dmm_layout.setContentsMargins(0, 0, 0, 0)
        dmm_layout.setSpacing(12)

        dmm_function_label = QLabel("Multimeter Mode")
        dmm_function_label.setObjectName("settingLabel")
        dmm_layout.addWidget(dmm_function_label)

        mm_mode_layout = QHBoxLayout()
        mm_mode_layout.setSpacing(8)

        self.mm_mode_auto_btn = QPushButton("Auto")
        self.mm_mode_auto_btn.setObjectName("modeButton")
        self.mm_mode_auto_btn.setProperty("active", True)
        self.mm_mode_auto_btn.setFixedHeight(36)
        self.mm_mode_auto_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mm_mode_auto_btn.clicked.connect(lambda: self._on_mm_mode_changed('auto'))
        mm_mode_layout.addWidget(self.mm_mode_auto_btn)

        self.mm_mode_custom_btn = QPushButton("Custom")
        self.mm_mode_custom_btn.setObjectName("modeButton")
        self.mm_mode_custom_btn.setProperty("active", False)
        self.mm_mode_custom_btn.setFixedHeight(36)
        self.mm_mode_custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mm_mode_custom_btn.clicked.connect(lambda: self._on_mm_mode_changed('custom'))
        mm_mode_layout.addWidget(self.mm_mode_custom_btn)

        dmm_layout.addLayout(mm_mode_layout)

        dmm_mode_hint = QLabel("Custom = As It Is on multimeter. Auto = force AUTO range.")
        dmm_mode_hint.setObjectName("settingHint")
        dmm_layout.addWidget(dmm_mode_hint)

        dmm_function_label2 = QLabel("Measurement Type")
        dmm_function_label2.setObjectName("settingLabel")
        dmm_layout.addWidget(dmm_function_label2)

        mm_function_layout = QHBoxLayout()
        mm_function_layout.setSpacing(8)

        self.mm_func_v_btn = QPushButton("V")
        self.mm_func_v_btn.setObjectName("modeButton")
        self.mm_func_v_btn.setProperty("active", True)
        self.mm_func_v_btn.setFixedHeight(36)
        self.mm_func_v_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mm_func_v_btn.clicked.connect(lambda: self._on_mm_function_changed('V'))
        mm_function_layout.addWidget(self.mm_func_v_btn)

        self.mm_func_a_btn = QPushButton("A")
        self.mm_func_a_btn.setObjectName("modeButton")
        self.mm_func_a_btn.setProperty("active", False)
        self.mm_func_a_btn.setFixedHeight(36)
        self.mm_func_a_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mm_func_a_btn.clicked.connect(lambda: self._on_mm_function_changed('A'))
        mm_function_layout.addWidget(self.mm_func_a_btn)

        self.mm_func_freq_btn = QPushButton("Freq")
        self.mm_func_freq_btn.setObjectName("modeButton")
        self.mm_func_freq_btn.setProperty("active", False)
        self.mm_func_freq_btn.setFixedHeight(36)
        self.mm_func_freq_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mm_func_freq_btn.clicked.connect(lambda: self._on_mm_function_changed('FREQ'))
        mm_function_layout.addWidget(self.mm_func_freq_btn)

        self.mm_func_period_btn = QPushButton("Period")
        self.mm_func_period_btn.setObjectName("modeButton")
        self.mm_func_period_btn.setProperty("active", False)
        self.mm_func_period_btn.setFixedHeight(36)
        self.mm_func_period_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mm_func_period_btn.clicked.connect(lambda: self._on_mm_function_changed('PERIOD'))
        mm_function_layout.addWidget(self.mm_func_period_btn)

        self.mm_func_ohms_btn = QPushButton("Ohms")
        self.mm_func_ohms_btn.setObjectName("modeButton")
        self.mm_func_ohms_btn.setProperty("active", False)
        self.mm_func_ohms_btn.setFixedHeight(36)
        self.mm_func_ohms_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mm_func_ohms_btn.clicked.connect(lambda: self._on_mm_function_changed('OHMS'))
        mm_function_layout.addWidget(self.mm_func_ohms_btn)

        dmm_layout.addLayout(mm_function_layout)

        self.mm_signal_container = QWidget()
        mm_signal_layout = QVBoxLayout(self.mm_signal_container)
        mm_signal_layout.setContentsMargins(0, 0, 0, 0)
        mm_signal_layout.setSpacing(8)

        mm_signal_label = QLabel("Signal Type")
        mm_signal_label.setObjectName("settingLabel")
        mm_signal_layout.addWidget(mm_signal_label)

        mm_signal_buttons_layout = QHBoxLayout()
        mm_signal_buttons_layout.setSpacing(8)

        self.mm_signal_dc_btn = QPushButton("DC")
        self.mm_signal_dc_btn.setObjectName("modeButton")
        self.mm_signal_dc_btn.setProperty("active", True)
        self.mm_signal_dc_btn.setFixedHeight(36)
        self.mm_signal_dc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mm_signal_dc_btn.clicked.connect(lambda: self._on_mm_signal_changed('DC'))
        mm_signal_buttons_layout.addWidget(self.mm_signal_dc_btn)

        self.mm_signal_ac_btn = QPushButton("AC")
        self.mm_signal_ac_btn.setObjectName("modeButton")
        self.mm_signal_ac_btn.setProperty("active", False)
        self.mm_signal_ac_btn.setFixedHeight(36)
        self.mm_signal_ac_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mm_signal_ac_btn.clicked.connect(lambda: self._on_mm_signal_changed('AC'))
        mm_signal_buttons_layout.addWidget(self.mm_signal_ac_btn)

        mm_signal_layout.addLayout(mm_signal_buttons_layout)
        dmm_layout.addWidget(self.mm_signal_container)

        mm_function_hint = QLabel("Signal Type applies only to V/A.")
        mm_function_hint.setObjectName("settingHint")
        dmm_layout.addWidget(mm_function_hint)

        self._update_mm_signal_visibility()

        # Mixed mode DMM settings container
        self.mixed_dmm_settings_container = QWidget()
        mixed_layout = QVBoxLayout(self.mixed_dmm_settings_container)
        mixed_layout.setContentsMargins(0, 0, 0, 0)
        mixed_layout.setSpacing(12)

        mixed_label = QLabel("Mixed Mode DMM (AUTO range)")
        mixed_label.setObjectName("settingLabel")
        mixed_layout.addWidget(mixed_label)

        mixed_buttons_layout = QHBoxLayout()
        mixed_buttons_layout.setSpacing(8)

        self.mixed_dmm_ac_btn = QPushButton("A AC")
        self.mixed_dmm_ac_btn.setObjectName("modeButton")
        self.mixed_dmm_ac_btn.setProperty("active", False)
        self.mixed_dmm_ac_btn.setFixedHeight(36)
        self.mixed_dmm_ac_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mixed_dmm_ac_btn.clicked.connect(lambda: self._on_mixed_dmm_function_changed('CURR:AC'))
        mixed_buttons_layout.addWidget(self.mixed_dmm_ac_btn)

        self.mixed_dmm_dc_btn = QPushButton("A DC")
        self.mixed_dmm_dc_btn.setObjectName("modeButton")
        self.mixed_dmm_dc_btn.setProperty("active", True)
        self.mixed_dmm_dc_btn.setFixedHeight(36)
        self.mixed_dmm_dc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mixed_dmm_dc_btn.clicked.connect(lambda: self._on_mixed_dmm_function_changed('CURR:DC'))
        mixed_buttons_layout.addWidget(self.mixed_dmm_dc_btn)

        mixed_layout.addLayout(mixed_buttons_layout)

        mixed_hint = QLabel("In mixed mode DMM uses AUTO range automatically.")
        mixed_hint.setObjectName("settingHint")
        mixed_layout.addWidget(mixed_hint)

        content_layout.addWidget(self.mixed_dmm_settings_container)
        self.mixed_dmm_settings_container.setVisible(False)

        content_layout.addWidget(self.dmm_settings_container)
        self.dmm_settings_container.setVisible(False)

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
        self.settings_changed.emit()

    def set_selected_instrument_type(self, instrument_type: str):
        """Switches settings panel content based on selected instrument type."""
        resolved = instrument_type if instrument_type in ('oscilloscope', 'dmm6500', 'mixed', 'none') else 'oscilloscope'
        self.selected_instrument_type = resolved

        if resolved == 'none':
            self.instrument_label.setText("Active Panel: Layout (no active device)")
            self.scope_settings_container.setVisible(True)
            self.dmm_settings_container.setVisible(False)
            self.mixed_dmm_settings_container.setVisible(False)
        elif resolved == 'dmm6500':
            self.instrument_label.setText("Active Instrument: Keithley DMM6500")
            self.scope_settings_container.setVisible(False)
            self.dmm_settings_container.setVisible(True)
            self.mixed_dmm_settings_container.setVisible(False)
        elif resolved == 'mixed':
            self.instrument_label.setText("Active Instrument: Mixed (Oscilloscope + DMM6500)")
            self.scope_settings_container.setVisible(True)
            self.dmm_settings_container.setVisible(False)
            self.mixed_dmm_settings_container.setVisible(True)
        else:
            self.instrument_label.setText("Active Instrument: Oscilloscope")
            self.scope_settings_container.setVisible(True)
            self.dmm_settings_container.setVisible(False)
            self.mixed_dmm_settings_container.setVisible(False)

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
                value = float(text)
                if value <= 0:
                    return None
                return value
            except ValueError:
                return None
        return None

    def get_timebase_text(self) -> str:
        return self.timebase_input.text().strip()

    def get_dmm_measurement_function(self) -> str:
        if self.selected_instrument_type == 'mixed':
            return self._dmm_mixed_function

        if self._dmm_mm_function == 'V':
            return 'VOLT:AC' if self._dmm_mm_signal == 'AC' else 'VOLT:DC'
        if self._dmm_mm_function == 'A':
            return 'CURR:AC' if self._dmm_mm_signal == 'AC' else 'CURR:DC'
        if self._dmm_mm_function == 'FREQ':
            return 'FREQ'
        if self._dmm_mm_function == 'PERIOD':
            return 'PER'
        if self._dmm_mm_function == 'OHMS':
            return 'RES'
        return 'VOLT:DC'

    def get_dmm_measurement_range(self) -> Optional[float]:
        return None

    def get_dmm_measurement_range_text(self) -> str:
        return ''

    def get_dmm_apply_configuration(self) -> bool:
        if self.selected_instrument_type == 'mixed':
            return True
        return self._dmm_mm_mode == 'auto'

    def _on_mm_mode_changed(self, mode: str):
        self._dmm_mm_mode = mode
        self.mm_mode_auto_btn.setProperty("active", mode == 'auto')
        self.mm_mode_custom_btn.setProperty("active", mode == 'custom')
        self._refresh_button_style(self.mm_mode_auto_btn)
        self._refresh_button_style(self.mm_mode_custom_btn)
        self.settings_changed.emit()

    def _on_mm_function_changed(self, function_code: str):
        self._dmm_mm_function = function_code
        buttons = {
            'V': self.mm_func_v_btn,
            'A': self.mm_func_a_btn,
            'FREQ': self.mm_func_freq_btn,
            'PERIOD': self.mm_func_period_btn,
            'OHMS': self.mm_func_ohms_btn,
        }
        for code, button in buttons.items():
            button.setProperty("active", code == function_code)
            self._refresh_button_style(button)
        self._update_mm_signal_visibility()
        self.settings_changed.emit()

    def _on_mm_signal_changed(self, signal_code: str):
        self._dmm_mm_signal = signal_code
        self.mm_signal_dc_btn.setProperty("active", signal_code == 'DC')
        self.mm_signal_ac_btn.setProperty("active", signal_code == 'AC')
        self._refresh_button_style(self.mm_signal_dc_btn)
        self._refresh_button_style(self.mm_signal_ac_btn)
        self.settings_changed.emit()

    def _on_mixed_dmm_function_changed(self, function_code: str):
        self._dmm_mixed_function = function_code
        self.mixed_dmm_ac_btn.setProperty("active", function_code == 'CURR:AC')
        self.mixed_dmm_dc_btn.setProperty("active", function_code == 'CURR:DC')
        self._refresh_button_style(self.mixed_dmm_ac_btn)
        self._refresh_button_style(self.mixed_dmm_dc_btn)
        self.settings_changed.emit()

    def set_scope_mode(self, mode: int):
        if mode not in (0, 1, 2):
            return
        self._on_mode_changed(mode)

    def set_timebase_text(self, value: str):
        self.timebase_input.setText(value)

    def set_mm_mode(self, mode: str):
        if mode not in ('auto', 'custom'):
            return
        self._on_mm_mode_changed(mode)

    def set_mm_function(self, function_code: str):
        if function_code not in ('V', 'A', 'FREQ', 'PERIOD', 'OHMS'):
            return
        self._on_mm_function_changed(function_code)

    def set_mm_signal(self, signal_code: str):
        if signal_code not in ('DC', 'AC'):
            return
        self._on_mm_signal_changed(signal_code)

    def set_mixed_dmm_function(self, function_code: str):
        if function_code not in ('CURR:AC', 'CURR:DC'):
            return
        self._on_mixed_dmm_function_changed(function_code)

    def get_mm_mode(self) -> str:
        return self._dmm_mm_mode

    def get_mm_function(self) -> str:
        return self._dmm_mm_function

    def get_mm_signal(self) -> str:
        return self._dmm_mm_signal

    def get_mixed_dmm_function(self) -> str:
        return self._dmm_mixed_function

    def _update_mm_signal_visibility(self):
        is_va_mode = self._dmm_mm_function in ('V', 'A')
        self.mm_signal_container.setVisible(is_va_mode)

    @staticmethod
    def _refresh_button_style(button: QPushButton):
        button.style().unpolish(button)
        button.style().polish(button)


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
        self.terminal.setMinimumHeight(90)
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
        self.settings = QSettings('DariuszPiskorowski', 'PyVISAInstrumentCaptureTool')
        self.scan_thread: Optional[ScanThread] = None
        self.capture_thread: Optional[CaptureThread] = None
        self.active_instrument_type: str = 'oscilloscope'
        self._mixed_selection_logged: bool = False
        self._loading_settings: bool = False
        self.setup_ui()
        self._load_ui_settings()
        self.load_stylesheet()
        
        # Auto-scan on startup
        QTimer.singleShot(500, self.scan_devices)

    def setup_ui(self):
        self.setWindowTitle("VISA Instrument Capture Tool")
        self.setMinimumSize(500, 700)
        self.resize(520, 720)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 10, 16, 14)
        main_layout.setSpacing(10)

        # Device panel
        self.device_panel = DevicePanel()
        self.device_panel.refresh_btn.clicked.connect(self.scan_devices)
        main_layout.addWidget(self.device_panel)

        # Control panel
        self.control_panel = ControlPanel()
        self.control_panel.capture_requested.connect(self.capture_screenshots)
        self.control_panel.settings_changed.connect(self._save_ui_settings)
        main_layout.addWidget(self.control_panel)

        # Terminal panel
        self.terminal_panel = TerminalPanel()
        main_layout.addWidget(self.terminal_panel, 1)

        # Footer
        footer = QLabel("PyVISA Multi-Instrument Control • v1.1")
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
        enabled_devices = self.device_panel.get_enabled_devices()
        enabled_count = len(enabled_devices)
        is_capturing = self.capture_thread is not None and self.capture_thread.isRunning()
        self._update_active_instrument_type(enabled_devices)
        self.control_panel.update_capture_button(enabled_count, is_capturing)

    def _update_active_instrument_type(self, enabled_devices: Optional[List[Device]] = None):
        if enabled_devices is None:
            enabled_devices = self.device_panel.get_enabled_devices()

        if not enabled_devices:
            self.active_instrument_type = 'none'
            self._mixed_selection_logged = False
            self.control_panel.set_selected_instrument_type(self.active_instrument_type)
            return

        contains_scope = any(device.instrument_type == 'oscilloscope' for device in enabled_devices)
        contains_dmm = any(device.instrument_type == 'dmm6500' for device in enabled_devices)

        if contains_scope and contains_dmm:
            self.active_instrument_type = 'mixed'
            self.control_panel.set_selected_instrument_type(self.active_instrument_type)
            if not self._mixed_selection_logged:
                self.terminal_panel.add_log(
                    'warning',
                    'Mixed selection detected. Oscilloscope uses scope settings. DMM6500 is AUTO range with selectable A AC/A DC.'
                )
                self._mixed_selection_logged = True
            return

        self._mixed_selection_logged = False

        if contains_dmm:
            self.active_instrument_type = 'dmm6500'
        else:
            self.active_instrument_type = 'oscilloscope'

        self.control_panel.set_selected_instrument_type(self.active_instrument_type)

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

        dmm_count = sum(1 for device in devices if device.instrument_type == 'dmm6500')
        scope_count = sum(1 for device in devices if device.instrument_type == 'oscilloscope')
        if scope_count:
            self.terminal_panel.add_log("info", f"Detected oscilloscopes: {scope_count}")
        if dmm_count:
            self.terminal_panel.add_log("info", f"Detected Keithley DMM6500: {dmm_count}")
        
        self._update_capture_button()

    def _on_scan_error(self, error: str):
        self.device_panel.set_scanning(False)
        self.terminal_panel.add_log("error", f"Scan failed: {error}")

    def capture_screenshots(self):
        enabled_devices = self.device_panel.get_enabled_devices()
        if not enabled_devices:
            return

        # Get oscilloscope settings
        mode = self.control_panel.get_mode()
        timebase = self.control_panel.get_timebase()
        timebase_text = self.control_panel.get_timebase_text()
        dmm_function = self.control_panel.get_dmm_measurement_function()
        dmm_range = self.control_panel.get_dmm_measurement_range()
        dmm_range_text = self.control_panel.get_dmm_measurement_range_text()
        dmm_apply_configuration = self.control_panel.get_dmm_apply_configuration()
        
        # Default save folder
        folder = os.path.join(os.path.expanduser("~"), "Pictures", "Oscilloscope")
        os.makedirs(folder, exist_ok=True)

        self.terminal_panel.add_log("info", f"Starting capture on {len(enabled_devices)} device(s)...")

        has_scope = any(device.instrument_type == 'oscilloscope' for device in enabled_devices)
        has_dmm = any(device.instrument_type == 'dmm6500' for device in enabled_devices)

        if has_scope and mode == 2 and timebase_text and timebase is None:
            self.terminal_panel.add_log("error", "Invalid custom time base. Use a positive numeric value (e.g. 0.001).")
            return

        if has_scope:
            if mode == 0:
                self.terminal_panel.add_log("info", "Oscilloscope mode: As It Is (no changes)")
            elif mode == 1:
                self.terminal_panel.add_log("info", "Oscilloscope mode: AutoScale enabled")
            else:
                tb = timebase if timebase else TIMEBASE_SECONDS_PER_DIVISION
                self.terminal_panel.add_log("info", f"Oscilloscope mode: Custom TimeBase ({tb} sec/div)")

        if has_dmm:
            if dmm_apply_configuration:
                unit = get_dmm6500_unit(dmm_function)
                range_text = 'AUTO' if dmm_range is None else f"{dmm_range}"
                self.terminal_panel.add_log(
                    "info",
                    f"DMM6500 mode: AUTO, function: {dmm_function} ({unit}), range: {range_text}"
                )
            else:
                self.terminal_panel.add_log("info", "DMM6500 mode: CUSTOM (As It Is on multimeter)")

        self._update_capture_button()

        self.capture_thread = CaptureThread(
            enabled_devices,
            folder,
            mode,
            timebase,
            dmm_measurement_function=dmm_function,
            dmm_measurement_range=dmm_range,
            dmm_apply_configuration=dmm_apply_configuration,
        )
        self.capture_thread.capture_started.connect(self._on_capture_started)
        self.capture_thread.capture_completed.connect(self._on_capture_completed)
        self.capture_thread.capture_failed.connect(self._on_capture_failed)
        self.capture_thread.all_completed.connect(self._on_all_captures_completed)
        self.capture_thread.start()

        self.control_panel.update_capture_button(len(enabled_devices), True)

    def _on_capture_started(self, device_id: str):
        self.terminal_panel.add_log("info", f"Capturing from {device_id}...")

    def _on_capture_completed(self, device_id: str, filepath: str):
        file_name = os.path.basename(filepath)
        if file_name.lower().endswith('.txt'):
            self.terminal_panel.add_log("success", f"Measurement saved: {file_name}")
        else:
            self.terminal_panel.add_log("success", f"Screenshot saved: {file_name}")

    def _on_capture_failed(self, device_id: str, error: str):
        self.terminal_panel.add_log("error", f"Failed {device_id}: {error}")

    def _on_all_captures_completed(self):
        self.terminal_panel.add_log("success", "All captures completed!")
        self._update_capture_button()

    def _load_ui_settings(self):
        self._loading_settings = True
        try:
            scope_mode_raw = self.settings.value('ui/scope_mode', 0)
            try:
                scope_mode = int(scope_mode_raw)
            except (TypeError, ValueError):
                scope_mode = 0
            self.control_panel.set_scope_mode(scope_mode)

            timebase_text = str(self.settings.value('ui/timebase_text', '') or '')
            self.control_panel.set_timebase_text(timebase_text)

            mm_mode = str(self.settings.value('ui/mm_mode', 'auto') or 'auto')
            self.control_panel.set_mm_mode(mm_mode)

            mm_function = str(self.settings.value('ui/mm_function', 'V') or 'V')
            self.control_panel.set_mm_function(mm_function)

            mm_signal = str(self.settings.value('ui/mm_signal', 'DC') or 'DC')
            self.control_panel.set_mm_signal(mm_signal)

            mixed_dmm_function = str(self.settings.value('ui/mixed_dmm_function', 'CURR:DC') or 'CURR:DC')
            self.control_panel.set_mixed_dmm_function(mixed_dmm_function)
        finally:
            self._loading_settings = False

    def _save_ui_settings(self):
        if self._loading_settings:
            return
        self.settings.setValue('ui/scope_mode', self.control_panel.get_mode())
        self.settings.setValue('ui/timebase_text', self.control_panel.get_timebase_text())
        self.settings.setValue('ui/mm_mode', self.control_panel.get_mm_mode())
        self.settings.setValue('ui/mm_function', self.control_panel.get_mm_function())
        self.settings.setValue('ui/mm_signal', self.control_panel.get_mm_signal())
        self.settings.setValue('ui/mixed_dmm_function', self.control_panel.get_mixed_dmm_function())


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
