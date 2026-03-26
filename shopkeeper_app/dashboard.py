"""
Dashboard UI for shopkeeper application
"""
import logging
logger = logging.getLogger(__name__)
import sys
import os
import win32print
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QPushButton, QTableWidget, 
                           QTableWidgetItem, QHeaderView, QMessageBox, 
                           QTabWidget, QGroupBox, QComboBox, QLineEdit,
                           QTextEdit, QProgressBar, QSplitter, QFrame, QFileDialog, 
                           QListWidget, QListWidgetItem, QCheckBox, QDialog, QScrollArea, QListView,
                           QToolButton, QMenu, QAction, QDateEdit, QDialogButtonBox, QGraphicsDropShadowEffect,
                           QStyledItemDelegate, QFormLayout, QSizePolicy, QToolTip, QRadioButton)
try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    WEBENGINE_AVAILABLE = False
    logger.warning("QWebEngineWidgets not available. Charts will use fallback rendering.")
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QPoint, QMetaObject, Qt, QSize, QRect
from PyQt5.QtGui import QPixmap, QFont, QIcon, QKeySequence, QPainter, QColor, QPaintEvent, QPen, QBrush
from PyQt5.QtWidgets import QStyle, QGraphicsDropShadowEffect
import weakref
import sip
from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QShortcut
from urllib.parse import unquote
import re
from datetime import datetime, timedelta, timezone
import json

import logging

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shopkeeper_app.auth import AuthManager
from shopkeeper_app.printer_manager import PrinterManager
from shopkeeper_app.api_client import ApiClient
from shared.file_processor import generate_nup_pdf
from shared.database import PrintJob, ShopPricing, SessionLocal
from sqlalchemy import func
from shared.config import LOG_FILE, EZPRINT_BASE_URL
from shared.global_error_handler import (
    global_error_handler, safe_execute, safe_ui_action, 
    safe_printer_action, safe_database_action, safe_thread_action
)
from shared.thread_safe_socketio_client import ThreadSafeSocketIOManager, SocketIOMessage

logger = logging.getLogger(__name__)


# Standardized Toggle Styles (UI-Only)
TOGGLE_STYLE = """
    QCheckBox::indicator {
        width: 44px;
        height: 24px;
        border-radius: 12px;
        border: none;
    }
    QCheckBox::indicator:unchecked {
        background-color: #e5e7eb;
    }
    QCheckBox::indicator:checked {
        background-color: #3b82f6;
    }
    QCheckBox:disabled {
        opacity: 0.5;
    }
"""

KNOB_STYLE = "background-color: white; border-radius: 10px;"


class ChartJSGraph(QWidget):
    """Modern Chart.js-based line graph widget using QWebEngineView for professional SaaS-quality charts"""
    def __init__(self, chart_type='line', parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setMaximumHeight(180)
        self.chart_type = chart_type
        self.values = []
        self.labels = []
        self.max_value = 1
        self.chart_id = f"chart_{id(self)}"
        
        if WEBENGINE_AVAILABLE:
            self.web_view = QWebEngineView(self)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.web_view)
            self._render_empty_chart()
        else:
            # Fallback: use SimpleLineGraph if WebEngine not available
            self.fallback_graph = SimpleLineGraph(self)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.fallback_graph)
    
    def set_data(self, values, labels=None, max_value=None):
        """Set graph data - values list and optional labels (same interface as SimpleLineGraph)"""
        self.values = values if values else []
        self.labels = labels if labels else []
        
        if max_value is None:
            self.max_value = max(values) if values else 1
        else:
            self.max_value = max_value if max_value > 0 else 1
        
        if self.max_value == 0:
            self.max_value = 1
        
        if WEBENGINE_AVAILABLE:
            self._render_chart()
        else:
            # Fallback to old implementation
            if hasattr(self, 'fallback_graph'):
                self.fallback_graph.set_data(values, labels, max_value)
    
    def _render_empty_chart(self):
        """Render empty chart placeholder"""
        html = self._get_chart_html([], [], 1)
        self.web_view.setHtml(html)
    
    def _render_chart(self):
        """Render chart with current data"""
        html = self._get_chart_html(self.values, self.labels, self.max_value)
        self.web_view.setHtml(html)
    
    def _get_chart_html(self, values, labels, max_value):
        """Generate HTML with Chart.js for rendering"""
        # Format labels
        display_labels = []
        for i, label in enumerate(labels if labels else []):
            if label and label.strip():
                display_labels.append(label)
            else:
                display_labels.append("")
        
        # Ensure labels match values length
        while len(display_labels) < len(values):
            display_labels.append("")
        display_labels = display_labels[:len(values)]
        
        # Format values for display
        formatted_values = []
        is_revenue = self.chart_type == 'revenue'
        for val in values:
            if is_revenue:
                formatted_values.append(float(val) if val else 0.0)
            else:
                formatted_values.append(int(val) if val else 0)
        
        values_json = json.dumps(formatted_values)
        labels_json = json.dumps(display_labels)
        max_val_json = json.dumps(float(max_value))
        
        y_axis_label = "Revenue (₹)" if is_revenue else "Print Jobs"
        tooltip_prefix = "₹ " if is_revenue else ""
        
        # Check if all values are zero
        is_empty = all(v == 0 for v in formatted_values) if formatted_values else True
        is_empty_json = "true" if is_empty else "false"

        html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {{
            box-sizing: border-box;
            -webkit-font-smoothing: antialiased;
        }}
        html, body {{
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
            background-color: transparent;
            overflow: hidden;
        }}
        .chart-container {{
            position: relative;
            width: 100%;
            height: 100%;
            padding: 10px;
        }}
        .empty-state {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: #9ca3af;
            font-size: 14px;
            font-weight: 500;
            display: { 'flex' if is_empty else 'none' };
            flex-direction: column;
            align-items: center;
            pointer-events: none;
            z-index: 10;
        }}
        canvas {{
            display: block;
            width: 100% !important;
            height: 100% !important;
        }}
    </style>
</head>
<body>
    <div class="chart-container">
        <div class="empty-state">
            <span>No revenue recorded yet</span>
        </div>
        <canvas id="{self.chart_id}"></canvas>
    </div>
    <script>
        const ctx = document.getElementById('{self.chart_id}').getContext('2d');
        
        const maxValue = Math.max(...{values_json});
        const providedMax = {max_val_json};
        // Match the reference image scale (0, 600, 1200, 1800, 2400)
        // If data exceeds 2400, we scale up, but keep 2400 as a logical benchmark
        const yAxisMax = providedMax > 0 ? (providedMax) : (maxValue <= 2400 ? 2400 : Math.ceil(maxValue / 600) * 600);
        
        const chart = new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: {labels_json},
                datasets: [{{
                    label: '{y_axis_label}',
                    data: {values_json},
                    borderColor: '#3b82f6',
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    tension: 0.4,
                    pointRadius: 5,
                    pointHoverRadius: 7,
                    pointBackgroundColor: '#3b82f6',
                    pointBorderColor: '#3b82f6',
                    pointBorderWidth: 1,
                    fill: false,
                    capBezierPoints: true
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                layout: {{
                    padding: {{ left: 10, right: 30, top: 40, bottom: 20 }}
                }},
                plugins: {{
                    legend: {{ display: false }},
                    tooltip: {{
                        enabled: !{is_empty_json},
                        backgroundColor: '#ffffff',
                        titleColor: '#6b7280',
                        bodyColor: '#111827',
                        borderColor: '#f3f4f6',
                        borderWidth: 1,
                        padding: 12,
                        cornerRadius: 8,
                        displayColors: false,
                        titleFont: {{ size: 12, weight: '500' }},
                        bodyFont: {{ size: 14, weight: 'bold' }},
                        callbacks: {{
                            label: (ctx) => '{tooltip_prefix}' + ctx.parsed.y.toLocaleString()
                        }}
                    }}
                }},
                scales: {{
                    x: {{
                        grid: {{ display: false }},
                        ticks: {{
                            color: '#9ca3af',
                            font: {{ size: 12 }},
                            maxRotation: 0,
                            autoSkip: false,
                            padding: 15
                        }},
                        border: {{ 
                            display: true,
                            color: '#e5e7eb',
                            width: 1
                        }}
                    }},
                    y: {{
                        beginAtZero: true,
                        max: yAxisMax,
                        min: 0,
                        grid: {{
                            color: '#e5e7eb',
                            drawBorder: false,
                            borderDash: [3, 3],
                            lineWidth: 1
                        }},
                        ticks: {{
                            color: '#9ca3af',
                            font: {{ size: 12 }},
                            stepSize: 600,
                            padding: 15,
                            callback: (val) => val.toLocaleString()
                        }},
                        border: {{ display: false }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
        return html_template


class SimpleLineGraph(QWidget):
    """Lightweight line graph widget using Qt-native painting - Fallback when WebEngine unavailable"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setMaximumHeight(180)
        self.data_points = []  # List of (x, y) tuples normalized to 0-1
        self.labels = []  # X-axis labels
        self.values = []  # Original values for tooltip display
        self.max_value = 1  # For scaling
        self.line_color = QColor(59, 130, 246)  # Blue accent color
        self.hovered_index = None  # Track which point is hovered
        self.setMouseTracking(True)  # Enable mouse tracking for tooltips
        
    def set_data(self, values, labels=None, max_value=None):
        """Set graph data - values list and optional labels"""
        if not values:
            self.data_points = []
            self.labels = []
            self.values = []
            self.max_value = 1
            self.update()
            return
        
        # Normalize values to 0-1 range
        if max_value is None:
            self.max_value = max(values) if values else 1
        else:
            self.max_value = max_value if max_value > 0 else 1
        
        if self.max_value == 0:
            self.max_value = 1
        
        self.values = values  # Store original values
        self.data_points = []
        for i, val in enumerate(values):
            x = i / (len(values) - 1) if len(values) > 1 else 0.5
            y = 1.0 - (val / self.max_value)  # Invert Y (0 at top)
            self.data_points.append((x, y))
        
        self.labels = labels if labels else []
        self.update()
    
    def mouseMoveEvent(self, event):
        """Handle mouse move to show tooltip"""
        if not self.data_points:
            return
        
        rect = self.rect()
        margin = 30
        chart_rect = QRect(margin, 10, rect.width() - margin - 10, rect.height() - 30)
        
        # Find closest data point
        mouse_x = event.pos().x()
        closest_index = None
        min_distance = float('inf')
        
        for i, (x_norm, y_norm) in enumerate(self.data_points):
            x = chart_rect.left() + (x_norm * chart_rect.width())
            distance = abs(mouse_x - x)
            if distance < min_distance and distance < 30:  # 30px threshold
                min_distance = distance
                closest_index = i
        
        if closest_index is not None and closest_index != self.hovered_index:
            self.hovered_index = closest_index
            self.update()
            
            # Show tooltip
            if closest_index < len(self.values):
                date_label = self.labels[closest_index] if (self.labels and closest_index < len(self.labels) and self.labels[closest_index]) else f"Point {closest_index + 1}"
                value = self.values[closest_index]
                # Format value appropriately (integers show as int, floats show 2 decimals)
                if isinstance(value, float):
                    value_str = f"{value:.2f}"
                elif isinstance(value, int):
                    value_str = str(value)
                else:
                    value_str = str(value)
                tooltip_text = f"{date_label}\nValue: {value_str}"
                QToolTip.showText(event.globalPos(), tooltip_text, self)
        elif closest_index is None and self.hovered_index is not None:
            self.hovered_index = None
            self.update()
            QToolTip.hideText()
    
    def leaveEvent(self, event):
        """Hide tooltip when mouse leaves"""
        self.hovered_index = None
        self.update()
        QToolTip.hideText()
    
    def paintEvent(self, event):
        """Paint the line graph"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Get drawing area
        rect = self.rect()
        margin = 30
        chart_rect = QRect(margin, 10, rect.width() - margin - 10, rect.height() - 30)
        
        if not self.data_points:
            # Empty state
            painter.setPen(QPen(QColor(156, 163, 175), 1, Qt.DashLine))
            painter.drawText(chart_rect, Qt.AlignCenter, "No data available")
            return
        
        # Draw grid lines (light grey dashed)
        grid_pen = QPen(QColor(229, 231, 235), 1, Qt.DashLine)
        painter.setPen(grid_pen)
        
        # Horizontal grid lines
        for i in range(5):
            y = chart_rect.top() + (chart_rect.height() * i / 4)
            painter.drawLine(chart_rect.left(), int(y), chart_rect.right(), int(y))
        
        # Vertical grid lines (fewer)
        if len(self.data_points) > 1:
            for i in range(min(7, len(self.data_points))):
                x = chart_rect.left() + (chart_rect.width() * i / (len(self.data_points) - 1))
                painter.drawLine(int(x), chart_rect.top(), int(x), chart_rect.bottom())
        
        # Draw line and points
        if len(self.data_points) > 1:
            # Draw line
            line_pen = QPen(self.line_color, 2)
            painter.setPen(line_pen)
            
            points = []
            for x_norm, y_norm in self.data_points:
                x = chart_rect.left() + (x_norm * chart_rect.width())
                y = chart_rect.top() + (y_norm * chart_rect.height())
                points.append(QPointF(x, y))
            
            # Draw smooth polyline
            for i in range(len(points) - 1):
                painter.drawLine(points[i], points[i + 1])
            
            # Draw data point circles
            point_brush = QBrush(self.line_color)
            painter.setBrush(point_brush)
            painter.setPen(QPen(self.line_color, 2))
            for i, point in enumerate(points):
                # Highlight hovered point
                if self.hovered_index == i:
                    # Draw larger circle for hovered point
                    hover_brush = QBrush(QColor(self.line_color.red(), self.line_color.green(), self.line_color.blue(), 200))
                    painter.setBrush(hover_brush)
                    painter.drawEllipse(point, 6, 6)
                    painter.setBrush(point_brush)
                else:
                    painter.drawEllipse(point, 4, 4)
        
        # Draw Y-axis labels (values)
        value_pen = QPen(QColor(107, 114, 128))
        painter.setPen(value_pen)
        painter.setFont(QFont("Segoe UI", 9))
        for i in range(5):
            value = self.max_value * (1 - i / 4)
            label_text = f"{int(value)}" if value >= 1 else f"{value:.1f}"
            y = chart_rect.top() + (chart_rect.height() * i / 4)
            painter.drawText(QRect(0, int(y) - 8, margin - 5, 16), Qt.AlignRight | Qt.AlignVCenter, label_text)
        
        # Draw X-axis labels (dates)
        if self.labels and len(self.labels) == len(self.data_points):
            painter.setFont(QFont("Segoe UI", 8))
            for i, label in enumerate(self.labels):
                if i < len(self.data_points):
                    x_norm = self.data_points[i][0]
                    x = chart_rect.left() + (x_norm * chart_rect.width())
                    painter.drawText(QRect(int(x) - 25, chart_rect.bottom() + 2, 50, 20), 
                                   Qt.AlignCenter, label)


def get_icon(icon_name, size=16):
    """Get Qt standard icon by name - production-safe icon helper with modern vector-style icons"""
    icon_map = {
        'home': QStyle.SP_DirHomeIcon,
        'file': QStyle.SP_FileIcon,
        'settings': QStyle.SP_FileDialogDetailedView,
        'printer': QStyle.SP_ComputerIcon,  # Using computer icon as printer alternative
        'connect': QStyle.SP_DriveNetIcon,
        'refresh': QStyle.SP_BrowserReload,
        'save': QStyle.SP_DialogSaveButton,
        'cancel': QStyle.SP_DialogCancelButton,
        'edit': QStyle.SP_FileDialogDetailedView,
        'profile': QStyle.SP_FileDialogInfoView,
        'inventory': QStyle.SP_DirIcon,
        'payments': QStyle.SP_FileDialogListView,
        'qr': QStyle.SP_FileDialogInfoView,
        'pricing': QStyle.SP_FileDialogDetailedView,
        'dashboard': QStyle.SP_DirHomeIcon,  # Home icon for dashboard
        'print_jobs': QStyle.SP_FileDialogListView,  # List icon for print jobs
        'shop_qr': QStyle.SP_FileDialogInfoView,  # Info icon for QR
    }
    
    standard_pixmap = icon_map.get(icon_name.lower(), QStyle.SP_FileIcon)
    app = QApplication.instance()
    if app:
        icon = app.style().standardIcon(standard_pixmap)
        # Return icon with proper size
        if size != 16:
            pixmap = icon.pixmap(size, size)
            return QIcon(pixmap)
        return icon
    return QIcon()


def get_profile_icon(size=20):
    """Get profile icon - can be replaced with user-provided image if available"""
    # Check for user-provided profile icon image
    # Common locations to check:
    profile_icon_paths = [
        os.path.join(os.path.dirname(__file__), "profile_icon.png"),
        os.path.join(os.path.dirname(__file__), "profile_icon.jpg"),
        os.path.join(os.path.dirname(__file__), "assets", "profile_icon.png"),
        os.path.join(os.path.dirname(__file__), "assets", "profile_icon.jpg"),
    ]
    
    for path in profile_icon_paths:
        if os.path.exists(path):
            try:
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    # Scale to desired size and make circular if needed
                    scaled_pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    return QIcon(scaled_pixmap)
            except Exception as e:
                logger.warning(f"Could not load profile icon from {path}: {e}")
    
    # Fallback to default icon
    return get_icon("profile", size)


def get_status_icon(status_type):
    """Get colored dot icon for status indicators"""
    # Create a simple colored circle pixmap
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    
    color_map = {
        'connected': QColor('#10b981'),  # Green
        'disconnected': QColor('#ef4444'),  # Red
        'warning': QColor('#f59e0b'),  # Amber
        'info': QColor('#3b82f6'),  # Blue
    }
    
    color = color_map.get(status_type.lower(), QColor('#6b7280'))
    painter.setBrush(color)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(2, 2, 8, 8)
    painter.end()
    
    return QIcon(pixmap)


class ElidedItemDelegate(QStyledItemDelegate):
    """Custom delegate for text eliding in table cells"""
    def paint(self, painter, option, index):
        text = index.data(Qt.DisplayRole)
        if text:
            # Add a subtle inter-column gap between File Name (col 2) and Time (col 3)
            rect = option.rect
            if index.column() == 2:
                # Reduce drawing width to leave extra right padding
                rect = rect.adjusted(0, 0, -10, 0)
            elif index.column() == 3:
                # Add extra left padding for Time to increase distance from File Name
                rect = rect.adjusted(8, 0, 0, 0)
            elided = option.fontMetrics.elidedText(text, Qt.ElideRight, rect.width())
            painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, elided)
        else:
            super().paint(painter, option, index)


class ConnectPrintersDialog(QDialog):
    """Modern popup dialog for connecting printers with card-like UI"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_dashboard = parent
        self.printer_cards = {}
        self.connect_buttons = {}  # Store references to Connect buttons for dynamic updates
        self.status_labels = {}    # Store references to status labels for dynamic updates
        self.init_ui()
        self.load_printers()
        self.setup_timer()
    
    def init_ui(self):
        self.setWindowTitle("Connect Printers")
        self.setModal(True)
        self.setFixedSize(700, 600)
        # Remove help button (?) from dialog title bar
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Header
        header_layout = QHBoxLayout()
        title_label = QLabel("Connect Printers")
        title_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title_label.setStyleSheet("color: #1f2937; margin-bottom: 10px; font-family: 'Segoe UI', sans-serif;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # Refresh button - text only, no icon
        refresh_btn = QPushButton("Refresh")
        # No icon - clean text-only button
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #374151;
                border: 1px solid #d1d5db;
                padding: 8px 16px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #f9fafb;
                border-color: #9ca3af;
            }
            QPushButton:pressed {
                background-color: #f3f4f6;
            }
        """)
        refresh_btn.clicked.connect(self.refresh_printers)
        header_layout.addWidget(refresh_btn)
        
        # Debug button removed for production
        
        layout.addLayout(header_layout)
        
        # Status info
        self.status_label = QLabel("Scanning for available printers...")
        self.status_label.setStyleSheet("color: #6b7280; font-size: 13px; margin-bottom: 10px; font-family: 'Segoe UI', sans-serif;")
        layout.addWidget(self.status_label)
        
        # Scroll area for printer cards
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #f1f5f9;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #cbd5e1;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #94a3b8;
            }
        """)
        
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(12)
        
        scroll_area.setWidget(self.scroll_widget)
        layout.addWidget(scroll_area)
        
        # Footer buttons
        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                border: none;
                padding: 10px 24px;
                border-radius: 8px;
                font-weight: 500;
                font-size: 14px;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        close_btn.clicked.connect(self.accept)
    
    def setup_timer(self):
        """Setup timer for real-time updates with enhanced WiFi detection"""
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_printer_status)
        self.timer.start(3000)  # Update every 3 seconds
        
        # Additional timer for connection icon updates
        self.icon_timer = QTimer()
        self.icon_timer.timeout.connect(self.update_connection_icons)
        self.icon_timer.start(5000)  # Update connection icons every 5 seconds
    
    def load_printers(self):
        """Load and display available printers"""
        try:
            # Clear existing cards
            for card in self.printer_cards.values():
                card.setParent(None)
            self.printer_cards.clear()
            self.connect_buttons.clear()  # Clear button references
            self.status_labels.clear()    # Clear status label references
            
            # Clear scroll layout
            for i in reversed(range(self.scroll_layout.count())):
                child = self.scroll_layout.itemAt(i).widget()
                if child:
                    child.setParent(None)
            
            # Check if parent dashboard and printer manager exist
            if not self.parent_dashboard or not hasattr(self.parent_dashboard, 'printer_manager'):
                self.status_label.setText("Error: Printer manager not available")
                logger.error("Parent dashboard or printer manager not available")
                return
            
            # Get available printers with error handling
            try:
                available_printers = self.parent_dashboard.printer_manager.get_available_printers()
                logger.info(f"Successfully retrieved {len(available_printers)} printers")
            except Exception as e:
                logger.error(f"Error getting available printers: {e}")
                self.status_label.setText(f"Error detecting printers: {str(e)}")
                return
            
            # Get active printers with error handling
            try:
                active_printers = set(self.parent_dashboard.printer_manager.get_active_printers(
                    self.parent_dashboard.shopkeeper_data['shop_id']
                ))
            except Exception as e:
                logger.error(f"Error getting active printers: {e}")
                active_printers = set()
            
            # Get default printer with error handling
            try:
                default_printer = self.parent_dashboard.printer_manager.get_default_printer(
                    self.parent_dashboard.shopkeeper_data['shop_id']
                )
            except Exception as e:
                logger.error(f"Error getting default printer: {e}")
                default_printer = None
            
            if not available_printers:
                # No printers found
                no_printers_label = QLabel("No printers detected")
                no_printers_label.setStyleSheet("""
                    QLabel {
                        color: #6b7280;
                        font-size: 14px;
                        padding: 40px;
                        text-align: center;
                    }
                """)
                no_printers_label.setAlignment(Qt.AlignCenter)
                self.scroll_layout.addWidget(no_printers_label)
                self.status_label.setText("No printers detected on this system")
                return
            
            # Create printer cards
            for printer_info in available_printers:
                card = self.create_printer_card(printer_info, active_printers, default_printer)
                self.scroll_layout.addWidget(card)
                self.printer_cards[printer_info['name']] = card
            
            # Add stretch to push cards to top
            self.scroll_layout.addStretch()
            
            # Update status
            connected_count = len(active_printers)
            self.status_label.setText(f"Found {len(available_printers)} printer(s) • {connected_count} connected")
            
        except Exception as e:
            logger.error(f"Error loading printers: {e}")
            self.status_label.setText("Error loading printers")
    
    def refresh_printers(self):
        """Refresh printer discovery to find WiFi printers"""
        try:
            self.status_label.setText("Scanning for printers (including WiFi)...")
            # Use the enhanced printer discovery with debug logging
            self.parent_dashboard.printer_manager.refresh_printer_discovery()
            # Reload the printer list
            self.load_printers()
        except Exception as e:
            logger.error(f"Error refreshing printers: {e}")
            self.status_label.setText("Error refreshing printers")
    
    # Debug method removed for production
    
    def update_connection_icons(self):
        """Update connection icons for all printer cards based on current connection type"""
        try:
            for printer_name, card in self.printer_cards.items():
                # Get comprehensive connection info
                conn_info = self.parent_dashboard.printer_manager.get_printer_connection_info(printer_name)
                current_connection_type = conn_info['connection_type']
                is_dual_connection = conn_info['is_dual_connection']
                
                # Update icon (using consistent printer emoji)
                icon_label = card.findChild(QLabel, f"icon_{printer_name}")
                if icon_label:
                    # Use consistent printer emoji for all printers
                    icon_label.setText("🖨️")
                
                # Update connection type text with dual-connection indicator
                conn_label = card.findChild(QLabel, f"conn_type_{printer_name}")
                if conn_label:
                    if is_dual_connection:
                        conn_text = f"• {current_connection_type} (Dual USB/WiFi)"
                    else:
                        conn_text = f"• {current_connection_type}"
                    conn_label.setText(conn_text)
                    
        except Exception as e:
            logger.error(f"Error updating connection icons: {e}")
    
    def create_printer_card(self, printer_info, active_printers, default_printer):
        """Create a modern printer card"""
        card = QFrame()
        card.setFrameStyle(QFrame.StyledPanel)
        
        printer_name = printer_info['name']  # Original spooler name for API/DB calls
        printer_display_name = printer_info.get('display_name', printer_name)  # Friendly name for UI
        is_connected = printer_name in active_printers
        is_default = printer_name == default_printer
        status = printer_info.get('status', 'Unknown')
        connection_type = printer_info.get('connection_type', 'Unknown')
        
        # Card styling - matches Settings page cards (border-radius: 8px, padding: 20px)
        if is_connected:
            if is_default:
                card.setStyleSheet("""
                    QFrame {
                        background-color: #ffffff;
                        border: 2px solid #2563EB;
                        border-radius: 8px;
                        padding: 20px;
                    }
                """)
            else:
                card.setStyleSheet("""
                    QFrame {
                        background-color: #ffffff;
                        border: 1px solid #e5e7eb;
                        border-radius: 8px;
                        padding: 20px;
                    }
                """)
        else:
            card.setStyleSheet("""
                QFrame {
                    background-color: #ffffff;
                    border: 1px solid #e5e7eb;
                    border-radius: 8px;
                    padding: 20px;
                }
            """)
        
        # Main layout - horizontal row layout
        main_layout = QHBoxLayout(card)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)
        
        # Left side content (icon + name + status)
        left_content = QHBoxLayout()
        left_content.setSpacing(12)
        
        # Connection icon with dynamic updates (printer emoji)
        icon_label = QLabel("🖨️")
        icon_label.setStyleSheet("font-size: 20px;")
        icon_label.setObjectName(f"icon_{printer_name}")  # For dynamic updates
        left_content.addWidget(icon_label)
        
        # Printer info (name + status)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        
        # Printer name
        name_label = QLabel(printer_display_name)
        name_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        name_label.setStyleSheet("color: #111827;")
        info_layout.addWidget(name_label)
        
        # Status and connection info
        status_layout = QHBoxLayout()
        status_layout.setSpacing(8)
        
        # Status indicator
        status_color = "#10b981" if status == "Online" else "#ef4444"
        status_dot = QLabel("●")
        status_dot.setStyleSheet(f"color: {status_color}; font-size: 12px;")
        status_dot.setObjectName(f"status_dot_{printer_name}")  # For dynamic updates
        status_layout.addWidget(status_dot)
        
        status_text = QLabel(status)
        status_text.setStyleSheet(f"color: {status_color}; font-size: 11px; font-weight: 500;")
        status_text.setObjectName(f"status_text_{printer_name}")  # For dynamic updates
        status_layout.addWidget(status_text)
        
        # Store status label reference for dynamic updates
        self.status_labels[printer_name] = {
            'dot': status_dot,
            'text': status_text
        }
        
        # Connection type with enhanced info for WiFi printers and dynamic updates
        if connection_type == 'WiFi/Ethernet':
            # Show additional info for WiFi printers
            if 'ip_address' in printer_info:
                conn_text = QLabel(f"• {connection_type} ({printer_info['ip_address']})")
            elif 'discovery_method' in printer_info:
                conn_text = QLabel(f"• {connection_type} ({printer_info['discovery_method']})")
            else:
                conn_text = QLabel(f"• {connection_type}")
        else:
            conn_text = QLabel(f"• {connection_type}")
        
        conn_text.setStyleSheet("color: #6b7280; font-size: 11px;")
        conn_text.setObjectName(f"conn_type_{printer_name}")  # For dynamic updates
        status_layout.addWidget(conn_text)
        
        # Default indicator - visually neutral, same as other status badges
        if is_default:
            default_text = QLabel("• Default")
            default_text.setStyleSheet("color: #6b7280; font-size: 11px; font-weight: 500;")
            status_layout.addWidget(default_text)
        
        status_layout.addStretch()
        info_layout.addLayout(status_layout)
        
        left_content.addLayout(info_layout)
        left_content.addStretch()  # Push content to the left
        
        # Add left content to main layout
        main_layout.addLayout(left_content)
        
        # Right side - Action buttons (always right-aligned)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)  # 8px spacing between buttons
        
        # Common button dimensions and styling
        button_width = 85
        button_height = 28
        button_style = """
            QPushButton {
                min-width: 85px;
                max-width: 85px;
                min-height: 28px;
                max-height: 28px;
                padding: 4px 8px;
                border-radius: 5px;
                font-size: 9px;
                font-weight: 500;
                text-align: center;
            }
        """
        
        if is_connected:
            # Set as default button (only if not already default) - LEFT
            if not is_default:
                default_btn = QPushButton("Set as Default")
                default_btn.setStyleSheet(button_style + """
                    QPushButton {
                        background-color: #f8fafc;
                        color: #475569;
                        border: 1px solid #cbd5e1;
                    }
                    QPushButton:hover {
                        background-color: #e2e8f0;
                        border-color: #94a3b8;
                    }
                """)
                default_btn.clicked.connect(lambda: self.set_default_printer(printer_name))
                button_layout.addWidget(default_btn)
            
            # Disconnect button - RIGHT
            disconnect_btn = QPushButton("Disconnect")
            disconnect_btn.setStyleSheet(button_style + """
                QPushButton {
                    background-color: #3b82f6;
                    color: #ffffff;
                    border: 1px solid #2563eb;
                }
                QPushButton:hover {
                    background-color: #2563eb;
                    border-color: #1d4ed8;
                }
            """)
            disconnect_btn.clicked.connect(lambda: self.disconnect_printer(printer_name))
            button_layout.addWidget(disconnect_btn)
        else:
            # Connect button - RIGHT (when not connected)
            connect_btn = QPushButton("Connect")
            connect_btn.setStyleSheet(button_style + """
                QPushButton {
                    background-color: #3b82f6;
                    color: #ffffff;
                    border: 1px solid #2563eb;
                }
                QPushButton:hover {
                    background-color: #2563eb;
                    border-color: #1d4ed8;
                }
                QPushButton:disabled {
                    background-color: #9ca3af;
                    color: #ffffff;
                    border: 1px solid #6b7280;
                }
            """)
            # Correct Rule (STEP 4): SAFETY VALIDATION
            # Only enable Connect if printer exists in spooler and OpenPrinter succeeds
            spooler_valid = False
            try:
                # 1. Quick existence check in Spooler
                all_spooler = [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]
                if printer_name in all_spooler:
                    # 2. OpenPrinter success check
                    h = win32print.OpenPrinter(printer_name)
                    win32print.ClosePrinter(h)
                    spooler_valid = True
            except Exception:
                spooler_valid = False

            is_online = status == "Online"
            is_verified = printer_info.get('connection_verified', False)
            
            # Enable ONLY if online, verified reachable (if network), and spooler-valid
            connect_btn.setEnabled(is_online and is_verified and spooler_valid)
            connect_btn.setObjectName(f"connect_btn_{printer_name}")  # For dynamic updates
            
            if is_online and is_verified and spooler_valid:
                connect_btn.setText("Connect")
                connect_btn.setToolTip("Click to connect this printer")
            elif not spooler_valid:
                connect_btn.setText("Unavailable")
                connect_btn.setToolTip("Printer queue no longer exists or is inaccessible")
                connect_btn.setEnabled(False)
            elif is_online and not is_verified:
                connect_btn.setText("Pending")
                connect_btn.setToolTip("Verifying printer reachability...")
                connect_btn.setEnabled(False)
            else:
                connect_btn.setText("Offline")
                connect_btn.setToolTip("Printer is offline or unreachable")
                
            connect_btn.clicked.connect(lambda: self.connect_printer(printer_name))
            button_layout.addWidget(connect_btn)
            
            # Store Connect button reference for dynamic updates
            self.connect_buttons[printer_name] = connect_btn
        
        # Add button layout to main layout (right side)
        main_layout.addLayout(button_layout)
        
        return card
    
    def get_connection_icon(self, connection_type, status):
        """Get appropriate icon for connection type with enhanced WiFi detection"""
        # Return QIcon instead of emoji string
        if connection_type == 'USB':
            return get_icon('connect', 16)
        elif connection_type == 'Bluetooth':
            return get_icon('connect', 16)
        elif connection_type == 'WiFi/Ethernet':
            return get_icon('connect', 16)
        else:
            return get_icon('printer', 16)
    
    def connect_printer(self, printer_name):
        """Connect a printer"""
        try:
            success, message = self.parent_dashboard.printer_manager.activate_printer(
                self.parent_dashboard.shopkeeper_data['shop_id'], 
                printer_name, 
                make_default=False
            )
            
            if success:
                self.load_printers()  # Refresh the display
                self.parent_dashboard.load_job_printers()  # Refresh job printer combo
                # Show success message on Dashboard window (not in dialog)
                if self.parent_dashboard.isVisible():
                    self.parent_dashboard.show_success_toast(f"Printer {printer_name} Connected Successfully")
            else:
                QMessageBox.warning(self, "Connection Failed", message)
                
        except Exception as e:
            logger.error(f"Error connecting printer: {e}")
            QMessageBox.warning(self, "Error", f"Failed to connect: {str(e)}")
    
    def disconnect_printer(self, printer_name):
        """Disconnect a printer"""
        try:
            success, message = self.parent_dashboard.printer_manager.deactivate_printer(
                self.parent_dashboard.shopkeeper_data['shop_id'], 
                printer_name
            )
            
            if success:
                self.load_printers()  # Refresh the display
                self.parent_dashboard.load_job_printers()  # Refresh job printer combo
                self.show_success_message(f"Disconnected from {printer_name}")
            else:
                QMessageBox.warning(self, "Disconnection Failed", message)
                
        except Exception as e:
            logger.error(f"Error disconnecting printer: {e}")
            QMessageBox.warning(self, "Error", f"Failed to disconnect: {str(e)}")
    
    def set_default_printer(self, printer_name):
        """Set a printer as default"""
        try:
            success, message = self.parent_dashboard.printer_manager.set_default_printer(
                self.parent_dashboard.shopkeeper_data['shop_id'], 
                printer_name
            )
            
            if success:
                self.load_printers()  # Refresh the display
                self.parent_dashboard.load_job_printers()  # Refresh job printer combo
                self.show_success_message(f"{printer_name} is now the default printer")
            else:
                QMessageBox.warning(self, "Set Default Failed", message)
                
        except Exception as e:
            logger.error(f"Error setting default printer: {e}")
            QMessageBox.warning(self, "Error", f"Failed to set default: {str(e)}")
    
    def update_printer_status(self):
        """Update printer status in real-time with enhanced WiFi detection"""
        try:
            # Only update if dialog is visible
            if self.isVisible():
                # Get fresh printer status without reloading entire UI
                self.update_printer_status_efficiently()
        except Exception as e:
            logger.error(f"Error updating printer status: {e}")
    
    def update_printer_status_efficiently(self):
        """Efficiently update printer status without reloading entire UI"""
        try:
            # First, handle any new printers that might have been discovered
            self.handle_new_printers()
            
            # Get current printer status from printer manager
            available_printers = self.parent_dashboard.printer_manager.get_available_printers()

            # Also fetch printers currently connected via our software (active in DB)
            try:
                active_printers = set(
                    self.parent_dashboard.printer_manager.get_active_printers(
                        self.parent_dashboard.shopkeeper_data['shop_id']
                    )
                )
            except Exception:
                active_printers = set()

            # Create a lookup dictionary for quick status access
            printer_status_map = {}
            for printer in available_printers:
                name = printer.get('name')
                status = printer.get('status', 'Unknown')
                is_verified = printer.get('connection_verified', False)
                printer_status_map[name] = {
                    'status': status,
                    'is_verified': is_verified
                }
            
            # Fetch total spooler list once for validation (Step 4 efficiency)
            spooler_names = set()
            try:
                spooler_names = {p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)}
            except Exception:
                pass

            # Update each existing printer card's status and button state
            for printer_name, info in printer_status_map.items():
                self.update_single_printer_status(printer_name, info['status'], info['is_verified'], spooler_names)
                
        except Exception as e:
            logger.error(f"Error in efficient printer status update: {e}")
    
    def update_single_printer_status(self, printer_name, status, is_verified=False, spooler_list=None):
        """Update status for a single printer (thread-safe) (STEP 4)"""
        try:
            # Update status labels if they exist
            if printer_name in self.status_labels:
                status_labels = self.status_labels[printer_name]
                status_color = "#10b981" if status == "Online" else "#ef4444"
                
                # Update status dot color
                status_labels['dot'].setStyleSheet(f"color: {status_color}; font-size: 12px;")
                
                # Update status text
                status_labels['text'].setText(status)
                status_labels['text'].setStyleSheet(f"color: {status_color}; font-size: 11px; font-weight: 500;")
            
            # Update Connect button state if it exists
            if printer_name in self.connect_buttons:
                connect_btn = self.connect_buttons[printer_name]
                
                # Rule (STEP 4): Safety validation during update
                spooler_valid = False
                try:
                    # 1. Existence check
                    if spooler_list is not None:
                        exists = printer_name in spooler_list
                    else:
                        all_spooler = {p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)}
                        exists = printer_name in all_spooler
                    
                    if exists:
                        # 2. Open check
                        h = win32print.OpenPrinter(printer_name)
                        win32print.ClosePrinter(h)
                        spooler_valid = True
                except Exception:
                    spooler_valid = False

                # Update button enabled state (Production Rule - STEP 4)
                is_online = status == "Online"
                connect_btn.setEnabled(is_online and is_verified and spooler_valid)
                
                # Update button text and tooltip for better UX
                if is_online and is_verified and spooler_valid:
                    connect_btn.setText("Connect")
                    connect_btn.setToolTip("Click to connect this printer")
                elif not spooler_valid:
                    connect_btn.setText("Unavailable")
                    connect_btn.setToolTip("Printer queue no longer exists or is inaccessible")
                    connect_btn.setEnabled(False)
                elif is_online and not is_verified:
                    connect_btn.setText("Pending")
                    connect_btn.setToolTip("Verifying printer reachability...")
                    connect_btn.setEnabled(False)
                else:
                    connect_btn.setText("Offline")
                    connect_btn.setToolTip("Printer is offline or unreachable")
            
            # Update connection icon if it exists
            if printer_name in self.printer_cards:
                card = self.printer_cards[printer_name]
                icon_label = card.findChild(QLabel, f"icon_{printer_name}")
                if icon_label:
                    # Get connection type from printer info
                    try:
                        available_printers = self.parent_dashboard.printer_manager.get_available_printers()
                        printer_info = next((p for p in available_printers if p['name'] == printer_name), None)
                        if printer_info:
                            # Use consistent printer emoji for all printers
                            icon_label.setText("🖨️")
                    except Exception as e:
                        logger.debug(f"Error updating icon for {printer_name}: {e}")
                        
        except Exception as e:
            logger.error(f"Error updating single printer status for {printer_name}: {e}")
    
    def handle_new_printers(self):
        """Handle newly discovered printers during the session"""
        try:
            # Get current printer list
            available_printers = self.parent_dashboard.printer_manager.get_available_printers()
            current_printer_names = set(self.printer_cards.keys())
            new_printer_names = set(printer['name'] for printer in available_printers)
            
            # Find new printers that aren't in our current UI
            newly_discovered = new_printer_names - current_printer_names
            
            if newly_discovered:
                logger.info(f"Found {len(newly_discovered)} new printers: {newly_discovered}")
                
                # Get active printers and default printer for new cards
                try:
                    active_printers = set(self.parent_dashboard.printer_manager.get_active_printers(
                        self.parent_dashboard.shopkeeper_data['shop_id']
                    ))
                except Exception:
                    active_printers = set()
                
                try:
                    default_printer = self.parent_dashboard.printer_manager.get_default_printer(
                        self.parent_dashboard.shopkeeper_data['shop_id']
                    )
                except Exception:
                    default_printer = None
                
                # Create cards for new printers
                for printer_info in available_printers:
                    if printer_info['name'] in newly_discovered:
                        card = self.create_printer_card(printer_info, active_printers, default_printer)
                        # Insert new card before the stretch widget
                        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, card)
                        self.printer_cards[printer_info['name']] = card
                
                # Update status label
                connected_count = len(active_printers)
                self.status_label.setText(f"Found {len(available_printers)} printer(s) • {connected_count} connected")
                
        except Exception as e:
            logger.error(f"Error handling new printers: {e}")
    
    def show_success_message(self, message):
        """Show a temporary success message"""
        try:
            # Create a temporary label for toast
            toast = QLabel(message)
            toast.setStyleSheet("""
                QLabel {
                    background-color: #10b981;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 6px;
                    font-weight: 500;
                    font-size: 12px;
                }
            """)
            toast.setAlignment(Qt.AlignCenter)
            
            # Position the toast
            toast.move(self.width() - 250, 50)
            toast.show()
            
            # Auto-hide after 2 seconds
            try:
                self._safe_single_shot(2000, toast.close)
            except Exception:
                pass
            
        except Exception as e:
            logger.error(f"Error showing success message: {e}")
    
    def closeEvent(self, event):
        """Handle dialog close"""
        try:
            if hasattr(self, 'timer'):
                self.timer.stop()
            if hasattr(self, 'icon_timer'):
                self.icon_timer.stop()
            
            # Clean up references
            self.connect_buttons.clear()
            self.status_labels.clear()
            
            event.accept()
        except Exception as e:
            logger.error(f"Error closing dialog: {e}")
            event.accept()

class AddPrinterDialog(QDialog):
    """Modal dialog for adding printers"""
    def __init__(self, available_printers, parent=None):
        super().__init__(parent)
        self.available_printers = available_printers
        self.selected_printers = []
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Add Printers")
        self.setModal(True)
        self.setFixedSize(500, 400)
        
        layout = QVBoxLayout(self)
        
        # Header
        header_label = QLabel("Select printers to connect:")
        header_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        layout.addWidget(header_label)
        
        # Scroll area for printer list
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        self.printer_checkboxes = {}
        for printer in self.available_printers:
            printer_frame = QFrame()
            printer_frame.setFrameStyle(QFrame.StyledPanel)
            printer_frame.setStyleSheet("""
                QFrame {
                    background-color: #f5f5f5;
                    border: 1px solid #e0e0e0;
                    border-radius: 4px;
                    margin: 2px;
                }
            """)
            
            frame_layout = QHBoxLayout(printer_frame)
            
            # Checkbox
            checkbox = QCheckBox()
            checkbox.stateChanged.connect(lambda state, p=printer: self.toggle_printer(p, state == Qt.Checked))
            frame_layout.addWidget(checkbox)
            
            # Status indicator
            status_color = "#4CAF50" if printer.get('status') == "Online" else "#F44336"
            status_icon = "●" if printer.get('status') == "Online" else "●"
            status_label = QLabel(status_icon)
            status_label.setStyleSheet(f"color: {status_color}; font-size: 14px;")
            frame_layout.addWidget(status_label)
            
            # Printer info
            info_layout = QVBoxLayout()
            name_label = QLabel(printer['name'])
            name_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
            info_layout.addWidget(name_label)
            
            connection_label = QLabel(f"Connection: {printer.get('connection_type', 'Unknown')}")
            connection_label.setStyleSheet("color: #666; font-size: 9px;")
            info_layout.addWidget(connection_label)
            
            status_label = QLabel(f"Status: {printer.get('status', 'Unknown')}")
            status_label.setStyleSheet(f"color: {status_color}; font-size: 9px;")
            info_layout.addWidget(status_label)
            
            frame_layout.addLayout(info_layout)
            frame_layout.addStretch()
            
            scroll_layout.addWidget(printer_frame)
            self.printer_checkboxes[printer['name']] = checkbox
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        connect_btn = QPushButton("Connect Selected")
        connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        connect_btn.clicked.connect(self.accept)
        button_layout.addWidget(connect_btn)
        
        layout.addLayout(button_layout)
    
    def toggle_printer(self, printer, selected):
        if selected:
            self.selected_printers.append(printer)
        else:
            self.selected_printers = [p for p in self.selected_printers if p['name'] != printer['name']]

class PrintJobWorker(QThread):
    """Worker thread for handling print jobs"""
    job_completed = pyqtSignal(str, str)  # job_id, status
    job_failed = pyqtSignal(str, str)  # job_id, error_message
    
    def __init__(self, job_id, file_path, printer_manager):
        super().__init__()
        self.job_id = job_id
        self.file_path = file_path
        self.printer_manager = printer_manager
    
    @safe_thread_action("PRINT_JOB_WORKER")
    def run(self):
        success, message = self.printer_manager.print_document(self.file_path)
        if success:
            self.job_completed.emit(self.job_id, "Completed")
        else:
            self.job_failed.emit(self.job_id, message)


class DashboardKPIWorker(QThread):
    """Worker thread for fetching and calculating Dashboard KPIs and analytics OFF the UI thread"""
    kpi_data_ready = pyqtSignal(dict)
    
    def __init__(self, shop_id, session_token, selected_month_str):
        super().__init__()
        self.shop_id = shop_id
        self.session_token = session_token
        self.selected_month_str = selected_month_str
        
    def run(self):
        try:
            logger.info(f"DashboardKPIWorker: Starting background data loading for shop {self.shop_id}")
            
            # API Client call logic
            api_success = False
            all_jobs_objs = []
            kpis = {}
            
            # Use top-level ApiClient
            api_client_local = ApiClient(session_token=self.session_token)
            
            success, api_data, error = api_client_local.get_dashboard(self.shop_id)
            
            if success and api_data:
                logger.info("DashboardKPIWorker: Successfully fetched data from API")
                kpis_raw = api_data.get('kpis', {})
                jobs_list = api_data.get('jobs', [])
                
                # Map API KPIs to structured result
                kpis = {
                    'total': str(kpis_raw.get('total_jobs', 0)),
                    'today': f"₹ {kpis_raw.get('total_revenue', 0.0):.2f}",
                    'monthly': f"₹ {kpis_raw.get('total_revenue', 0.0):.2f}",
                    'pending': str(kpis_raw.get('pending_jobs', 0)),
                    'printing': str(kpis_raw.get('printing_jobs', 0)),
                    'completed': str(kpis_raw.get('completed_jobs', 0)),
                    'failed': str(kpis_raw.get('failed_jobs', 0))
                }
                
                # Convert API jobs to simple objects
                from types import SimpleNamespace
                for j in jobs_list:
                    created_at = None
                    if j.get('created_at'):
                        try:
                            # Parse ISO format (handling 'Z' or '+00:00')
                            iso_str = j['created_at'].replace('Z', '+00:00')
                            created_at = datetime.fromisoformat(iso_str)
                        except:
                            pass
                    
                    obj = SimpleNamespace(
                        job_id=j.get('job_id'),
                        filename=j.get('filename'),
                        file_path=j.get('file_path'),
                        status=j.get('status'),
                        amount=j.get('amount', 0.0),
                        created_at=created_at,
                        total_pages=j.get('total_pages'),
                        copies=j.get('copies', 1),
                        page_range=j.get('page_range'),
                        page_size=j.get('page_size'),
                        orientation=j.get('orientation'),
                        print_side=j.get('print_side'),
                        color_mode=j.get('color_mode'),
                        layout_pages=j.get('layout_pages', 1)
                    )
                    all_jobs_objs.append(obj)
                api_success = True
            
            # DB Fallback and Analytics logic
            from shared.database import SessionLocal, PrintJob
            import calendar
            
            db = SessionLocal()
            try:
                if not api_success:
                    logger.info("DashboardKPIWorker: Falling back to local database for KPIs")
                    # Fallback KPI calculation from local DB
                    all_jobs_db = db.query(PrintJob).filter(PrintJob.shop_id == self.shop_id).all()
                    all_jobs_objs = all_jobs_db # Use DB objects for recent jobs list
                    
                    total_jobs = len(all_jobs_objs)
                    pending_statuses = {"pending", "in queue", "processing", "printing started"}
                    printing_statuses = {"printing", "printing started"}
                    
                    pending_count = sum(1 for job in all_jobs_objs if (job.status or "").strip().lower() in pending_statuses)
                    printing_count = sum(1 for job in all_jobs_objs if (job.status or "").strip().lower() in printing_statuses)
                    completed_count = sum(1 for job in all_jobs_objs if (job.status or "").strip().lower() == "completed")
                    failed_count = sum(1 for job in all_jobs_objs if (job.status or "").strip().lower() == "failed")
                    
                    now = datetime.now()
                    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    
                    today_revenue = sum(job.amount or 0 for job in all_jobs_objs if job.created_at and job.created_at >= today_start)
                    monthly_revenue = sum(job.amount or 0 for job in all_jobs_objs if job.created_at and job.created_at >= month_start)
                    
                    kpis = {
                        'total': str(total_jobs),
                        'today': f"₹ {today_revenue:.2f}",
                        'monthly': f"₹ {monthly_revenue:.2f}",
                        'pending': str(pending_count),
                        'printing': str(printing_count),
                        'completed': str(completed_count),
                        'failed': str(failed_count)
                    }
                
                # Calculate Analytics data
                # If we have API data, we still use DB for chart to keep existing logic behavior 
                # (which was: update_dashboard_kpis calls update_revenue_analytics which queries DB)
                jobs_for_analytics = db.query(PrintJob).filter(PrintJob.shop_id == self.shop_id).all()
                completed_jobs = [j for j in jobs_for_analytics if (j.status or "").strip().lower() == "completed"]
                
                now = datetime.now()
                try:
                    selected_date = datetime.strptime(self.selected_month_str, "%B %Y")
                except:
                    selected_date = now
                
                days_in_month = calendar.monthrange(selected_date.year, selected_date.month)[1]
                daily_revenue = {d: 0.0 for d in range(1, days_in_month + 1)}
                
                for job in completed_jobs:
                    if job.created_at and job.created_at.year == selected_date.year and job.created_at.month == selected_date.month:
                        day = job.created_at.day
                        daily_revenue[day] += float(job.amount or 0.0)
                
                values = []
                labels = []
                month_abbr = selected_date.strftime("%b")
                for d in range(1, days_in_month + 1):
                    values.append(daily_revenue[d])
                    if d in [1, 5, 10, 15, 20, 25, 30]:
                        labels.append(f"{month_abbr} {d}")
                    else:
                        labels.append("")
                
                analytics_data = {
                    "values": values,
                    "labels": labels,
                    "selected_month_str": self.selected_month_str
                }
                
                # Emit result
                result = {
                    "recent_jobs": all_jobs_objs,
                    "kpis": kpis,
                    "analytics_data": analytics_data
                }
                self.kpi_data_ready.emit(result)
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"DashboardKPIWorker Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.kpi_data_ready.emit({"error": str(e)})

class JobPopupDialog(QDialog):
    """Simple, non-blocking popup notification for new print jobs"""
    def __init__(self, job, parent_dashboard):
        super().__init__(parent_dashboard)
        self.job = job
        self.dashboard = parent_dashboard
        
        # 2 Instance Variables for Routing Metadata (Objective 2)
        self.routed_printer_name = None
        self.routed_printer_display_name = None  # Friendly display name for UI
        self.routing_error_message = None
        self.printer_status = "Online"  # Track real-time status (Offline Warning Requirement)
        
        # Initial routing check to determine printer FOR THIS JOB (Objective 1)
        printer_manager = getattr(self.dashboard, 'printer_manager', None)
        if printer_manager:
            try:
                # FIX 3: POPUP UI MUST USE AUTHORIZED PRINTERS ONLY
                available_printers_raw = printer_manager.get_authorized_printers()
                available_printers = [p.get('name') for p in available_printers_raw if p.get('name')]
                
                # Capture per-job routing result (now strictly enforces authorization)
                self.routed_printer_name, self.routing_error_message = printer_manager.select_printer_for_job(self.job)
                
                # Fetch real-time status for the routed printer
                if self.routed_printer_name:
                    printer_info = next((p for p in available_printers_raw if p.get('name') == self.routed_printer_name), None)
                    if printer_info:
                        self.printer_status = printer_info.get('status', 'Online')
                        self.routed_printer_display_name = printer_info.get('display_name', self.routed_printer_name)
            except Exception as e:
                logger.warning(f"Initial routing check failed for Popup: {e}")
        
        self.init_ui()
        QTimer.singleShot(0, self.center_on_screen)
        # Initial visibility check for Cancel button
        self._update_cancel_visibility(self.job.status)
        
        # Bind to existing status update mechanism (dashboard's thread-safe signal)
        if hasattr(self.dashboard, 'thread_safe_signal'):
            self.dashboard.thread_safe_signal.connect(self.on_dashboard_signal)
            
        # Step 1: Lightweight status refresh timer (Real-time Offline Requirement)
        self._printer_status_timer = QTimer(self)
        self._printer_status_timer.timeout.connect(self._refresh_printer_status)
        self._printer_status_timer.start(2000) # 2 seconds
        
    def center_on_screen(self):
        screen = self.screen().availableGeometry()
        x = screen.x() + (screen.width() - self.width()) // 2
        y = screen.y() + (screen.height() - self.height()) // 2
        self.move(x, y)

    def init_ui(self):
        self.setWindowTitle("New Print Job")
        screen = self.screen().size()

        dialog_w = min(360, int(screen.width() * 0.30))
        dialog_h = min(560, int(screen.height() * 0.72))

        # Allow height to be driven by content — prevents child-widget bleed/overflow
        self.setMinimumWidth(dialog_w)
        self.setMaximumWidth(dialog_w)
        self.adjustSize()
        # Non-blocking (Modeless) overlay and remove help icon
        self.setWindowFlags((self.windowFlags() | Qt.WindowStaysOnTopHint) & ~Qt.WindowContextHelpButtonHint)
        
        # Modern styling
        self.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
                border-radius: 12px;
            }
            QLabel {
                font-family: 'Segoe UI', system-ui, sans-serif;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        # Constrain dialog width strictly but allow height to grow with content
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        
        # Divider is now at the top after removing header

        
        # Helper to handle missing fields safely
        def safe_text(val, fallback="N/A"):
            return str(val) if val is not None and str(val).strip() else fallback
            
        # Job Header Card (Hero Style)
        job_header_card = QFrame()
        job_header_card.setStyleSheet("""
            QFrame {
                background-color: #F8FAFC;
                border-radius: 12px;
                border: 1px solid #E2E8F0;
            }
        """)
        header_layout = QVBoxLayout(job_header_card)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(3)
        
        # 1. JOB ID Label
        job_id_title = QLabel("JOB ID")
        job_id_title.setAlignment(Qt.AlignCenter)
        job_id_title.setStyleSheet("""
            font-size: 11px;
            font-weight: bold;
            color: #64748B;
            letter-spacing: 1px;
            border: none;
        """)
        header_layout.addWidget(job_id_title)
        
        # 2. Actual Job ID
        job_id_display = safe_text(self.job.job_id)[:8]
        job_id_val_hero = QLabel(job_id_display)
        job_id_val_hero.setAlignment(Qt.AlignCenter)
        job_id_val_hero.setStyleSheet("color: #111827; font-size: 22px; font-weight: 800; border: none;")
        header_layout.addWidget(job_id_val_hero)

        # 3. File Name (Pill Style)
        file_val = QLabel(safe_text(self.job.filename))
        file_val.setWordWrap(True)
        file_val.setAlignment(Qt.AlignCenter)
        file_val.setStyleSheet("""
            background-color: #f1f5f9;
            color: #0f172a;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 6px 14px;
            font-size: 13px;
            font-weight: bold;
            margin-top: 4px;
            margin-bottom: 2px;
        """)
        header_layout.addWidget(file_val)
        
        # 4. Date & Time
        from datetime import timezone
        utc_time = self.job.created_at or datetime.utcnow()
        local_time = utc_time.replace(tzinfo=timezone.utc).astimezone(None)
        date_text = local_time.strftime("%d %b %Y, %I:%M %p")
        date_val = QLabel(date_text)
        date_val.setAlignment(Qt.AlignCenter)
        date_val.setStyleSheet("""
            font-size: 12px;
            color: #94a3b8;
            font-weight: bold;
            margin-bottom: 4px;
            border: none;
        """)
        header_layout.addWidget(date_val)

        # Add Card to Main Layout
        layout.addWidget(job_header_card)
        
        # Basic Info Details Grid (Clean Left-Right Layout)
        details_container = QVBoxLayout()
        details_container.setSpacing(4)  # Compact but readable row gap
        
        def add_detail_row(label_text, value_text):
            row_layout = QHBoxLayout()
            
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #64748b; font-size: 13px; font-weight: 500; border: none;")
            lbl.setAlignment(Qt.AlignLeft)
            
            val = QLabel(value_text)
            val.setStyleSheet("color: #0f172a; font-size: 13px; font-weight: 600; border: none;")
            val.setAlignment(Qt.AlignRight)
            
            row_layout.addWidget(lbl, 1)
            row_layout.addWidget(val, 1)
            details_container.addLayout(row_layout)

        # Color Mode
        add_detail_row("Color Mode", safe_text(getattr(self.job, 'color_mode', None), "-"))
        
        # Pages
        total_pages = getattr(self.job, 'total_pages', None)
        pages_display = str(total_pages) if total_pages is not None else "All"
        add_detail_row("Pages", pages_display)
        
        # Page Range
        page_range = safe_text(getattr(self.job, 'page_range', None), "All")
        add_detail_row("Page Range", page_range)
        
        # Copies
        add_detail_row("Copies", safe_text(getattr(self.job, 'copies', None), "1"))
        
        # Side
        add_detail_row("Side", safe_text(getattr(self.job, 'print_side', None), "-"))
        
        # Layout
        n_up = getattr(self.job, 'layout_pages', 1)
        if n_up is None: n_up = 1
        add_detail_row("Layout", f"{n_up} per sheet" if n_up > 1 else "1 per sheet")
        
        # Paper Size
        paper_val_text = safe_text(getattr(self.job, 'page_size', None))
        if paper_val_text == "N/A":
            paper_val_text = safe_text(getattr(self.job, 'paper_size', None), "A4")
        add_detail_row("Paper Size", paper_val_text)

        # Orientation
        add_detail_row("Orientation", safe_text(getattr(self.job, 'orientation', None), "Portrait"))

        layout.addLayout(details_container)
        
        # Divider Line After Settings
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #e5e7eb; border: none; margin-top: 10px; margin-bottom: 12px;")
        layout.addWidget(divider)
        
        # Total Amount (Left-Right Row Style)
        amount = self.job.amount if self.job.amount is not None else 0.0
        amount_container = QHBoxLayout()
        amount_container.setContentsMargins(0, 6, 0, 0) # Margin-top: 6px
        
        amount_label = QLabel("Total Amount :")
        amount_label.setStyleSheet("color: #64748b; font-size: 14px; font-weight: 600; border: none;")
        amount_label.setAlignment(Qt.AlignLeft)
        
        amount_val = QLabel(f"₹ {amount:.2f}")
        amount_val.setStyleSheet("color: #059669; font-size: 16px; font-weight: 800; border: none;")
        amount_val.setAlignment(Qt.AlignRight)
        
        amount_container.addWidget(amount_label, 1)
        amount_container.addWidget(amount_val, 1)
        layout.addLayout(amount_container)

        # Printer Name & Status Card Container
        info_card = QFrame()
        info_card.setStyleSheet("""
            QFrame {
                background-color: #F8FAFC;
                border-radius: 12px;
                border: 1px solid #E2E8F0;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        # Ensure styled background renders correctly and children cannot bleed outside frame
        info_card.setAttribute(Qt.WA_StyledBackground, True)
        info_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        info_card_layout = QVBoxLayout(info_card)
        info_card_layout.setContentsMargins(12, 12, 12, 12)
        info_card_layout.setSpacing(6)
        
        # Printer Name OR Routing Error Message (Objective 3 & 4)
        # Popup ONLY displays per-job routed printer (Requirement 6)
        self.printer_label = QLabel("")
        self.printer_label.setAlignment(Qt.AlignCenter)
        self.printer_label.setWordWrap(True)
        
        if self.routing_error_message:
            # Show error message in place of printer label (Objective 3)
            self.printer_label.setText(self.routing_error_message)
            self.printer_label.setStyleSheet("""
                color: #dc2626;
                font-size: 13px;
                font-weight: 600;
                padding: 4px;
                background-color: #fef2f2;
                border: 1px solid #fecaca;
                border-radius: 6px;
            """)
        else:
            # Show routed printer name (Objective 1)
            # Use display_name if available for UI; routed_printer_name may be spooler name
            p_display = self.routed_printer_display_name or self.routed_printer_name or "System Default"
            self.printer_label.setText(f"Printer: {p_display}")
            self.printer_label.setStyleSheet("""
                font-weight: 700;
                color: #334155;
                font-size: 14px;
            """)
        info_card_layout.addWidget(self.printer_label)
        
        # Offline Error Label (Step 2 & 3: UI Feedback Only)
        self.printer_offline_label = QLabel("Connected printer is offline.")
        self.printer_offline_label.setAlignment(Qt.AlignCenter)
        self.printer_offline_label.setStyleSheet("""
            color: #dc2626;
            background-color: #fef2f2;
            border: 1px solid #fecaca;
            border-radius: 6px;
            padding: 6px;
            font-size: 12px;
            font-weight: 600;
        """)
        self.printer_offline_label.hide()
        
        info_card_layout.addWidget(self.printer_offline_label)
        
        # Status Badge (Centered in card)
        self.status_val = QLabel(safe_text(self.job.status, "Pending"))
        self.status_val.setAlignment(Qt.AlignCenter)
        info_card_layout.addWidget(self.status_val, alignment=Qt.AlignCenter)
        
        # Error Message Label (Hidden by default, shown for routing errors)
        self.error_label = QLabel("")
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("""
            color: #dc2626;
            font-size: 12px;
            font-weight: 500;
            padding: 8px;
            background-color: #fef2f2;
            border: 1px solid #fecaca;
            border-radius: 6px;
            margin-top: 6px;
        """)
        self.error_label.hide()  # Hidden by default
        info_card_layout.addWidget(self.error_label)
        
        layout.addWidget(info_card)
        
        # Mode-aware button detection (before creating buttons)
        is_auto = hasattr(self.dashboard, 'auto_mode') and self.dashboard.auto_mode
        
        # Cancel Button (Manual Mode Only)
        if not is_auto:
            self.cancel_btn = QPushButton("Cancel")
            self.cancel_btn.setFixedSize(90, 28)
            self.cancel_btn.setCursor(Qt.PointingHandCursor)
            self.cancel_btn.setStyleSheet("""
                QPushButton {
                    min-width: 90px;
                    max-width: 90px;
                    min-height: 28px;
                    max-height: 28px;
                    padding: 4px 8px;
                    border-radius: 5px;
                    font-size: 9px;
                    font-weight: 600;
                    text-align: center;
                    background-color: #dc2626;
                    color: #ffffff;
                    border: 1px solid #b91c1c;
                }
                QPushButton:hover {
                    background-color: #b91c1c;
                    border-color: #991b1b;
                }
                QPushButton:disabled {
                    background-color: #9ca3af;
                    color: #ffffff;
                    border: 1px solid #6b7280;
                }
            """)
            self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        
        # Print Button
        self.print_btn = QPushButton("Print")
        self.print_btn.setFixedSize(90, 28)
        self.print_btn.setCursor(Qt.PointingHandCursor)
        self.print_btn.setStyleSheet("""
            QPushButton {
                min-width: 90px;
                max-width: 90px;
                min-height: 28px;
                max-height: 28px;
                padding: 4px 8px;
                border-radius: 5px;
                font-size: 9px;
                font-weight: 500;
                text-align: center;
                background-color: #3b82f6;
                color: #ffffff;
                border: 1px solid #2563eb;
            }
            QPushButton:hover {
                background-color: #2563eb;
                border-color: #1d4ed8;
            }
            QPushButton:disabled {
                background-color: #9ca3af;
                color: #ffffff;
                border: 1px solid #6b7280;
            }
        """)
        self.print_btn.clicked.connect(self.on_print_clicked)
        
        # Layout: [Cancel] [Print] in Manual Mode, or just [Print] in Auto Mode
        layout.addStretch()

        footer_layout = QHBoxLayout()
        footer_layout.addStretch()

        if not is_auto:
            footer_layout.addWidget(self.cancel_btn)
            footer_layout.addSpacing(12)

        footer_layout.addWidget(self.print_btn)
        footer_layout.addStretch()

        layout.addLayout(footer_layout)

        # APPLY INITIAL STATE AFTER CREATING BUTTONS (FIX: Move from above)
        if not self.routed_printer_name:
             self.print_btn.setEnabled(False)
        elif self.printer_status == "Offline":
            self.printer_offline_label.show()
            self.print_btn.setEnabled(False)
            self.print_btn.setText("Offline")


        # Mode-aware behavior initialization (is_auto already defined above)
        if is_auto:
            self.print_btn.hide()
            # Trigger print immediately for Auto Mode if job is still pending
            current_status = (self.job.status or 'Pending').lower()
            if current_status == 'pending':
                # Minimal delay to ensure UI listeners are active before starting print
                def auto_print_with_routing_check():
                    """Check for routing errors before auto-printing (Updated for per-job display)"""
                    printer_manager = getattr(self.dashboard, 'printer_manager', None)
                    if printer_manager:
                        try:
                            # Get available printers for routing
                            available_printers_raw = printer_manager.get_available_printers()
                            available_printers = [p.get('name') for p in available_printers_raw if p.get('name')]
                            
                            if available_printers:
                                # Call routing function directly
                                selected, error = printer_manager.select_printer_for_job(self.job, available_printers)
                                
                                # Update instance variables and UI immediately (Mode B)
                                self.routed_printer_name = selected
                                self.routing_error_message = error
                                
                                if error:
                                    # Show routing error in printer label position (Objective 4)
                                    self.printer_label.setText(error)
                                    self.printer_label.setStyleSheet("""
                                        color: #dc2626;
                                        font-size: 13px;
                                        font-weight: 600;
                                        padding: 4px;
                                        background-color: #fef2f2;
                                        border: 1px solid #fecaca;
                                        border-radius: 6px;
                                    """)
                                    self.error_label.hide() # Do not duplicate messages
                                    
                                    # Show print button for manual retry after printer is connected
                                    self.print_btn.show()
                                    self.print_btn.setText("RETRY")
                                    logger.warning(f"Auto-print blocked by routing error for job {self.job.job_id}: {error}")
                                    return
                                else:
                                    # Update printer label with successful route
                                    self.printer_label.setText(f"Printer: {selected or 'System Default'}")
                                    self.printer_label.setStyleSheet("font-weight: 700; color: #334155; font-size: 14px;")
                                    self.error_label.hide()
                            
                            # No routing error - proceed with auto-print
                        except Exception as e:
                            logger.warning(f"Error during auto-print routing check: {e}")
                    
                    # Call print_job if available
                    if hasattr(self.dashboard, 'print_job'):
                        self.dashboard.print_job(self.job)
                
                QTimer.singleShot(30, auto_print_with_routing_check)
        
        # Apply initial styling and visibility based on current status and mode
        self.update_status_style(self.status_val.text())

    def _update_cancel_visibility(self, status):
        """Helper to control Cancel button visibility based on status and mode"""
        if not hasattr(self, 'cancel_btn') or sip.isdeleted(self.cancel_btn):
            return
            
        is_auto = hasattr(self.dashboard, 'auto_mode') and self.dashboard.auto_mode
        s = (status or "").lower()
        
        # Cancel button visible ONLY in Manual Mode AND Pending state
        if not is_auto and s == "pending":
            self.cancel_btn.show()
        else:
            self.cancel_btn.hide()

        
    def on_print_clicked(self):
        # If already completed, this button acts as "PICKUP" to close the popup
        if self.print_btn.text() == "PICKUP":
            logger.info(f"PICKUP clicked for job {self.job.job_id}. Closing popup.")
            self.accept()
            return

        # ===== ROUTING ERROR CHECK (Updated for per-job display) =====
        printer_manager = getattr(self.dashboard, 'printer_manager', None)
        if printer_manager:
            try:
                # FIX 3: POPUP UI MUST USE ROUTING RESULT ONLY (Authorized printers)
                available_printers_raw = printer_manager.get_authorized_printers()
                
                # Call routing function (internally uses get_authorized_printers)
                selected, error = printer_manager.select_printer_for_job(self.job)
                
                # Store result
                self.routed_printer_name = selected
                self.routing_error_message = error
                    
                if error:
                    # Show error in printer label position (Objective 4)
                    self.printer_label.setText(error)
                    self.printer_label.setStyleSheet("""
                        color: #dc2626;
                        font-size: 13px;
                        font-weight: 600;
                        padding: 4px;
                        background-color: #fef2f2;
                        border: 1px solid #fecaca;
                        border-radius: 6px;
                    """)
                    self.error_label.hide() # Do not duplicate messages
                    self.print_btn.setEnabled(False)
                    self.print_btn.setText("No Printer")
                    logger.warning(f"Routing error for job {self.job.job_id}: {error}")
                    return
                else:
                    # Success - update printer name
                    self.printer_label.setText(f"Printer: {selected or 'System Default'}")
                    self.printer_label.setStyleSheet("font-weight: 700; color: #334155; font-size: 14px;")
                    self.error_label.hide()
                    
            except Exception as e:
                logger.warning(f"Error during manual print routing check: {e}")
                self.error_label.setText(f"Routing check error: {e}")
                self.error_label.show()
                return

        # ===== EXISTING PRINT FLOW =====
        # Call existing print trigger logic
        if hasattr(self.dashboard, 'print_job'):
            self.dashboard.print_job(self.job)
        
        # Hide cancel button immediately when printing starts
        self._update_cancel_visibility("Printing")
        
        # Disable button after click to prevent double-printing
        self.print_btn.setEnabled(False)
        self.print_btn.setText("PRINTING...")

        self.print_btn.setStyleSheet("""
            QPushButton {
                min-width: 90px;
                max-width: 90px;
                min-height: 28px;
                max-height: 28px;
                padding: 4px 8px;
                border-radius: 5px;
                font-size: 9px;
                font-weight: 500;
                text-align: center;
                background-color: #9ca3af;
                color: #ffffff;
                border: 1px solid #6b7280;
            }
        """)

    def on_cancel_clicked(self):
        """
        Cancel button handler - calls the SAME cancel logic as context menu.
        This is the EXACT same flow as: _on_jobs_context_menu → cancel_job_by_id → stop_job
        """
        try:
            job_id = self.job.job_id
            logger.info(f"Cancel button clicked for job {job_id}")
            
            # 1. Capture Dashboard Reference (ensure it exists before closing)
            dash = self.dashboard
            
            # 2. Close popup IMMEDIATELY to free the UI event loop
            self.accept()
            
            # 3. Defer cancellation logic to the NEXT event loop cycle
            # This prevents win32print blocking calls from executing inside the dialog event loop
            if dash and hasattr(dash, 'cancel_job_by_id'):
                QTimer.singleShot(0, lambda: dash.cancel_job_by_id(job_id))
            
        except Exception as e:
            logger.error(f"Error in popup cancel button: {e}")
            # Ensure popup is closed even if deferred call setup fails
            try:
                self.accept()
            except Exception:
                pass
    
    def on_view_clicked(self):        # ← 4 spaces
        try:
            logger.info(f"DEBUG PREVIEW: color_mode='{self.job.color_mode}' file_type='{self.job.file_type}'")                          # ← 8 spaces
            import threading
            def generate_preview():
                try:
                    from shared.file_processor import generate_final_print_pdf
                    from shared.file_processor import ensure_local_path
                    local_path, is_temp = ensure_local_path(self.job.file_path)
                    preview_pdf = generate_final_print_pdf(
                        file_path=local_path,
                        file_type=self.job.file_type or 'pdf',
                        page_size=self.job.page_size or 'A4',
                        orientation=self.job.orientation or 'Portrait',
                        layout_pages=self.job.layout_pages or 1,
                        color_mode=self.job.color_mode or 'Color',
                        page_range=self.job.page_range or ''
                    )
                    from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
                    QMetaObject.invokeMethod(self, "_show_preview_window",
                        Qt.QueuedConnection, Q_ARG(str, preview_pdf))
                except Exception as e:
                    from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
                    QMetaObject.invokeMethod(self, "_on_preview_error",
                        Qt.QueuedConnection, Q_ARG(str, str(e)))
            threading.Thread(target=generate_preview, daemon=True).start()
        except Exception as e:
            logger.error(f"Preview error: {e}")

    @pyqtSlot(str)
    def _show_preview_window(self, preview_pdf_path):
        try:
            logger.info(f"DEBUG PREVIEW FILE: {preview_pdf_path}")
            import os, sys, subprocess
            if sys.platform.startswith('win'):
                os.startfile(preview_pdf_path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', preview_pdf_path])
            else:
                subprocess.Popen(['xdg-open', preview_pdf_path])
        except Exception as e:
            logger.error(f"Show preview error: {e}")

    @pyqtSlot(str)
    def _on_preview_error(self, error_msg):
        QMessageBox.warning(self, "Preview Failed", f"Could not generate preview:\n{error_msg}")

    def contextMenuEvent(self, event):
        try:
            from PyQt5.QtWidgets import QMenu, QAction
            from PyQt5.QtGui import QCursor
            menu = QMenu(self)
            menu.setStyleSheet("""
                QMenu { background-color: #ffffff; border: 1px solid #e5e7eb;
                    border-radius: 6px; padding: 4px; }
                QMenu::item { color: #111827; padding: 8px 20px; font-size: 13px; }
                QMenu::item:selected { background-color: #6366f1; color: #ffffff; border-radius: 4px; }
            """)
            preview_action = QAction("Preview (Final Print)", self)
            preview_action.triggered.connect(self.on_view_clicked)
            menu.addAction(preview_action)
            menu.exec_(QCursor.pos())
        except Exception as e:
            logger.error(f"Context menu error: {e}")
     

    def update_status(self, status):
        """External bridge to update popup status and UI state dynamically"""
        try:
            if sip.isdeleted(self):
                return
            
            # Update internal job object status
            if hasattr(self, 'job'):
                self.job.status = status
                
                # Auto Mode dismissal guard: Clear dismissal when status changes from Pending
                if hasattr(self.dashboard, 'dismissed_auto_jobs') and self.job.job_id in self.dashboard.dismissed_auto_jobs:
                    if status.lower() != 'pending':
                        self.dashboard.dismissed_auto_jobs.discard(self.job.job_id)
                        logger.debug(f"Auto Mode: Job {self.job.job_id} status changed to {status}, removed from dismissed set.")
                
            # Update UI labels and styles
            if hasattr(self, 'status_val') and self.dashboard._is_alive(self.status_val):
                self.status_val.setText(status)
                self.update_status_style(status)
            
            # Show error message if status is Failed and error_message exists
            if status.lower() == 'failed' and hasattr(self, 'job') and hasattr(self.job, 'error_message'):
                error_msg = self.job.error_message
                if error_msg:
                    self.error_label.setText(error_msg)
                    self.error_label.show()
                    # Re-enable button for retry
                    if hasattr(self, 'print_btn'):
                        self.print_btn.show()
                        self.print_btn.setEnabled(True)
                        self.print_btn.setText("RETRY")
            elif status.lower() in ['printing', 'printing started', 'completed']:
                # Hide error label when job is printing or completed successfully
                # (Routing errors are handled in on_print_clicked and shown before status changes)
                if hasattr(self, 'error_label'):
                    self.error_label.hide()
                
            logger.debug(f"Popup synchronized with job {self.job.job_id} status: {status}")
        except Exception as e:
            logger.error(f"Error in popup update_status: {e}")

    def on_dashboard_signal(self, operation, data):
        """Listen for job status updates from the dashboard signal"""
        try:
            # Safety check: do nothing if dialog is closed/deleted
            if sip.isdeleted(self) or not self.isVisible():
                return
                
            if operation == "update_job_status":
                # Data format followed from DashboardWindow.handle_thread_safe_operation
                job_id, status, progress, details = data
                if job_id == self.job.job_id:
                    self.update_status(status)
            elif operation == "handle_websocket_message":
                # WebSocket messages also update statuses
                if data.get('type') == 'job_update':
                    job_id = data.get('job_id')
                    status = data.get('status')
                    if job_id == self.job.job_id:
                        self.status_val.setText(status)
                        self.update_status_style(status)
        except Exception as e:
            logger.error(f"Error in popup status update: {e}")

    def _refresh_printer_status(self):
        """Step 2: Periodic check for printer connectivity (Real-time UI only)"""
        try:
            if sip.isdeleted(self) or not self.routed_printer_name:
                return
                
            # Step 3B: Early return if job already Printing or Completed
            current_status = (self.job.status or "Pending").lower()
            if any(s in current_status for s in ["printing", "completed"]):
                return

            printer_manager = getattr(self.dashboard, 'printer_manager', None)
            if not printer_manager:
                return

            # FIX 3: POPUP REFRESH MUST USE AUTHORIZED PRINTERS ONLY
            available_printers_raw = printer_manager.get_authorized_printers()
            printer_info = next((p for p in available_printers_raw if p.get('name') == self.routed_printer_name), None)
            
            # Update internal status state
            new_status = printer_info.get('status', 'Offline') if printer_info else 'Offline'
            self.printer_status = new_status

            # Step 2 Implementation: UI State Updates
            if new_status == "Offline":
                self.printer_offline_label.show()
                self.printer_offline_label.setText("Connected printer is offline.")
                self.print_btn.setEnabled(False)
                self.print_btn.setText("Offline")
            else:
                self.printer_offline_label.hide()
                # Restore button state if it was "Offline" (Respect Step 3A Routing Errors)
                if self.print_btn.text() == "Offline":
                    # If a routing error exists, it MUST keep the button disabled
                    if self.routing_error_message:
                        self.print_btn.setEnabled(False)
                        self.print_btn.setText("Print")
                    else:
                        self.print_btn.setEnabled(True)
                        # Ensure button text matches current job status state
                        if "failed" in current_status:
                            self.print_btn.setText("RETRY")
                        else:
                            self.print_btn.setText("Print")
        except Exception as e:
            logger.debug(f"Error in popup printer status refresh: {e}")

    def closeEvent(self, event):
        """Step 4: Cleanup timer on popup close to prevent orphan polling"""
        try:
            if hasattr(self, '_printer_status_timer'):
                self._printer_status_timer.stop()
                self._printer_status_timer.deleteLater()
            
            # Auto Mode dismissal guard: Mark job as dismissed if closed via X in Auto Mode
            is_auto = hasattr(self.dashboard, 'auto_mode') and self.dashboard.auto_mode
            if is_auto and hasattr(self, 'job') and hasattr(self.dashboard, 'dismissed_auto_jobs'):
                # Only mark as dismissed if job is still Pending (not Printed/Picked/Cancelled)
                current_status = (self.job.status or 'Pending').lower()
                if current_status == 'pending':
                    self.dashboard.dismissed_auto_jobs.add(self.job.job_id)
                    logger.info(f"Auto Mode: Job {self.job.job_id} dismissed via X. Will not reopen until status changes.")
            
            # Ensure finished(int) signal is emitted to reset dashboard state
            self.accept()
        except Exception:
            self.accept()


    def update_status_style(self, status):
        """Update status label styling and button state based on current status and mode"""
        # Immediately update cancel button visibility
        self._update_cancel_visibility(status)

        if not hasattr(self, 'status_val') or sip.isdeleted(self.status_val):
            return
            
        is_auto = hasattr(self.dashboard, 'auto_mode') and self.dashboard.auto_mode
        s = status.lower()
        
        # EXACT status-to-chip logic from create_print_job_card (dashboard list)
        if s == 'completed':
            status_bg = "#dcfce7"
            status_color = "#15803d"
            status_text = "Completed"
        elif s == 'failed':
            status_bg = "#fee2e2"
            status_color = "#dc2626"
            status_text = "Failed"
        elif s in ['printing', 'printing started']:
            status_bg = "#dbeafe"
            status_color = "#1e40af"
            status_text = "Printing"
        elif s == 'cancelled':
            status_bg = "#f3f4f6"
            status_color = "#374151"
            status_text = "Cancelled"
        else:  # Pending, In Queue, Processing
            status_bg = "#fef3c7"
            status_color = "#d97706"
            status_text = "Pending"

        # Apply the badge style matching the PRINT button's size and shape
        self.status_val.setText(status_text)
        self.status_val.setAlignment(Qt.AlignCenter)
        self.status_val.setStyleSheet(f"""
            background-color: {status_bg}; 
            color: {status_color}; 
            border: 1px solid #cbd5e1;
            border-radius: 10px; 
            padding: 4px 24px; 
            font-weight: bold; 
            font-size: 13px;
            min-width: 240px;
        """)
        
        # Ensure bold weight is applied
        st_chip_font = self.status_val.font()
        st_chip_font.setWeight(QFont.Bold)
        st_chip_font.setPointSize(11) # Base size, stylesheet will override
        self.status_val.setFont(st_chip_font)


        # Handle Action Button state (Popup-specific behavior)
        if status_text == "Completed":
            self.print_btn.setText("PICKUP")
            self.print_btn.setEnabled(True)
            self.print_btn.show()
            self.print_btn.setStyleSheet("""
                QPushButton {
                    min-width: 90px;
                    max-width: 90px;
                    min-height: 28px;
                    max-height: 28px;
                    padding: 4px 8px;
                    border-radius: 5px;
                    font-size: 9px;
                    font-weight: 500;
                    text-align: center;
                    background-color: #10b981;
                    color: #ffffff;
                    border: 1px solid #059669;
                }
                QPushButton:hover {
                    background-color: #059669;
                    border-color: #047857;
                }
            """)
        elif status_text == "Failed":
            self.print_btn.setText("RETRY")
            self.print_btn.setEnabled(True)
            self.print_btn.show()
            self.print_btn.setStyleSheet("""
                QPushButton {
                    min-width: 90px;
                    max-width: 90px;
                    min-height: 28px;
                    max-height: 28px;
                    padding: 4px 8px;
                    border-radius: 5px;
                    font-size: 9px;
                    font-weight: 500;
                    text-align: center;
                    background-color: #ef4444;
                    color: #ffffff;
                    border: 1px solid #dc2626;
                }
                QPushButton:hover {
                    background-color: #dc2626;
                    border-color: #b91c1c;
                }
            """)
        elif status_text == "Printing":
            self.print_btn.setText("PRINTING...")
            self.print_btn.setEnabled(False)
            if is_auto:
                self.print_btn.hide()
            else:
                self.print_btn.show()
                self.print_btn.setStyleSheet("""
                    QPushButton {
                        min-width: 90px;
                        max-width: 90px;
                        min-height: 28px;
                        max-height: 28px;
                        padding: 4px 8px;
                        border-radius: 5px;
                        font-size: 9px;
                        font-weight: 500;
                        text-align: center;
                        background-color: #9ca3af;
                        color: #ffffff;
                        border: 1px solid #6b7280;
                    }
                """)
        else: # Pending
            if is_auto:
                self.print_btn.hide()
            else:
                self.print_btn.show()
                # Maintain default PRINT style if not printing/failed/completed
                self.print_btn.setText("Print")
                self.print_btn.setEnabled(True)
                self.print_btn.setStyleSheet("""
                    QPushButton {
                        min-width: 90px;
                        max-width: 90px;
                        min-height: 28px;
                        max-height: 28px;
                        padding: 4px 8px;
                        border-radius: 5px;
                        font-size: 9px;
                        font-weight: 500;
                        text-align: center;
                        background-color: #3b82f6;
                        color: #ffffff;
                        border: 1px solid #2563eb;
                    }
                    QPushButton:hover {
                        background-color: #2563eb;
                        border-color: #1d4ed8;
                    }
                    QPushButton:disabled {
                        background-color: #9ca3af;
                        color: #ffffff;
                        border: 1px solid #6b7280;
                    }
                """)

        # Add FINAL override to respect Offline status even during status changes
        current_s = status.lower()
        if not any(s in current_s for s in ["printing", "completed"]):
            if hasattr(self, 'printer_status') and self.printer_status == "Offline":
                self.print_btn.setEnabled(False)
                self.print_btn.setText("Offline")
                if hasattr(self, 'printer_offline_label'):
                    self.printer_offline_label.show()
            elif hasattr(self, 'routing_error_message') and self.routing_error_message:
                self.print_btn.setEnabled(False)




class ColdStartPrinterDiscoveryWorker(QThread):
    finished = pyqtSignal()

    def run(self):
        try:
            if hasattr(self.parent(), 'printer_manager'):
                self.parent().printer_manager.thread_safe_discovery.force_refresh()
        except Exception as e:
            logger.error(f"Cold start discovery worker error: {e}")
        finally:
            self.finished.emit()

class DashboardWindow(QMainWindow):
    # Signal for thread-safe operations
    thread_safe_signal = pyqtSignal(str, object)
    
    def __init__(self, shopkeeper_data, on_logout=None):
        super().__init__()
        self._is_initializing = True
        import time
        self._last_activity_time = time.time()
        QTimer.singleShot(0, self.showMaximized)
        self.setMinimumSize(1024, 600)
        self.sleep_watchdog = QTimer(self)
        self.sleep_watchdog.timeout.connect(self._check_system_resume)
        self.sleep_watchdog.start(5000)
        try:
            logger.info("Initializing DashboardWindow...")
            
            self.shopkeeper_data = shopkeeper_data
            logger.info("Setting up authentication manager...")
            self.auth_manager = AuthManager()
            
            logger.info("Setting up printer manager...")
            self.printer_manager = PrinterManager()
            
            self.websocket_client = None
            self.print_workers = {}
            self.on_logout_cb = on_logout
            # Prevent UI refresh from interrupting open menus
            self._suspend_jobs_refresh = False
            self._is_refreshing_jobs = False
            
            # Track known jobs to avoid duplicate popups
            self.known_job_ids = set()
            self.is_first_load = True
            
            # Printing mode (default to manual)
            self.auto_mode = False
            
            # Track selected jobs for bulk actions
            self.selected_job_ids = set()
            
            # Selection mode state
            self.selection_mode = False
            self.pending_action = None  # Track which action is pending
            
            # Map job IDs to job cards and job objects for selection
            self.job_cards_map = {}  # {job_id: {'card': widget, 'job': job_object}}
            
            # Track previous printer connection state for disconnect popup
            self.previous_printer_connected = None  # None = initial state, True = connected, False = disconnected
            self.printer_disconnect_popup_shown = False  # Track if popup has been shown for current disconnect state
            self.dashboard_ready = False  # Track if dashboard is visible and ready (set in showEvent)
            
            # Sequential popup management
            self.popup_job_queue = []
            self.is_popup_active = False
            self._active_job_popups = []
            self._cancel_dialog_active = False
            
            # Auto Mode dismissal guard (in-memory only, resets on restart)
            self.dismissed_auto_jobs = set()  # Track job IDs dismissed via X in Auto Mode
            
            # Central pricing state for UI synchronization
            self.pricing_state = {
                "bw_single": 2.0,
                "bw_double": 1.5,
                "color_single": 10.0,
                "color_double": 8.0
            }
            
            # Initialize pricing input variables for both sets to None
            self.sidebar_bw_single_input = None
            self.sidebar_bw_double_input = None
            self.sidebar_color_single_input = None
            self.sidebar_color_double_input = None
            
            self.settings_bw_single_input = None
            self.settings_bw_double_input = None
            self.settings_color_single_input = None
            self.settings_color_double_input = None

            logger.info("Setting up database session...")
            self.db = SessionLocal()
            
            # Initialize API client with token from auth (if available)
            token = self.shopkeeper_data.get('session_token')
            self.api_client = ApiClient(session_token=token)
            if token:
                self.auth_manager.api_client.set_session_token(token)
            logger.info(f"ApiClient initialized with token: {'Available' if token else 'Not Available'}")
            
            # Phase 5: Ensure token is stored for WS setup
            self.session_token = token
            
            # Dashboard KPI Worker initialization
            self.kpi_worker = None
            
            # Current page
            self.current_page = "dashboard"
            
            logger.info("Initializing UI...")
            self.init_ui()
            
            # Connect thread-safe signal
            self.thread_safe_signal.connect(self.handle_thread_safe_operation)
            
            logger.info("Setting up websocket...")
            self.setup_websocket()
            
            logger.info("DashboardWindow initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize DashboardWindow: {e}")
            raise
        self.load_job_printers()  # Load printers for job selection
        # Ensure a current printer is set on startup if OS default exists
        try:
            if not self.printer_manager.current_printer:
                default = self.printer_manager.get_default_printer(self.shopkeeper_data['shop_id'])
                if default:
                    self.printer_manager.current_printer = default
                else:
                    # As a fallback, pick the first available active printer if any
                    actives = self.printer_manager.get_active_printers(self.shopkeeper_data['shop_id'])
                    if actives:
                        self.printer_manager.current_printer = actives[0]
        except Exception:
            pass
        # ── Startup job recovery ──────────────────────────────────────
        # Recover jobs left in transient states by a prior crash/close.
        # Must run BEFORE load_print_jobs() and setup_timer() so the
        # spooler monitor never picks up these stale jobs.
        self._recover_interrupted_jobs()

        QTimer.singleShot(0, self.load_print_jobs)
        self.setup_timer()
        self.setup_polling_timer()  # Setup fallback polling
        self.setup_shortcuts()
        
        # Set default mode to manual
        self.set_manual_mode()
        
        # Setup printer connectivity status polling
        self.setup_printer_connectivity_polling()

        # Schedule background printer discovery (avoids startup freeze)
        QTimer.singleShot(100, self._start_background_printer_discovery)

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def safe_db_operation(self, operation_func):
        """
        Wrapper for safe database operations with automatic rollback.

        Usage::

            def my_operation():
                # Your DB logic here
                return result

            return self.safe_db_operation(my_operation)
        """
        try:
            result = operation_func()
            self.db.commit()
            return result
        except Exception as e:
            self.db.rollback()
            error_msg = f"Database operation failed: {str(e)}"
            logger.error(error_msg)
            QMessageBox.critical(self, "Database Error", error_msg)
            return None

    def _recover_interrupted_jobs(self):
        """Recover jobs left in transient states by a prior crash or unexpected close.

        Runs once at startup, BEFORE the spooler monitor begins polling.
        Any job still marked as 'In Queue', 'Printing Started', 'Processing',
        or 'Printing' cannot realistically be in the Windows spooler any more,
        so we mark them 'Failed' with a clear error_message and alert the
        shopkeeper.
        """
        STALE_STATUSES = ['In Queue', 'Printing Started', 'Processing', 'Printing']
        try:
            stale_jobs = self.db.query(PrintJob).filter(
                PrintJob.shop_id == self.shopkeeper_data['shop_id'],
                PrintJob.status.in_(STALE_STATUSES)
            ).all()

            if not stale_jobs:
                return  # Nothing to recover

            # Mark each stale job as Failed with a descriptive message
            recovered_names = []
            for job in stale_jobs:
                old_status = job.status
                job.status = 'Failed'
                job.error_message = (
                    f'Interrupted - app closed while job was "{old_status}". '
                    f'Please verify at the printer before reprinting.'
                )
                recovered_names.append(
                    f"  - {job.filename or job.job_id[:8]}  (was: {old_status})"
                )
                logger.warning(
                    f"Startup recovery: job {job.job_id} "
                    f"changed from '{old_status}' to 'Failed' (interrupted)"
                )

            self.db.commit()

            # Show a visible warning so the shopkeeper knows
            count = len(recovered_names)
            details = "\n".join(recovered_names)
            QMessageBox.warning(
                self,
                "Interrupted Jobs Detected",
                f"{count} job(s) were interrupted by an unexpected shutdown.\n"
                f"They have been marked as Failed.\n\n"
                f"{details}\n\n"
                f"Please check the printer output before reprinting."
            )
            logger.info(f"Startup recovery complete: {count} job(s) marked as Failed")

        except Exception as e:
            self.db.rollback()
            logger.error(f"Startup job recovery failed: {e}")

    def bulk_delete_jobs(self, job_ids):
        """Delete multiple jobs safely, cleaning up Cloudinary assets as needed."""
        def delete_operation():
            from shared.cloudinary_helper import delete_file_from_cloudinary
            deleted_count = 0
            for job_id in job_ids:
                job = self.db.query(PrintJob).filter_by(job_id=job_id).first()
                if job:
                    # Remove from Cloudinary if an asset is linked
                    if job.cloudinary_public_id:
                        try:
                            delete_file_from_cloudinary(job.cloudinary_public_id)
                        except Exception:
                            pass  # Non-fatal: continue deletion even if cloud cleanup fails

                    self.db.delete(job)
                    deleted_count += 1

            return deleted_count

        count = self.safe_db_operation(delete_operation)
        if count:
            QMessageBox.information(self, "Success", f"Deleted {count} job(s)")
            self.load_print_jobs()

        return count

    def _api_job_to_obj(self, job_dict):
        """Convert API job dictionary to an object-like structure for backward compatibility"""
        from types import SimpleNamespace
        from datetime import datetime
        # Parse dates
        created_at = None
        if job_dict.get('created_at'):
            try:
                # Handle ISO 8601 format
                created_at = datetime.fromisoformat(job_dict['created_at'].replace('Z', '+00:00'))
            except:
                pass
        
        return SimpleNamespace(
            job_id=job_dict.get('job_id'),
            filename=job_dict.get('filename'),
            file_path=job_dict.get('file_path'),
            status=job_dict.get('status'),
            amount=job_dict.get('amount', 0.0),
            created_at=created_at,
            total_pages=job_dict.get('total_pages'),
            copies=job_dict.get('copies', 1),
            page_range=job_dict.get('page_range'),
            page_size=job_dict.get('page_size'),
            orientation=job_dict.get('orientation'),
            print_side=job_dict.get('print_side'),
            color_mode=job_dict.get('color_mode'),
            layout_pages=job_dict.get('layout_pages', 1)
        )

    # ------------------------
    # Safety helpers for UI
    # ------------------------
    def _is_alive(self, widget):
        try:
            return widget is not None and not sip.isdeleted(widget)
        except Exception:
            return False

    def _safe_restore_jobs_scroll(self, value):
        """Safely restore scroll position after layout updates"""
        try:
            if hasattr(self, 'jobs_cards_scroll') and self._is_alive(self.jobs_cards_scroll):
                self.jobs_cards_scroll.verticalScrollBar().setValue(value)
        except Exception:
            pass

    def _safe_set_checked(self, widget, value):
        try:
            if self._is_alive(widget):
                widget.setChecked(value)
        except RuntimeError:
            pass

    def _safe_set_enabled(self, widget, value):
        try:
            if self._is_alive(widget):
                widget.setEnabled(value)
        except RuntimeError:
            pass

    def _safe_set_text(self, widget, text):
        try:
            if self._is_alive(widget):
                widget.setText(text)
        except RuntimeError:
            pass

    def _safe_single_shot(self, msec, func):
        """Run func later only if this window still exists."""
        self_ref = weakref.ref(self)
        def _wrapped():
            inst = self_ref()
            try:
                if inst is None or sip.isdeleted(inst):
                    return
            except Exception:
                return
            try:
                func()
            except RuntimeError:
                pass
        QTimer.singleShot(msec, _wrapped)

    def create_reprint_handler(self, job):
        """Create a handler function for reprinting a job"""
        def handler():
            try:
                # Prevent accidental double-clicks
                try:
                    sender_btn = self.sender()
                    if sender_btn:
                        sender_btn.setEnabled(False)
                except Exception:
                    sender_btn = None
                logger.info(f"Reprint requested for job {job.job_id}")
                # Validate file path exists before trying to print
                if not job.file_path or not os.path.exists(job.file_path):
                    logger.error(f"File path missing for job {job.job_id}: {job.file_path}")
                    QMessageBox.warning(self, "File Missing", "Original file not found on disk.")
                else:
                    self.print_job(job)
                # Re-enable the button shortly after to keep UI responsive
                try:
                    from PyQt5.QtCore import QTimer
                    if sender_btn:
                        # Use a safe callback that checks the widget's validity at runtime
                        def _reenable():
                            try:
                                # sender_btn may be deleted if the row is rebuilt; guard it
                                if sender_btn and getattr(sender_btn, 'setEnabled', None):
                                    # QWidget.isEnabled() access will also throw if deleted; inside try
                                    sender_btn.setEnabled(True)
                            except Exception:
                                pass
                        QTimer.singleShot(800, _reenable)
                except Exception:
                    try:
                        if sender_btn:
                            sender_btn.setEnabled(True)
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Error reprinting job {job.job_id}: {e}")
                QMessageBox.warning(self, "Error", f"Failed to reprint job {job.job_id}")
        return handler
    
    def create_cancel_handler(self, job):
        """Create a handler function for canceling a job"""
        def handler():
            try:
                self.stop_job(job)
            except Exception as e:
                logger.error(f"Error canceling job {job.job_id}: {e}")
                QMessageBox.warning(self, "Error", f"Failed to cancel job {job.job_id}")
        return handler
    
    def create_delete_handler(self, job):
        """Create a handler function for deleting a job"""
        def handler():
            try:
                self.delete_job(job)
            except Exception as e:
                logger.error(f"Error deleting job {job.job_id}: {e}")
                QMessageBox.warning(self, "Error", f"Failed to delete job {job.job_id}")
        return handler

    def _clear_layout(self, layout):
        """Recursively clear a layout of all widgets, sub-layouts, and spacers"""
        if layout is None:
            return

        while layout.count():
            item = layout.takeAt(0)

            if item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()

            elif item.layout():
                self._clear_layout(item.layout())
    
    def create_copy_handler(self, job):
        """Create a handler function for copying job ID"""
        def handler():
            try:
                QApplication.clipboard().setText(job.job_id)
                self.show_toast(f"Job ID {job.job_id} copied to clipboard")
            except Exception as e:
                logger.error(f"Error copying job ID {job.job_id}: {e}")
                QMessageBox.warning(self, "Error", f"Failed to copy job ID")
        return handler

    def _format_job_display_name(self, job):
        """Return a clean, human-friendly display name for a print job.

        Rules:
        - Prefer stored filename; fallback to basename of file_path
        - URL-decode any encoded characters
        - Strip temporary prefixes like 'temp_'
        - Strip leading UUID prefixes like '<uuid>_', '<uuid>-'
        - Remove query/hash suffixes, replace '+' with space
        - If cleaned name empty or starts with '.', fallback to original filename
        """
        try:
            raw_name = job.filename or os.path.basename(job.file_path or "") or ""
            name = os.path.basename(raw_name)
            name = unquote(name).replace('+', ' ')
            # Strip query/hash
            if '?' in name:
                name = name.split('?', 1)[0]
            if '#' in name:
                name = name.split('#', 1)[0]
            # Strip temp_ prefix
            while name.lower().startswith("temp_"):
                name = name[5:]
            # Strip leading UUID prefixes repeatedly
            uuid_re = re.compile(r'^[{(]?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}[)}]?')
            while True:
                m = uuid_re.match(name)
                if not m:
                    break
                rest = name[m.end():]
                # Drop leading separators
                rest = rest.lstrip(" _-.")
                if not rest:
                    break
                name = rest
            # If name still empty, just show placeholder
            if not name or name.strip() == "" or name.startswith('.'):
                return "(no name)"
            return name
        except Exception:
            return job.filename or "(no name)"

    def _human_size(self, num_bytes):
        try:
            size = float(num_bytes or 0)
            for unit in ['B','KB','MB','GB','TB']:
                if size < 1024.0:
                    return f"{size:.1f} {unit}" if unit != 'B' else f"{int(size)} {unit}"
                size /= 1024.0
            return f"{size:.1f} PB"
        except Exception:
            return "-"

    def _icon_for_type(self, file_type):
        """Get icon for file type - returns QIcon"""
        ft = (file_type or '').lower()
        if 'pdf' in ft:
            return get_icon('file', 16)
        if any(x in ft for x in ['png','jpg','jpeg','gif','bmp','tiff']):
            return get_icon('file', 16)
        if any(x in ft for x in ['doc','docx']):
            return get_icon('file', 16)
        return get_icon('file', 16)

    def _status_display_and_style(self, raw_status):
        try:
            s = (raw_status or 'Pending').strip().lower()
            # Normalize separators and common variants
            s = s.replace('_', ' ').replace('-', ' ')
            s = ' '.join(s.split())
            # Synonyms
            synonyms = {
                'queued': 'in queue',
                'inqueue': 'in queue',
                'success': 'completed',
                'error': 'failed',
                'cancel': 'cancelled',
            }
            key = synonyms.get(s, s)
            # Prefer explicit variants for display text
            if key == 'printing completed':
                return 'Printing Completed', 'background:#10b981; color:#fff; font-weight: 600;'
            if key == 'printing started':
                return 'Printing Started', 'background:#dbeafe; color:#1e40af; font-weight: 600;'

            style_map = {
                'in queue': ('In Queue', 'background:#6b7280; color:#fff; font-weight: 600;'),  # Gray
                'processing': ('Processing', 'background:#dbeafe; color:#1e40af; font-weight: 600;'),  # Light blue
                'printing': ('Printing', 'background:#dbeafe; color:#1e40af; font-weight: 600;'),  # Light blue
                'completed': ('Completed', 'background:#10b981; color:#fff; font-weight: 600;'),  # Green
                'failed': ('Failed', 'background:#ef4444; color:#fff; font-weight: 600;'),  # Red
                'cancelled': ('Cancelled', 'background:#f3f4f6; color:#374151; font-weight: 600;'),
                'pending': ('Pending', 'background:#93c5fd; color:#111827; font-weight: 600;'),
            }
            display, style = style_map.get(key, ('Pending', 'background:#93c5fd; color:#111827; font-weight: 600;'))
            return display, style
        except Exception:
            return 'Pending', 'background:#93c5fd; color:#111827; font-weight: 600;'

    def show_toast(self, message):
        try:
            toast = QLabel(message, self)
            toast.setStyleSheet("background: rgba(17,24,39,0.9); color:#fff; padding:8px 12px; border-radius:8px; font-weight:600;")
            toast.setWindowFlags(Qt.ToolTip)
            toast.adjustSize()
            # Position bottom-right
            geo = self.geometry()
            x = geo.width() - toast.width() - 24
            y = geo.height() - toast.height() - 24
            toast.move(x, y)
            toast.show()
            try:
                self._safe_single_shot(2500, toast.close)
            except Exception:
                pass
        except Exception:
            pass

    def setup_select_header(self):
        """Setup custom header with checkbox for Select column"""
        try:
            # Create header checkbox widget
            self.header_checkbox = QCheckBox()
            self.header_checkbox.stateChanged.connect(self.toggle_all_jobs)
            self.header_checkbox.setStyleSheet("""
                QCheckBox {
                    font-weight: 600;
                    font-size: 11px;
                }
            """)
            
            # Set the header widget
            self.jobs_table.setHorizontalHeaderItem(0, QTableWidgetItem(""))
            self.jobs_table.setCellWidget(0, 0, self.header_checkbox)
            
            # Hide Select column by default
            self.jobs_table.setColumnHidden(0, True)
            
        except Exception as e:
            logger.error(f"Error setting up select header: {e}")


    @safe_ui_action("JOB_DOUBLE_CLICK")
    def handle_job_double_click(self, row, column):
        """
        Handle double-click on a print job row - WhatsApp-style multi-select
        
        This method implements a WhatsApp-style selection flow:
        1. Double-click enters selection mode and shows checkboxes for all rows
        2. Automatically selects the double-clicked job
        3. Enables the action menu (Print, Cancel, Delete) in top-right
        4. Allows multi-select of additional jobs
        
        Args:
            row (int): The row index of the double-clicked job
            column (int): The column index of the double-clicked cell
        """
        try:
            logger.info(f"Job double-clicked at row {row}, column {column}")
            
            # Check if the row is valid
            if row < 0 or row >= self.jobs_table.rowCount():
                logger.warning(f"Invalid row index: {row}")
                return
            
            # Get the checkbox widget for this row
            checkbox_widget = self.jobs_table.cellWidget(row, 0)
            if not checkbox_widget or not isinstance(checkbox_widget, QCheckBox):
                logger.warning(f"No checkbox found for row {row}")
                return
            
            # Check if the job is completed (disabled checkbox)
            if not checkbox_widget.isEnabled():
                logger.info(f"Job at row {row} is completed, cannot select")
                self.show_toast("Cannot select completed jobs")
                return
            
            # Get the job_id from first column item
            job_id_item = self.jobs_table.item(row, 1)
            if not job_id_item:
                return
            job_id = job_id_item.data(Qt.UserRole)
            if not job_id:
                return

            # Enter selection mode if not already in it (WhatsApp-style)
            if not self.selection_mode:
                logger.info("Entering selection mode via double-click")
                self.enter_selection_mode("print")  # Default to print action
                self.show_toast("Selection mode activated - select jobs and use menu")
            
            # Select the double-clicked job
            if not checkbox_widget.isChecked():
                logger.info(f"Auto-selecting job {job_id}")
                
                # Temporarily disconnect the signal to avoid recursive calls
                checkbox_widget.stateChanged.disconnect()
                checkbox_widget.setChecked(True)
                # Reconnect the signal
                checkbox_widget.stateChanged.connect(lambda state, jid=job_id: self.handle_job_selection(jid, state))
                
                # Add to selected jobs set
                self.selected_job_ids.add(job_id)
                
                # Update the UI to show selection mode
                self.update_bulk_action_buttons()
                
                logger.info(f"Job {job_id} selected successfully. Total selected: {len(self.selected_job_ids)}")
            else:
                logger.info(f"Job {job_id} is already selected")
                self.show_toast("Job already selected")
            
        except Exception as e:
            logger.error(f"Error handling job double-click: {e}")
            self.show_toast("Error selecting job")



    def update_bulk_action_buttons(self):
        """Update global menu state based on selection"""
        try:
            # Update selection bar visibility and counts
            count = len(getattr(self, 'selected_job_ids', set()))
            if hasattr(self, 'selection_bar'):
                self.selection_bar.setVisible(self.selection_mode)
                if hasattr(self, 'sel_count_label'):
                    self.sel_count_label.setText(f"{count} selected")
        except Exception as e:
            logger.error(f"Error updating bulk action buttons: {e}")

    def get_selected_jobs(self):
        """Get list of selected job objects"""
        selected_jobs = []
        try:
            for job_id in self.selected_job_ids:
                job = self.db.query(PrintJob).filter(
                    PrintJob.job_id == job_id,
                    PrintJob.shop_id == self.shopkeeper_data['shop_id']
                ).first()
                if job:
                    selected_jobs.append(job)
        except Exception as e:
            logger.error(f"Error getting selected jobs: {e}")
        return selected_jobs




    def clear_selection(self):
        """Clear all selections"""
        try:
            for row in range(self.jobs_table.rowCount()):
                checkbox_widget = self.jobs_table.cellWidget(row, 0)
                if checkbox_widget and isinstance(checkbox_widget, QCheckBox):
                    checkbox_widget.setChecked(False)
            
            # Clear selection tracking
            self.selected_job_ids.clear()
            self.update_global_menu_state()
        except Exception as e:
            logger.error(f"Error clearing selection: {e}")

    def update_global_menu_state(self):
        """Update global menu button state based on selection mode and job selection - disabled since menu button removed"""
        try:
            # Menu button removed - this method is kept for compatibility but does nothing
            pass
        except Exception as e:
            logger.error(f"Error updating global menu state: {e}")


    def enter_selection_mode(self, action):
        """Enter selection mode for a specific action - WhatsApp-style"""
        try:
            self.selection_mode = True
            self.pending_action = action
            
            # Show Select column (checkboxes for all rows)
            self.jobs_table.setColumnHidden(0, False)
            
            # Show selection action bar
            if hasattr(self, 'selection_bar'):
                self.selection_bar.setVisible(True)
            
            # Clear any existing selections
            self.clear_selection()
            
            # Update menu button state (will be disabled until jobs are selected)
            self.update_global_menu_state()
            
            logger.info(f"Entered selection mode for action: {action}")
            
        except Exception as e:
            logger.error(f"Error entering selection mode: {e}")


    @safe_ui_action("BULK_ACTION")
    def execute_bulk_action(self, action):
        """Execute bulk action on selected jobs - real-time operations"""
        try:
            selected_jobs = self.get_selected_jobs()
            if not selected_jobs:
                self.show_toast("No jobs selected")
                return
            
            logger.info(f"Executing bulk action '{action}' on {len(selected_jobs)} jobs")
            
            if action == "print":
                self.bulk_print_jobs()
            elif action == "cancel":
                self.bulk_cancel_jobs()
            elif action == "delete":
                self.bulk_delete_jobs()
            else:
                logger.warning(f"Unknown bulk action: {action}")
                self.show_toast(f"Unknown action: {action}")
                
        except Exception as e:
            logger.error(f"Error executing bulk action '{action}': {e}")
            self.show_toast(f"Error executing {action} action")

    def execute_pending_action(self):
        """Execute the pending action on selected jobs (legacy method)"""
        try:
            if not self.pending_action or not self.selected_job_ids:
                return
                
            if self.pending_action == "print":
                self.bulk_print_jobs()
            elif self.pending_action == "cancel":
                self.bulk_cancel_jobs()
            elif self.pending_action == "delete":
                self.bulk_delete_jobs()
            
            # Exit selection mode after action
            self.exit_selection_mode()
            
        except Exception as e:
            logger.error(f"Error executing pending action: {e}")

    @safe_ui_action("UPDATE_JOB_STATUS")
    def update_job_status_in_ui(self, job_id, new_status, progress=None, details=None):
        """Update a single job's status in the UI (both table and cards) without full reload"""
        try:
            # 1. Update Modern Card UI (if it exists)
            if hasattr(self, 'job_cards_map') and job_id in self.job_cards_map:
                card = self.job_cards_map[job_id]['card']
                if self._is_alive(card):
                    # Find status chip in card
                    status_chip = card.findChild(QLabel, f"status_chip_{job_id}")
                    if status_chip:
                        # Determine new style
                        if new_status.lower() == 'completed':
                            bg, color, text = "#dcfce7", "#15803d", "Completed"
                        elif new_status.lower() == 'failed':
                            bg, color, text = "#fee2e2", "#dc2626", "Failed"
                        elif new_status.lower() in ['printing', 'printing started']:
                            bg, color, text = "#dbeafe", "#1e40af", "Printing"
                        elif new_status.lower() == 'cancelled':
                            bg, color, text = "#f3f4f6", "#374151", "Cancelled"
                        else:
                            bg, color, text = "#fef3c7", "#d97706", "Pending"
                        
                        status_chip.setText(text)
                        status_chip.setStyleSheet(f"background-color: {bg}; color: {color}; border-radius: 4px; padding: 2px 8px; font-weight: 600; font-size: 11px;")

            # 2. Update Legacy Table UI (for backward compatibility)
            for row in range(self.jobs_table.rowCount()):
                job_id_item = self.jobs_table.item(row, 1)  # Job ID is column 1
                if job_id_item and job_id_item.text() == job_id[:8]:
                    norm_text, norm_style = self._status_display_and_style(new_status)
                    status_badge = QLabel(norm_text)
                    status_badge.setAlignment(Qt.AlignCenter)
                    status_badge.setStyleSheet(f"padding:4px 10px; min-width:110px; border-radius:8px; font-size:13px; margin-right:12px; {norm_style}")
                    
                    # Ensure bold
                    stat_font = status_badge.font()
                    stat_font.setWeight(QFont.DemiBold)
                    status_badge.setFont(stat_font)
                    
                    old_widget = self.jobs_table.cellWidget(row, 7)
                    if old_widget:
                        old_widget.deleteLater()
                    self.jobs_table.setCellWidget(row, 7, status_badge)
                    
                    if new_status.lower() == 'failed':
                        job_id_item.setForeground(Qt.red)
                    elif new_status.lower() == 'cancelled':
                        job_id_item.setForeground(QColor("#374151"))
                    else:
                        job_id_item.setForeground(Qt.black)
                    
                    # Disable checkbox for completed jobs
                    checkbox_widget = self.jobs_table.cellWidget(row, 0)
                    if checkbox_widget and isinstance(checkbox_widget, QCheckBox):
                        if new_status.lower() == 'completed':
                            checkbox_widget.setEnabled(False)
                            checkbox_widget.setChecked(False)
                            self.selected_job_ids.discard(job_id)
                        else:
                            checkbox_widget.setEnabled(True)
                    break
            
            # Update last refresh time locally
            if hasattr(self, 'last_refresh_label'):
                self.last_refresh_label.setText(f"Last refresh: {datetime.now().strftime('%I:%M:%S %p')}")
                
            # 3. Synchronize with active popup (New sequential queue bridge)
            # This ensures that if a popup is open for this job, it reflects 
            # the status change (e.g. showing the PICKUP button) immediately.
            if hasattr(self, '_active_job_popups'):
                for popup in self._active_job_popups:
                    try:
                        if self._is_alive(popup) and hasattr(popup, 'job') and popup.job.job_id == job_id:
                            if hasattr(popup, 'update_status'):
                                popup.update_status(new_status)
                    except Exception as e:
                        logger.error(f"Error bridging status to popup: {e}")

            logger.info(f"Successfully updated UI for job {job_id[:8]} -> {new_status}")

            # 4. DB write — runs on main thread (same session as on_job_completed/on_job_failed)
            # This is the ONLY place report_job_status updates the DB, avoiding the
            # race condition where a background-thread SessionLocal() and main-thread
            # self.db wrote to the same PrintJob row concurrently.
            try:
                job_in_db = self.db.query(PrintJob).filter(PrintJob.job_id == job_id).first()
                if job_in_db:
                    job_in_db.status = new_status
                    if new_status == 'Completed':
                        job_in_db.completed_at = datetime.utcnow()
                    elif new_status == 'Failed':
                        job_in_db.error_message = details or ''
                    self.db.commit()
                    logger.debug(f"DB updated for job {job_id[:8]} -> {new_status} (main thread)")
            except Exception as db_err:
                self.db.rollback()
                logger.error(f"Failed to update job status in DB (main thread): {db_err}")
            
        except Exception as e:
            logger.error(f"Error updating job status in UI: {e}")
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("EzPrint Dashboard")
        self.setGeometry(100, 100, 1400, 900)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout with sidebar on the left
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Sidebar - proportional width (~20% of window)
        self.create_sidebar()
        main_layout.addWidget(self.sidebar, 1)  # Stretch factor 1 for ~20% width

        # Content area - takes remaining space (~80% of window)
        content_container = QFrame()
        content_container.setStyleSheet("background-color: #f7fafc;")
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_stack = QTabWidget()
        self.content_stack.tabBar().setVisible(False)
        content_layout.addWidget(self.content_stack)
        main_layout.addWidget(content_container, 4)  # Stretch factor 4 for ~80% width
        
        # Create pages
        self.page_id_order = []
        def add_page(creator, pid, title):
            creator()
            self.page_id_order.append(pid)
        add_page(self.create_dashboard_page, "dashboard", "Dashboard")
        add_page(self.create_print_jobs_page, "print_jobs", "Print Jobs")
        add_page(self.create_pricing_page, "pricing", "Set Pricing")
        add_page(self.create_payments_page, "payments", "Payments")
        add_page(self.create_qr_page, "shop_qr", "Shop QR")
        add_page(self.create_profile_page, "profile", "Profile")
        add_page(self.create_settings_page, "settings", "Settings")
        add_page(self.create_connect_printers_page, "connect_printers", "Connect Printers")
        
        # Set initial page
        self.show_page("dashboard")
    
    def create_sidebar(self):
        """Create left sidebar navigation"""
        self.sidebar = QFrame()
        self.sidebar.setFrameStyle(QFrame.NoFrame)
        # Use size policy for proportional width instead of fixed width
        self.sidebar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.sidebar.setMinimumWidth(200)  # Minimum width constraint
        self.sidebar.setMaximumWidth(300)  # Maximum width constraint
        self.sidebar.setStyleSheet("""
            QFrame { 
                background-color: #1e293b; 
                border: none;
            }
            QPushButton { 
                text-align: left; 
                padding: 12px 16px; 
                border: none; 
                border-radius: 8px; 
                color: #cbd5e1; 
                font-weight: 500;
                font-size: 14pt;
                font-family: 'Segoe UI', sans-serif;
                spacing: 12px;
            }
            QPushButton:hover { 
                background-color: #334155; 
                color: #ffffff;
                font-size: 14pt;
            }
            QPushButton:checked { 
                background-color: #3b82f6; 
                color: #ffffff; 
                font-size: 14pt;
                font-weight: 600;
            }
            QLabel#brand { 
                color: #ffffff; 
                font-weight: 700;
                font-size: 18px;
                font-family: 'Segoe UI', sans-serif;
                letter-spacing: 0.5px;
            }
            QLabel#muted { 
                color: #94a3b8; 
                font-family: 'Segoe UI', sans-serif;
            }
        """)

        layout = QVBoxLayout(self.sidebar)
        # Equal top and bottom margins around logo for vertical centering
        layout.setContentsMargins(16, 16, 16, 24)
        layout.setSpacing(6)

        # Logo image at the top of the sidebar (replaces brand container)
        logo_path = r"C:\Users\Asus\Desktop\success_MVP_7\Screenshot 2025-12-19 094645.png"
        
        logo_label = QLabel()
        if os.path.exists(logo_path):
            logo_pixmap = QPixmap(logo_path)
            if not logo_pixmap.isNull():
                # Scale logo to fit sidebar width while maintaining aspect ratio
                # Maximum width: sidebar width minus padding (200-300px range, use 250px as target)
                max_logo_width = 250
                if logo_pixmap.width() > max_logo_width:
                    logo_pixmap = logo_pixmap.scaled(max_logo_width, max_logo_width, 
                                                     Qt.KeepAspectRatio, Qt.SmoothTransformation)
                logo_label.setPixmap(logo_pixmap)
                logo_label.setAlignment(Qt.AlignCenter)
                logo_label.setStyleSheet("padding: 12px 0px; border: none; background: transparent;")
        
        layout.addWidget(logo_label)
        # Equal spacing below logo to match top margin for visual balance
        layout.addSpacing(16)

        self.nav_buttons = {}
        # Create font matching "Daily Print Jobs Performance" heading (14pt)
        sidebar_font = QFont("Segoe UI", 14)
        nav_items = [
            ("dashboard", "Dashboard"),
            ("print_jobs", "Print Jobs"),
            ("pricing", "Set Pricing"),
            ("payments", "Payments"),
            ("shop_qr", "Shop QR"),
            ("settings", "Settings"),
        ]
        for pid, label in nav_items:
            btn = QPushButton(label)
            # Text-only buttons - no icons for clean professional look
            btn.setCheckable(True)
            btn.setFont(sidebar_font)  # Apply font size matching heading
            btn.clicked.connect(lambda checked, p=pid: self.show_page(p))
            layout.addWidget(btn)
            self.nav_buttons[pid] = btn
        
        layout.addSpacing(8)
        
        # Connect Printers button (now opens as page)
        connect_printers_btn = QPushButton("Connect Printers")
        # Text-only button - no icon
        connect_printers_btn.setCheckable(True)  # Made checkable to show active state
        connect_printers_btn.setFont(sidebar_font)  # Apply font size matching heading
        connect_printers_btn.clicked.connect(lambda checked, p="connect_printers": self.show_page(p))
        layout.addWidget(connect_printers_btn)
        self.nav_buttons["connect_printers"] = connect_printers_btn

        layout.addStretch()

        # Bottom-corner Profile section with avatar and shop name
        profile_container = QWidget()
        profile_container._is_checked = False
        
        def set_checked_profile(checked):
            """Update visual state when profile is active/inactive"""
            profile_container._is_checked = checked
            if checked:
                profile_container.setStyleSheet("""
                    QWidget {
                        background-color: #3b82f6;
                        border-radius: 8px;
                        border: none;
                    }
                    QWidget:hover {
                        background-color: #2563eb;
                        border-radius: 8px;
                        border: none;
                    }
                """)
            else:
                profile_container.setStyleSheet("""
                    QWidget {
                        background-color: transparent;
                        border: none;
                    }
                    QWidget:hover {
                        background-color: #334155;
                        border-radius: 8px;
                        border: none;
                    }
                """)
        
        profile_container.setChecked = set_checked_profile
        set_checked_profile(False)  # Initialize as unchecked
        
        profile_layout = QHBoxLayout(profile_container)
        profile_layout.setContentsMargins(12, 12, 12, 12)
        profile_layout.setSpacing(12)
        
        # Generate initials from shop name (first letter of each word, max 2 chars)
        shop_name = self.shopkeeper_data.get('shop_name', 'Shop')
        words = shop_name.split()
        if len(words) >= 2:
            initials = (words[0][0] + words[1][0]).upper()
        elif len(words) == 1 and len(words[0]) >= 2:
            initials = words[0][:2].upper()
        else:
            initials = shop_name[:2].upper() if len(shop_name) >= 2 else shop_name.upper()
        
        # Circular avatar with initials
        avatar_label = QLabel(initials)
        avatar_label.setFixedSize(40, 40)
        avatar_label.setAlignment(Qt.AlignCenter)
        avatar_label.setStyleSheet("""
            QLabel {
                background-color: #475569;
                color: #ffffff;
                border-radius: 20px;
                font-weight: 700;
                font-size: 14px;
                font-family: 'Segoe UI', sans-serif;
            }
        """)
        profile_layout.addWidget(avatar_label)
        
        # Shop name text
        shop_name_label = QLabel(shop_name)
        shop_name_label.setFont(sidebar_font)  # Apply font size matching sidebar section texts
        shop_name_label.setStyleSheet("""
            QLabel {
                color: #cbd5e1;
                font-weight: 500;
                font-size: 14pt;
                font-family: 'Segoe UI', sans-serif;
            }
        """)
        profile_layout.addWidget(shop_name_label)
        profile_layout.addStretch()
        
        # Make the container clickable
        profile_container.mousePressEvent = lambda event: self.show_page("profile")
        profile_container.setCursor(Qt.PointingHandCursor)
        
        layout.addWidget(profile_container)
        self.nav_buttons["profile"] = profile_container
    
    def show_page(self, page_id):
        """Show specific page and update navigation"""
        # Stop auto-refresh timers when leaving active pages
        if hasattr(self, 'current_page'):
            if self.current_page == "connect_printers" and hasattr(self, 'connect_printers_auto_refresh_timer'):
                self.connect_printers_auto_refresh_timer.stop()
                # Restore background discovery to slow refresh (30s)
                try:
                    self.printer_manager.thread_safe_discovery.update_discovery_interval(30)
                except Exception as e:
                    logger.debug(f"Could not restore discovery interval: {e}")
            elif self.current_page == "payments" and hasattr(self, 'payments_refresh_timer'):
                self.payments_refresh_timer.stop()
        
        self.current_page = page_id
        try:
            index = ["dashboard", "print_jobs", "pricing", "payments", "shop_qr", "profile", "settings", "connect_printers"].index(page_id)
            self.content_stack.setCurrentIndex(index)
        except ValueError:
            return
        
        # Update navigation buttons
        for btn_id, btn in self.nav_buttons.items():
            btn.setChecked(btn_id == page_id)
        
        # Start auto-refresh timers when entering specific pages
        if page_id == "connect_printers":
            if hasattr(self, 'connect_printers_auto_refresh_timer'):
                # Boost both discovery and UI refresh for near-realtime updates (Objective 1 & 3)
                self.connect_printers_auto_refresh_timer.start(2000)  # Refresh every 2 seconds
                try:
                    # Set background discovery to fast refresh (2s) only when page is open
                    self.printer_manager.thread_safe_discovery.update_discovery_interval(2)
                except Exception as e:
                    logger.debug(f"Could not boost discovery interval: {e}")
        elif page_id == "payments":
            if hasattr(self, 'payments_refresh_timer'):
                self.payments_refresh_timer.start(15000)  # Refresh every 15 seconds
        
        # Refresh dashboard data when navigating to it
        if page_id == "dashboard":
            self.update_dashboard_kpis()
    
    @safe_ui_action("SHOW_CONNECT_PRINTERS_DIALOG")
    def show_connect_printers_dialog(self, *args, **kwargs):
        """Show Connect Printers page (now a regular page, not a dialog)
        
        Args:
            *args: Additional positional arguments (ignored for compatibility)
            **kwargs: Additional keyword arguments (ignored for compatibility)
        """
        try:
            # Simply show the page using the standard page navigation
            self.show_page("connect_printers")
        except Exception as e:
            logger.error(f"Error showing connect printers dialog: {e}")
            QMessageBox.warning(self, "Error", f"Failed to open printer dialog: {str(e)}")
            # Uncheck button on error
            if "connect_printers" in self.nav_buttons:
                self.nav_buttons["connect_printers"].setChecked(False)
    
    def create_dashboard_page(self):
        """Create dashboard overview page styled like the provided design"""
        page = QWidget()
        # Main Scroll Area for Dashboard
        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.NoFrame)
        page_scroll.setStyleSheet("background-color: transparent;")
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Header title with status indicators
        header_row = QHBoxLayout()
        title = QLabel("Dashboard")
        title.setFont(QFont("Segoe UI", 24, QFont.Bold))
        title.setStyleSheet("color: #111827;")
        header_row.addWidget(title)
        header_row.addStretch()
        
        # Manual Refresh Button (matching Print Jobs style)
        self.dash_refresh_btn = QPushButton("Refresh")
        self.dash_refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #374151;
                border: 1px solid #d1d5db;
                padding: 8px 16px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 13px;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #f9fafb;
                border-color: #9ca3af;
            }
            QPushButton:pressed {
                background-color: #f3f4f6;
            }
        """)
        self.dash_refresh_btn.clicked.connect(lambda: self.update_dashboard_kpis())
        header_row.addWidget(self.dash_refresh_btn)
        
        layout.addLayout(header_row)

        # Stats cards row
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)

        def _stat_card(title_text, primary_text, meta_text, accent="#2196F3", primary_label_ref=None):
            card = QFrame()
            card.setFrameStyle(QFrame.StyledPanel)
            # Enhanced card styling with shadow effect and modern design
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: #ffffff;
                    border: 1px solid #e5e7eb;
                    border-radius: 12px;
                }}
            """)
            # Add shadow effect using QGraphicsDropShadowEffect
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(8)
            shadow.setXOffset(0)
            shadow.setYOffset(2)
            shadow.setColor(QColor(0, 0, 0, 30))  # Subtle shadow
            card.setGraphicsEffect(shadow)
            
            v = QVBoxLayout(card)
            v.setContentsMargins(20, 16, 20, 16)
            v.setSpacing(8)

            t = QLabel(title_text)
            t.setStyleSheet("color:#6b7280; font-size:13px; font-family: 'Segoe UI', sans-serif; font-weight: 500;")
            v.addWidget(t)

            p = QLabel(primary_text)
            p.setFont(QFont("Segoe UI", 28, QFont.Bold))
            p.setStyleSheet("color:#111827; margin-top: 4px; font-family: 'Segoe UI', sans-serif;")
            v.addWidget(p)
            
            # Store reference if provided
            if primary_label_ref is not None:
                primary_label_ref.append(p)

            m = QLabel(meta_text)
            m.setStyleSheet(f"color:{accent}; font-size:12px; font-family: 'Segoe UI', sans-serif; margin-top: 4px; font-weight: 500;")
            v.addWidget(m)

            return card

        # Store references to KPI card labels for realtime updates
        self.kpi_total_jobs_label = []
        self.kpi_today_revenue_label = []
        self.kpi_monthly_revenue_label = []
        self.kpi_pending_jobs_label = []
        self.kpi_printing_jobs_label = []
        self.kpi_completed_jobs_label = []
        
        cards_row.addWidget(_stat_card("Total Print Jobs", "0", "All time jobs", accent="#10B981", primary_label_ref=self.kpi_total_jobs_label))
        cards_row.addWidget(_stat_card("Today's Revenue", "₹ 0", "Today's earnings", accent="#3B82F6", primary_label_ref=self.kpi_today_revenue_label))
        cards_row.addWidget(_stat_card("Monthly Revenue", "₹ 0", "This month", accent="#EF4444", primary_label_ref=self.kpi_monthly_revenue_label))

        layout.addLayout(cards_row)
        
        # New KPI tickets row (top row: 3 tickets)
        kpi_status_row1 = QHBoxLayout()
        kpi_status_row1.setSpacing(16)
        
        completed_card = _stat_card("Completed Jobs", "0", "Successfully finished", accent="#10B981", primary_label_ref=self.kpi_completed_jobs_label)
        completed_card.setToolTip("Number of print jobs successfully completed")
        kpi_status_row1.addWidget(completed_card)
        
        pending_card = _stat_card("Pending Jobs", "0", "Waiting to be printed", accent="#F59E0B", primary_label_ref=self.kpi_pending_jobs_label)
        pending_card.setToolTip("Number of print jobs waiting in queue")
        kpi_status_row1.addWidget(pending_card)
        
        printing_card = _stat_card("Printing Jobs", "0", "Currently being printed", accent="#3B82F6", primary_label_ref=self.kpi_printing_jobs_label)
        printing_card.setToolTip("Number of print jobs currently printing")
        kpi_status_row1.addWidget(printing_card)
        
        layout.addLayout(kpi_status_row1)
        
        # Recent Jobs Section wrapper (Styled as a Card)
        self.recent_jobs_wrapper = QFrame()
        self.recent_jobs_wrapper.setFrameStyle(QFrame.StyledPanel)
        self.recent_jobs_wrapper.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
            }
        """)
        # Add shadow effect to match KPI cards
        recent_jobs_shadow = QGraphicsDropShadowEffect()
        recent_jobs_shadow.setBlurRadius(8)
        recent_jobs_shadow.setXOffset(0)
        recent_jobs_shadow.setYOffset(2)
        recent_jobs_shadow.setColor(QColor(0, 0, 0, 30))
        self.recent_jobs_wrapper.setGraphicsEffect(recent_jobs_shadow)

        recent_jobs_layout = QVBoxLayout(self.recent_jobs_wrapper)
        recent_jobs_layout.setContentsMargins(16, 16, 16, 16)
        recent_jobs_layout.setSpacing(12)

        recent_jobs_title = QLabel("Recent Jobs")
        recent_jobs_title.setFont(QFont("Segoe UI", 14, QFont.Bold))  # 18px is approx 14pt
        recent_jobs_title.setStyleSheet("color: #111827; margin-bottom: 4px; background: transparent; border: none; font-size: 18px;")
        recent_jobs_layout.addWidget(recent_jobs_title)

        # Recent Jobs Table Header
        recent_header_card = QFrame()
        recent_header_card.setStyleSheet("""
            QFrame {
                background-color: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 12px 20px;
            }
        """)
        recent_h_layout = QHBoxLayout(recent_header_card)
        recent_h_layout.setContentsMargins(0, 0, 0, 0)
        recent_h_layout.setSpacing(12)

        h1 = QLabel("Job ID")
        h1.setFont(QFont("Segoe UI", 12, QFont.Bold))
        h1.setStyleSheet("color: #111827;")
        h1.setMinimumWidth(85)
        h1.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        recent_h_layout.addWidget(h1, 0)

        h2 = QLabel("File Name")
        h2.setFont(QFont("Segoe UI", 12, QFont.Bold))
        h2.setStyleSheet("color: #111827;")
        recent_h_layout.addWidget(h2, 5)

        h3 = QLabel("Amount")
        h3.setFont(QFont("Segoe UI", 12, QFont.Bold))
        h3.setStyleSheet("color: #111827;")
        h3.setMinimumWidth(145)
        recent_h_layout.addWidget(h3, 0)

        h4 = QLabel("Status")
        h4.setFont(QFont("Segoe UI", 12, QFont.Bold))
        h4.setStyleSheet("color: #111827;")
        h4.setMinimumWidth(110)
        recent_h_layout.addWidget(h4, 0)

        recent_jobs_layout.addWidget(recent_header_card)

        # Container for job rows
        self.recent_jobs_container = QWidget()
        self.recent_jobs_layout = QVBoxLayout(self.recent_jobs_container)
        self.recent_jobs_layout.setContentsMargins(0, 8, 0, 0)
        self.recent_jobs_layout.setSpacing(8)
        recent_jobs_layout.addWidget(self.recent_jobs_container)
        
        layout.addWidget(self.recent_jobs_wrapper)
        
        # Initialize KPI cards with realtime data (after cards are created)
        self.update_dashboard_kpis()

        # Initialize printer connection state (popup check will happen in showEvent after window is visible)
        active_printers = self.printer_manager.get_active_printers(self.shopkeeper_data['shop_id'])
        self.previous_printer_connected = len(active_printers) > 0
        
        # Update printer status (will show popup on future disconnections)
        self.update_printer_connectivity_status()

        layout.addStretch()

        page_scroll.setWidget(scroll_content)
        main_vbox = QVBoxLayout(page)
        main_vbox.setContentsMargins(0, 0, 0, 0)
        main_vbox.addWidget(page_scroll)

        self.content_stack.addTab(page, "Dashboard")
    
    def on_kpi_data_ready(self, data):
        """Slot to handle ready KPI data from background worker"""
        try:
            if "error" in data:
                logger.error(f"Error in background KPI loading: {data['error']}")
                return

            logger.info("Updating Dashboard UI with background KPI data")
            
            # 1. Update KPI labels
            kpis = data.get("kpis", {})
            labels_map = {
                'kpi_total_jobs_label': kpis.get('total', '0'),
                'kpi_today_revenue_label': kpis.get('today', '₹ 0.00'),
                'kpi_monthly_revenue_label': kpis.get('monthly', '₹ 0.00'),
                'kpi_pending_jobs_label': kpis.get('pending', '0'),
                'kpi_printing_jobs_label': kpis.get('printing', '0'),
                'kpi_completed_jobs_label': kpis.get('completed', '0'),
                'kpi_failed_jobs_label': kpis.get('failed', '0')
            }
            
            for attr, text in labels_map.items():
                if hasattr(self, attr) and getattr(self, attr):
                    getattr(self, attr)[0].setText(text)

            # 2. Update Recent Jobs list
            recent_jobs = data.get("recent_jobs", [])
            self.update_recent_jobs_list(recent_jobs)

            # 3. Update Revenue Chart
            analytics_data = data.get("analytics_data", {})
            if analytics_data and hasattr(self, 'revenue_chart'):
                self.revenue_chart.set_data(
                    analytics_data.get("values", []), 
                    analytics_data.get("labels", [])
                )
                if hasattr(self, 'analytics_subtitle'):
                    self.analytics_subtitle.setText(analytics_data.get("selected_month_str", ""))

            logger.info("Dashboard UI update from background worker complete")
        except Exception as e:
            logger.error(f"Error updating UI from KPI data: {e}")

    def update_dashboard_kpis(self, all_jobs=None):
        """Update Dashboard KPI cards using background worker (OFF UI thread)"""
        try:
            # Guard: skip if previous worker still running
            if hasattr(self, 'kpi_worker') and self.kpi_worker is not None:
                try:
                    if self.kpi_worker.isRunning():
                        logger.info("KPI refresh already in progress, skipping...")
                        return
                except RuntimeError:
                    # Qt C++ object deleted — reset safely
                    self.kpi_worker = None

            # Prepare data for worker
            shop_id = self.shopkeeper_data.get('shop_id')
            token = getattr(self, 'session_token', None)
            selected_month = self.month_selector.currentText() if hasattr(self, 'month_selector') else datetime.now().strftime("%B %Y")

            # Initialize and start worker
            self.kpi_worker = DashboardKPIWorker(shop_id, token, selected_month)
            self.kpi_worker.kpi_data_ready.connect(self.on_kpi_data_ready)
            self.kpi_worker.start()
            
            logger.info("Started background Dashboard KPI update worker")
                
        except Exception as e:
            logger.error(f"Error initiating dashboard KPI worker: {e}")

    def _unused_old_update_dashboard_kpis(self, all_jobs=None):
        """Update Dashboard KPI cards with data from API (with DB fallback)"""
        try:
            logger.info("=== Starting Dashboard KPI Update ===")
            
            # Phase 3: Try to fetch data from API first
            api_success = False
            if all_jobs is None:
                shop_id = self.shopkeeper_data.get('shop_id')
                success, api_data, error = self.api_client.get_dashboard(shop_id)
                
                if success and api_data:
                    logger.info("Dashboard data fetched successfully from API")
                    kpis = api_data.get('kpis', {})
                    jobs_list = api_data.get('jobs', [])
                    
                    # Log API usage
                    logger.info("Using API data for Dashboard KPIs")
                    
                    # Map API KPIs to UI
                    kpi_total = str(kpis.get('total_jobs', 0))
                    kpi_today = f"₹ {kpis.get('total_revenue', 0.0):.2f}"
                    kpi_monthly = f"₹ {kpis.get('total_revenue', 0.0):.2f}" # API returns total for period, using for both is okay for now
                    kpi_pending = str(kpis.get('pending_jobs', 0))
                    kpi_printing = str(kpis.get('printing_jobs', 0))
                    kpi_completed = str(kpis.get('completed_jobs', 0))
                    kpi_failed = str(kpis.get('failed_jobs', 0))
                    
                    # Convert API jobs to objects for recent list
                    all_jobs = [self._api_job_to_obj(j) for j in jobs_list]
                    api_success = True
                else:
                    logger.warning(f"API Dashboard fetch failed, falling back to database: {error}")
            
            # Database Fallback (if API failed or all_jobs not provided)
            if not api_success:
                logger.info("Using Database for Dashboard KPIs (Fallback)")
                if all_jobs is None:
                    db = SessionLocal()
                    try:
                        all_jobs = db.query(PrintJob).filter(
                            PrintJob.shop_id == self.shopkeeper_data['shop_id']
                        ).all()
                    finally:
                        db.close()
                
                # Original logic for DB-based KPI calculation
                total_jobs = len(all_jobs)
                pending_statuses = {"pending", "in queue", "processing", "printing started"}
                printing_statuses = {"printing", "printing started"}
                
                pending_count = sum(1 for job in all_jobs if (job.status or "").strip().lower() in pending_statuses)
                printing_count = sum(1 for job in all_jobs if (job.status or "").strip().lower() in printing_statuses)
                completed_count = sum(1 for job in all_jobs if (job.status or "").strip().lower() == "completed")
                failed_count = sum(1 for job in all_jobs if (job.status or "").strip().lower() == "failed")
                
                now = datetime.now()
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=1)
                
                today_revenue = sum(job.amount or 0 for job in all_jobs 
                                  if job.created_at and job.created_at >= today_start)
                monthly_revenue = sum(job.amount or 0 for job in all_jobs 
                                    if job.created_at and job.created_at >= month_start)
                
                kpi_total = str(total_jobs)
                kpi_today = f"₹ {today_revenue:.2f}"
                kpi_monthly = f"₹ {monthly_revenue:.2f}"
                kpi_pending = str(pending_count)
                kpi_printing = str(printing_count)
                kpi_completed = str(completed_count)
                kpi_failed = str(failed_count)

            # Update Recent Jobs list (can handle both DB objects and API-converted objects)
            if not getattr(self, "_is_initializing", False):
                self.update_recent_jobs_list(all_jobs)
            
            # Update KPI labels safely
            labels_map = {
                'kpi_total_jobs_label': kpi_total,
                'kpi_today_revenue_label': kpi_today,
                'kpi_monthly_revenue_label': kpi_monthly,
                'kpi_pending_jobs_label': kpi_pending,
                'kpi_printing_jobs_label': kpi_printing,
                'kpi_completed_jobs_label': kpi_completed,
                'kpi_failed_jobs_label': kpi_failed
            }
            
            for attr, text in labels_map.items():
                if hasattr(self, attr) and getattr(self, attr):
                    getattr(self, attr)[0].setText(text)
            
            if hasattr(self, 'revenue_chart'):
                self.update_revenue_analytics()
                
            logger.info("=== Dashboard KPI Update Complete ===")
                
        except Exception as e:
            logger.error(f"Error updating dashboard KPIs: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    def update_recent_jobs_list(self, jobs):
        """Update the Recent Jobs list on the dashboard with latest 5 jobs"""
        try:
            print(f"DEBUG: update_recent_jobs_list called with {len(jobs) if jobs else 0} jobs")
            if not hasattr(self, 'recent_jobs_layout'):
                print("DEBUG: recent_jobs_layout not found")
                return
                
            # Clear existing rows
            while self.recent_jobs_layout.count():
                item = self.recent_jobs_layout.takeAt(0)
                if item:
                    w = item.widget()
                    if w:
                        w.setParent(None)   # immediate detach from UI
                        w.hide()           # ensure not visible
                        w.deleteLater()    # cleanup later
            
            if not jobs:
                print("DEBUG: No jobs to display in recent list")
                return

            # Take only top 4 jobs
            recent_jobs = sorted(jobs, key=lambda x: x.created_at or datetime.min, reverse=True)[:4]
            print(f"DEBUG: Adding {len(recent_jobs)} rows to Dashboard")
            
            for job in recent_jobs:
                row_card = QFrame()
                row_card.setAttribute(Qt.WA_TransparentForMouseEvents)
                row_layout = QHBoxLayout(row_card)
                row_card.setLayout(row_layout)
                row_card.setStyleSheet("""
                    QFrame {
                        background-color: #ffffff;
                        border: 1px solid #e5e7eb;
                        border-radius: 8px;
                        padding: 12px 20px;
                    }
                """)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(12)
                
                # Column 1: Job ID (11px, Bold)
                jid_text = (job.job_id or "")[:8]
                jid = QLabel(jid_text)
                jid.setFont(QFont("Segoe UI", 11, QFont.Bold))
                jid.setStyleSheet("color: #374151;")
                jid.setMinimumWidth(85)
                jid.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
                jid.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                jid.setAttribute(Qt.WA_TransparentForMouseEvents)
                row_layout.addWidget(jid, 0)
                
                # Column 2: File Name (11px, Normal)
                fname_text = self._format_job_display_name(job)
                fname = QLabel(fname_text)
                fname.setStyleSheet("color: #374151; font-size: 11px;")
                fname.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                fname.setTextFormat(Qt.PlainText)
                fname.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                fname.setAttribute(Qt.WA_TransparentForMouseEvents)
                row_layout.addWidget(fname, 5)
                
                # Column 3: Amount (11px, Bold)
                amount_val = job.amount or 0.0
                amt = QLabel(f"₹ {amount_val:.2f}")
                amt.setFont(QFont("Segoe UI", 11, QFont.Bold))
                amt.setStyleSheet("color: #0369a1;")
                amt.setMinimumWidth(145)
                amt.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                amt.setAttribute(Qt.WA_TransparentForMouseEvents)
                row_layout.addWidget(amt, 0)
                
                # Column 4: Status (Chip - reuse exact stylesheet)
                status = job.status or 'Pending'
                if status.lower() == 'completed':
                    status_bg = "#dcfce7"
                    status_color = "#15803d"
                    status_text = "Completed"
                elif status.lower() == 'failed':
                    status_bg = "#fee2e2"
                    status_color = "#dc2626"
                    status_text = "Failed"
                elif status.lower() in ['printing', 'printing started']:
                    status_bg = "#dbeafe"
                    status_color = "#1e40af"
                    status_text = "Printing"
                elif status.lower() == 'cancelled':
                    status_bg = "#f3f4f6"
                    status_color = "#374151"
                    status_text = "Cancelled"
                else:
                    status_bg = "#fef3c7"
                    status_color = "#d97706"
                    status_text = "Pending"
                
                status_chip = QLabel(status_text)
                status_chip.setAlignment(Qt.AlignCenter)
                status_chip.setMinimumWidth(110)
                status_chip.setMaximumWidth(110)
                status_chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
                status_chip.setStyleSheet(f"background-color: {status_bg}; color: {status_color}; border-radius: 4px; padding: 2px 8px; font-weight: 600; font-size: 11px;")
                # Explicitly set font weight to DemiBold (600) to ensure it renders bold
                chip_font = status_chip.font()
                chip_font.setWeight(QFont.DemiBold)
                status_chip.setFont(chip_font)
                status_chip.setAttribute(Qt.WA_TransparentForMouseEvents)
                row_layout.addWidget(status_chip, 0)
                
                self.recent_jobs_layout.addWidget(row_card)
            
            print("DEBUG: update_recent_jobs_list completion")
        except Exception as e:
            logger.error(f"Error updating recent jobs list: {e}")
            print(f"DEBUG: update_recent_jobs_list ERROR: {e}")
                
        except Exception as e:
            logger.error(f"Error updating recent jobs list: {e}")

    def lazy_load_analytics(self, parent_layout):
        """Safely initialize analytics after dashboard load"""
        try:
            # Verify layout is still valid (user might have closed app)
            if sip.isdeleted(parent_layout):
                return
                
            self.create_analytics_section(parent_layout)
            # Trigger initial data update
            self.update_revenue_analytics()
            
        except Exception as e:
            logger.error(f"Error in lazy analytics load: {e}")
            # Don't crash, just log

    def create_analytics_section(self, parent_layout):
        """Create the Revenue Analytics section below KPI tickets"""
        # Container Card
        analytics_card = QFrame()
        analytics_card.setObjectName("analyticsCard")
        analytics_card.setStyleSheet("""
            QFrame#analyticsCard {
                background-color: white;
                border-radius: 12px;
                border: 1px solid #e5e7eb;
            }
        """)
        
        # Shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 10))
        shadow.setOffset(0, 4)
        analytics_card.setGraphicsEffect(shadow)
        
        card_layout = QVBoxLayout(analytics_card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(16)
        
        # Header Row: Title area + Month Selector
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(10, 5, 10, 5)
        
        # Title & Subtitle block
        title_block = QVBoxLayout()
        title_block.setSpacing(4)
        
        title_label = QLabel("Revenue Overview")
        title_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title_label.setStyleSheet("color: #111827; margin: 0; padding: 0;")
        title_block.addWidget(title_label)
        
        # Dynamic Subtitle (e.g., March 2023)
        current_month_year = datetime.now().strftime("%B %Y")
        self.analytics_subtitle = QLabel(current_month_year)
        self.analytics_subtitle.setFont(QFont("Segoe UI", 12))
        self.analytics_subtitle.setStyleSheet("color: #6b7280; margin: 0; padding: 0;")
        title_block.addWidget(self.analytics_subtitle)
        
        header_layout.addLayout(title_block)
        header_layout.addStretch()
        
        # Month Selector Dropdown
        self.month_selector = QComboBox()
        self.month_selector.setFixedWidth(200)
        self.month_selector.addItem(current_month_year)
        # Add a few previous months for demonstration
        for i in range(1, 4):
            prev_date = datetime.now() - timedelta(days=30*i)
            self.month_selector.addItem(prev_date.strftime("%B %Y"))
            
        self.month_selector.setStyleSheet("""
            QComboBox {
                background-color: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                padding: 10px 15px;
                font-size: 14px;
                color: #374151;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #6b7280;
                margin-right: 15px;
            }
        """)
        self.month_selector.currentIndexChanged.connect(self.update_revenue_analytics)
        
        header_layout.addWidget(self.month_selector)
        card_layout.addLayout(header_layout)
        
        # Chart Component
        self.revenue_chart = ChartJSGraph(chart_type='revenue')
        self.revenue_chart.setMinimumHeight(350)
        card_layout.addWidget(self.revenue_chart)
        
        parent_layout.addWidget(analytics_card)
        
    def _switch_analytics_mode(self, mode):
        """Deprecated: Modal switching handled by dropdown index change"""
        pass

    def update_revenue_analytics(self):
        """No longer performs calculations directly. Calls update_dashboard_kpis to trigger background refresh."""
        if hasattr(self, 'revenue_chart'):
            # Just trigger a refresh of everything. 
            # The background worker handles both KPIs and analytics now.
            self.update_dashboard_kpis()


    def create_inventory_page(self):
        """Inventory page for paper/ink stocks"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Inventory")
        title.setFont(QFont("Segoe UI", 24, QFont.Bold))
        title.setStyleSheet("color: #111827;")
        layout.addWidget(title)
        info = QLabel("Track paper stock, ink levels, and supplies. (Coming soon)")
        info.setStyleSheet("color:#6b7280; font-family: 'Segoe UI', sans-serif; font-size: 14px;")
        layout.addWidget(info)
        layout.addStretch()
        self.content_stack.addTab(page, "Inventory")

    def create_payments_page(self):
        """Payments page showing completed print jobs"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Header
        header_row = QHBoxLayout()
        title = QLabel("Payments")
        title.setFont(QFont("Segoe UI", 24, QFont.Bold))
        title.setStyleSheet("color: #111827;")
        header_row.addWidget(title)
        header_row.addStretch()
        
        # Manual Refresh Button (matching Print Jobs style)
        self.pay_refresh_btn = QPushButton("Refresh")
        self.pay_refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #374151;
                border: 1px solid #d1d5db;
                padding: 8px 16px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 13px;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #f9fafb;
                border-color: #9ca3af;
            }
            QPushButton:pressed {
                background-color: #f3f4f6;
            }
        """)
        self.pay_refresh_btn.clicked.connect(self.manual_refresh_payments)
        header_row.addWidget(self.pay_refresh_btn)
        
        layout.addLayout(header_row)
        
        # Search & Filters Card (exact match to Print Jobs)
        filters_card = QFrame()
        filters_card.setStyleSheet("""
            QFrame { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px; }
            QLineEdit { padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 6px; }
            QComboBox { padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 6px; }
        """)
        filters_layout = QHBoxLayout(filters_card)
        filters_layout.setContentsMargins(12, 12, 12, 12)
        filters_layout.setSpacing(12)

        # Search bar matching Print Jobs styling
        self.payments_search = QLineEdit()
        self.payments_search.setPlaceholderText("Search payments...")
        self.payments_search.textChanged.connect(self.load_payments_data)
        self.payments_search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.payments_search.setObjectName("paymentsSearch")
        self.payments_search.setStyleSheet("""
            QLineEdit#paymentsSearch {
                background: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 12px;
                padding-left: 36px;
                padding-right: 12px;
                padding-top: 10px;
                padding-bottom: 10px;
                color: #1F2937;
            }
            QLineEdit#paymentsSearch:focus {
                border: 1px solid #93C5FD;
                background: #FFFFFF;
            }
            QLineEdit#paymentsSearch::placeholder { color: #6B7280; }
        """)
        
        # Magnifier icon overlay
        try:
            search_icon = QLabel(self.payments_search)
            search_icon.setText("⌕")
            search_icon.setStyleSheet("color:#6B7280; font-size:14px;")
            search_icon.setFixedSize(20, 20)
            def _reposition_pay_icon():
                search_icon.move(10, int((self.payments_search.height() - 20) / 2))
            self.payments_search.resizeEvent = lambda ev: (_reposition_pay_icon(), QLineEdit.resizeEvent(self.payments_search, ev))[1]
            _reposition_pay_icon()
        except Exception: pass
        
        filters_layout.addWidget(self.payments_search, 1)

        # Date filter dropdown (ONE only as requested)
        self.pay_date_filter = QComboBox()
        self.pay_date_filter.addItems(["All", "Today", "Yesterday", "This Week", "This Month"])
        self.pay_date_filter.currentIndexChanged.connect(self.load_payments_data)
        self.pay_date_filter.setMinimumWidth(150)
        filters_layout.addWidget(self.pay_date_filter, 0)

        layout.addWidget(filters_card)
        
        subtitle = QLabel("Payment history for completed print jobs")
        subtitle.setStyleSheet("color:#6b7280; font-family: 'Segoe UI', sans-serif; font-size: 14px; margin-bottom: 10px;")
        layout.addWidget(subtitle)
        
        # Column header card (matching Print Jobs header styling exactly)
        header_card = QFrame()
        header_card.setFrameStyle(QFrame.StyledPanel)
        header_card.setStyleSheet("""
            QFrame {
                background-color: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 12px 20px;
            }
        """)
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        
        # Header labels with same styling as Print Jobs
        # Job ID (minimum width, no stretch)
        job_id_header = QLabel("Job ID")
        job_id_header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        job_id_header.setStyleSheet("color: #111827;")
        job_id_header.setMinimumWidth(85)
        job_id_header.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        header_layout.addWidget(job_id_header, 0)
        
        # File Name (stretch factor 2)
        file_name_header = QLabel("File Name")
        file_name_header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        file_name_header.setStyleSheet("color: #111827;")
        file_name_header.setMinimumWidth(100)
        header_layout.addWidget(file_name_header, 2)
        
        # Time (minimum width, no stretch)
        time_header = QLabel("Time")
        time_header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        time_header.setStyleSheet("color: #111827;")
        time_header.setMinimumWidth(135)
        time_header.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        header_layout.addWidget(time_header, 0)
        
        # Amount (stretch factor 1)
        amount_header = QLabel("Amount")
        amount_header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        amount_header.setStyleSheet("color: #111827;")
        amount_header.setMinimumWidth(145)
        header_layout.addWidget(amount_header, 1)
        
        layout.addWidget(header_card)
        
        # Scroll area for payment records (matching Print Jobs scroll styling)
        self.payments_scroll = QScrollArea()
        self.payments_scroll.setWidgetResizable(True)
        self.payments_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #f1f5f9;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #cbd5e1;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #94a3b8;
            }
        """)
        
        self.payments_widget = QWidget()
        self.payments_layout = QVBoxLayout(self.payments_widget)
        self.payments_layout.setContentsMargins(0, 0, 0, 0)
        self.payments_layout.setSpacing(8)
        
        self.payments_scroll.setWidget(self.payments_widget)
        self.payments_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        layout.addWidget(self.payments_scroll)
        
        self.content_stack.addTab(page, "Payments")
        
        # Setup auto-refresh timer for payments (15 seconds)
        if not hasattr(self, 'payments_refresh_timer'):
            self.payments_refresh_timer = QTimer(self)
            self.payments_refresh_timer.timeout.connect(self.load_payments_data)
            
        # Initial load payment data
        self.load_payments_data()
    
    def load_payments_data(self):
        """Load completed print jobs from database (with Search and Date Filters)"""
        try:
            # 1. FULLY clear layout (widgets AND spacers/stretches) - Root Cause Fix
            while self.payments_layout.count() > 0:
                item = self.payments_layout.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
            
            # Query database for completed jobs
            db = SessionLocal()
            try:
                completed_jobs = db.query(PrintJob).filter(
                    PrintJob.shop_id == self.shopkeeper_data['shop_id'],
                    PrintJob.status == "Completed"
                ).order_by(PrintJob.completed_at.desc()).all()
                
                # Apply Filtering Logic
                filtered_jobs = []
                
                # Get filter states
                search_term = self.payments_search.text().lower() if hasattr(self, 'payments_search') else ""
                date_filter = self.pay_date_filter.currentText() if hasattr(self, 'pay_date_filter') else "All"
                
                from datetime import datetime, timedelta
                now = datetime.now()
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                
                for job in completed_jobs:
                    # A. Search Filter (Job ID or File Name)
                    job_id_match = search_term in job.job_id.lower()
                    filename_match = search_term in (job.filename or "").lower()
                    if search_term and not (job_id_match or filename_match):
                        continue
                        
                    # B. Date Filter (using completed_at)
                    job_date = job.completed_at
                    if date_filter != "All":
                        if not job_date: continue
                        
                        # Handle naive vs aware datetime if necessary
                        if job_date.tzinfo is not None:
                            # If job_date is aware, make today_start aware too for comparison
                            # Simplified check matching Print Jobs logic
                            pass
                            
                        if date_filter == "Today":
                            if job_date < today_start: continue
                        elif date_filter == "Yesterday":
                            yesterday_start = today_start - timedelta(days=1)
                            if not (yesterday_start <= job_date < today_start): continue
                        elif date_filter == "This Week":
                            # Monday start
                            days_since_monday = today_start.weekday()
                            week_start = today_start - timedelta(days=days_since_monday)
                            if job_date < week_start: continue
                        elif date_filter == "This Month":
                            month_start = today_start.replace(day=1)
                            if job_date < month_start: continue
                    
                    filtered_jobs.append(job)

                if not filtered_jobs:
                    # Show empty state
                    empty_label = QLabel("No completed payments found matching filters" if search_term or date_filter != "All" else "No completed payments found")
                    empty_label.setAlignment(Qt.AlignCenter)
                    empty_label.setStyleSheet("color: #9ca3af; font-size: 14px; padding: 40px;")
                    self.payments_layout.addWidget(empty_label)
                else:
                    # Create payment card for each filtered job
                    for job in filtered_jobs:
                        payment_card = self.create_payment_card(job)
                        self.payments_layout.addWidget(payment_card)
                
                # 2. Add a SINGLE stretch at the end
                self.payments_layout.addStretch()
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error loading payments data: {e}")
            # Show error message
            error_label = QLabel("Error loading payment history")
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setStyleSheet("color: #ef4444; font-size: 14px; padding: 40px;")
            self.payments_layout.addWidget(error_label)
            self.payments_layout.addStretch()

    def manual_refresh_payments(self):
        """Reset filters and reload payments data"""
        if hasattr(self, 'payments_search'):
            self.payments_search.clear()
        if hasattr(self, 'pay_date_filter'):
            self.pay_date_filter.setCurrentText("All")
        self.load_payments_data()
    
    def create_payment_card(self, job):
        """Create a payment record card matching Print Jobs card styling exactly"""
        card = QFrame()
        card.setFrameStyle(QFrame.StyledPanel)
        
        # Card styling - EXACT match to Print Jobs card
        card.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 12px 20px;
            }
        """)
        
        # Main layout - horizontal row layout matching Print Jobs
        main_layout = QHBoxLayout(card)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)
        
        # Column 1: Job ID (first 8 characters, bold, matching Print Jobs)
        job_id_short = (job.job_id or "")[:8]
        job_id_value = QLabel(job_id_short)
        job_id_value.setFont(QFont("Segoe UI", 11, QFont.Bold))
        job_id_value.setStyleSheet("color: #374151;")
        job_id_value.setMinimumWidth(85)
        job_id_value.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        job_id_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        main_layout.addWidget(job_id_value, 0)
        
        # Column 2: File Name (stretch factor 2, matching Print Jobs)
        file_name = job.filename or "Unknown File"
        file_name_value = QLabel(file_name)
        file_name_value.setStyleSheet("color: #374151; font-size: 11px;")
        file_name_value.setMinimumWidth(100)
        file_name_value.setWordWrap(False)
        file_name_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        file_name_value.setTextFormat(Qt.PlainText)
        file_name_value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        main_layout.addWidget(file_name_value, 2)
        
        # Column 3: Time (matching Print Jobs format: dd MMM yyyy, hh:mm AM/PM)
        time_text = self.format_payment_time(job.completed_at)
        time_value = QLabel(time_text)
        time_value.setStyleSheet("color: #374151; font-size: 11px;")
        time_value.setMinimumWidth(135)
        time_value.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        time_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        time_value.setAttribute(Qt.WA_TransparentForMouseEvents)
        main_layout.addWidget(time_value, 0)
        
        # Column 4: Amount (BOLD, matching Print Jobs)
        amount_value_num = job.amount if job.amount is not None else 0.0
        amount_value = QLabel(f"₹ {amount_value_num:.2f}")
        amount_value.setFont(QFont("Segoe UI", 11, QFont.Bold))
        amount_value.setStyleSheet("color: #0369a1;")
        amount_value.setMinimumWidth(145)
        amount_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        amount_value.setAttribute(Qt.WA_TransparentForMouseEvents)
        main_layout.addWidget(amount_value, 1)
        
        return card
    
    def format_payment_time(self, utc_time):
        """Format UTC time to local time matching Print Jobs format"""
        try:
            if utc_time is None:
                return "N/A"
            
            # Convert UTC to local time (matching Print Jobs logic)
            if utc_time.tzinfo is None:
                utc_time = utc_time.replace(tzinfo=timezone.utc)
            
            local_time = utc_time.astimezone(None)
            
            # Format as "dd MMM yyyy, hh:mm AM/PM" (matching Print Jobs)
            return local_time.strftime("%d %b %Y, %I:%M %p")
            
        except Exception as e:
            logger.error(f"Error formatting payment time: {e}")
            return "N/A"

    def create_qr_page(self):
        """Shop QR page with shop info on left, QR code on right"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # Header
        header = QHBoxLayout()
        title = QLabel("Shop QR Code")
        title.setFont(QFont("Segoe UI", 24, QFont.Bold))
        title.setStyleSheet("color: #111827;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Main content with two sections (swapped layout)
        main_layout = QHBoxLayout()
        main_layout.setSpacing(20)

        # Left section: Shop Information (moved from right)
        details_card = QFrame()
        details_card.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        details_layout = QVBoxLayout(details_card)
        details_layout.setSpacing(15)

        # Shop details title with edit button
        title_row = QHBoxLayout()
        details_title = QLabel("Shop Information")
        details_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        details_title.setStyleSheet("color: #111827;")
        title_row.addWidget(details_title)
        title_row.addStretch()
        

        details_layout.addLayout(title_row)

        # Shop information display/edit area
        self.shop_info_widget = QWidget()
        self.shop_info_layout = QVBoxLayout(self.shop_info_widget)
        self.shop_info_layout.setSpacing(10)
        
        # Initialize shop info display
        self.setup_shop_info_display()
        details_layout.addWidget(self.shop_info_widget)


        details_layout.addStretch()

        main_layout.addWidget(details_card, 1)

        # Right section: QR Code + Shop Name + Shop ID (moved from left)
        qr_card = QFrame()
        qr_card.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        qr_layout = QVBoxLayout(qr_card)
        qr_layout.setAlignment(Qt.AlignCenter)
        qr_layout.setSpacing(15)

        # Shop name as main title (replaces "Your Shop QR Code")
        shop_name_label = QLabel(self.shopkeeper_data.get('shop_name', 'Shop Name'))
        shop_name_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
        shop_name_label.setStyleSheet("color: #111827; margin-bottom: 8px;")
        shop_name_label.setAlignment(Qt.AlignCenter)
        qr_layout.addWidget(shop_name_label)

        # QR Code subtitle
        qr_subtitle = QLabel("Scan this QR code to access your EzPrint service")
        qr_subtitle.setFont(QFont("Segoe UI", 12))
        qr_subtitle.setStyleSheet("color: #6b7280;")
        qr_subtitle.setAlignment(Qt.AlignCenter)
        qr_layout.addWidget(qr_subtitle)

        # QR Code image (larger size for better visibility)
        qr_path = self.ensure_qr_code_exists()
        if qr_path and os.path.exists(qr_path):
            qr_pix = QPixmap(qr_path).scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            qr_label = QLabel()
            qr_label.setPixmap(qr_pix)
            qr_label.setAlignment(Qt.AlignCenter)
            qr_label.setStyleSheet("border: 2px solid #e2e8f0; border-radius: 8px; padding: 10px; background: #f8fafc;")
            qr_label.setFixedSize(270, 270)  # Larger square shape for better visibility
            
            # Center the QR code container
            qr_container_layout = QHBoxLayout()
            qr_container_layout.addStretch()
            qr_container_layout.addWidget(qr_label)
            qr_container_layout.addStretch()
            qr_layout.addLayout(qr_container_layout)
        else:
            no_qr = QLabel("QR Code not available")
            no_qr.setFont(QFont("Segoe UI", 12))
            no_qr.setStyleSheet("color: #6b7280; padding: 20px;")
            no_qr.setAlignment(Qt.AlignCenter)
            no_qr.setFixedSize(270, 270)  # Larger square shape for better visibility
            
            # Center the no QR code container
            no_qr_container_layout = QHBoxLayout()
            no_qr_container_layout.addStretch()
            no_qr_container_layout.addWidget(no_qr)
            no_qr_container_layout.addStretch()
            qr_layout.addLayout(no_qr_container_layout)

        # Shop ID below QR code
        shop_id_label = QLabel(f"Shop ID: {self.shopkeeper_data.get('shop_id', 'N/A')}")
        shop_id_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        shop_id_label.setStyleSheet("color: #1f2937; margin-top: 10px;")
        shop_id_label.setAlignment(Qt.AlignCenter)
        qr_layout.addWidget(shop_id_label)

        # Action buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)

        download_btn = QPushButton("Download QR")
        download_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        download_btn.clicked.connect(self.download_qr_code)

        print_btn = QPushButton("Print QR")
        print_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: #ffffff;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        print_btn.clicked.connect(self.print_qr_code)

        buttons_layout.addWidget(download_btn)
        buttons_layout.addWidget(print_btn)
        qr_layout.addLayout(buttons_layout)

        main_layout.addWidget(qr_card, 1)
        layout.addLayout(main_layout)

        layout.addStretch()
        scroll.setWidget(page)
        self.content_stack.addTab(scroll, "Shop QR")
        # Initialize edit mode state
        self.is_edit_mode = False

    def create_profile_page(self):
        """Profile page UI styled like the provided image (info card + QR panel)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # Header
        header = QHBoxLayout()
        title = QLabel("Profile")
        title.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title.setStyleSheet("color: #111827;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Main split identical to Shop QR page
        main_layout = QHBoxLayout()
        main_layout.setSpacing(20)

        # Left: Shop Information card with Edit + URL block
        details_card = QFrame()
        details_card.setStyleSheet("""
            QFrame { background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; }
        """)
        details_layout = QVBoxLayout(details_card)
        details_layout.setSpacing(15)

        title_row = QHBoxLayout()
        details_title = QLabel("Shop Information")
        details_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        details_title.setStyleSheet("color: #111827;")
        title_row.addWidget(details_title)
        title_row.addStretch()
        self.edit_btn_profile = QPushButton("Edit")
        self.edit_btn_profile.setStyleSheet("""
            QPushButton { background-color: #f3f4f6; color:#374151; border:1px solid #d1d5db; padding:6px 12px; border-radius:4px; font-weight:500; font-size:12px; }
            QPushButton:hover { background-color:#e5e7eb; }
        """)
        self.edit_btn_profile.clicked.connect(self.toggle_edit_mode)
        title_row.addWidget(self.edit_btn_profile)
        details_layout.addLayout(title_row)

        # Reuse existing shop info widgets/setup from QR page
        self.shop_info_widget_profile = QWidget()
        self.shop_info_layout_profile = QVBoxLayout(self.shop_info_widget_profile)
        self.shop_info_layout_profile.setSpacing(10)
        # Use same method to populate (it targets self.shop_info_layout when present), so mirror attribute
        self.shop_info_widget = self.shop_info_widget_profile
        self.shop_info_layout = self.shop_info_layout_profile
        self.setup_shop_info_display()
        details_layout.addWidget(self.shop_info_widget_profile)
        details_layout.addStretch()

        # QR Code URL section removed (UI cleanup)

        # Logout button at bottom of left card
        logout_btn = QPushButton("Log Out")
        logout_btn.setStyleSheet("""
            QPushButton {
                background-color: #ef4444;
                color: #ffffff;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #dc2626;
            }
        """)
        logout_btn.clicked.connect(self.logout)
        details_layout.addWidget(logout_btn)

        main_layout.addWidget(details_card, 1)

        # Right: QR panel (same as QR page)
        qr_card = QFrame()
        qr_card.setStyleSheet("""
            QFrame { background-color:#ffffff; border:1px solid #e5e7eb; border-radius:8px; padding:20px; }
        """
        )
        qr_layout = QVBoxLayout(qr_card)
        qr_layout.setAlignment(Qt.AlignCenter)
        qr_layout.setSpacing(15)
        shop_name_label = QLabel(self.shopkeeper_data.get('shop_name', 'Shop Name'))
        shop_name_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
        shop_name_label.setStyleSheet("color:#111827; margin-bottom:8px;")
        shop_name_label.setAlignment(Qt.AlignCenter)
        qr_layout.addWidget(shop_name_label)
        qr_subtitle = QLabel("Scan this QR code to access your EzPrint service")
        qr_subtitle.setFont(QFont("Segoe UI", 12))
        qr_subtitle.setStyleSheet("color:#6b7280;")
        qr_subtitle.setAlignment(Qt.AlignCenter)
        qr_layout.addWidget(qr_subtitle)
        qr_path = self.ensure_qr_code_exists()
        if qr_path and os.path.exists(qr_path):
            qr_pix = QPixmap(qr_path).scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            qr_label = QLabel()
            qr_label.setPixmap(qr_pix)
            qr_label.setAlignment(Qt.AlignCenter)
            qr_label.setStyleSheet("border:2px solid #e2e8f0; border-radius:8px; padding:10px; background:#f8fafc;")
            qr_label.setFixedSize(270, 270)
            qr_container_layout = QHBoxLayout()
            qr_container_layout.addStretch()
            qr_container_layout.addWidget(qr_label)
            qr_container_layout.addStretch()
            qr_layout.addLayout(qr_container_layout)
        else:
            no_qr = QLabel("QR Code not available")
            no_qr.setFont(QFont("Segoe UI", 12))
            no_qr.setStyleSheet("color:#6b7280; padding:20px;")
            no_qr.setAlignment(Qt.AlignCenter)
            no_qr.setFixedSize(270, 270)
            no_qr_container_layout = QHBoxLayout()
            no_qr_container_layout.addStretch()
            no_qr_container_layout.addWidget(no_qr)
            no_qr_container_layout.addStretch()
            qr_layout.addLayout(no_qr_container_layout)
        shop_id_label = QLabel(f"Shop ID: {self.shopkeeper_data.get('shop_id', 'N/A')}")
        shop_id_label.setFont(QFont("Segoe UI", 14, QFont.Bold))
        shop_id_label.setStyleSheet("color:#1f2937; margin-top:10px;")
        shop_id_label.setAlignment(Qt.AlignCenter)
        qr_layout.addWidget(shop_id_label)
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        download_btn = QPushButton("Download QR")
        download_btn.setStyleSheet("""
            QPushButton { background-color:#3b82f6; color:#fff; border:none; padding:10px 20px; border-radius:6px; font-weight:600; font-size:13px; }
            QPushButton:hover { background-color:#2563eb; }
        """)
        download_btn.clicked.connect(self.download_qr_code)
        print_btn = QPushButton("Print QR")
        print_btn.setStyleSheet("""
            QPushButton { background-color:#10b981; color:#fff; border:none; padding:10px 20px; border-radius:6px; font-weight:600; font-size:13px; }
            QPushButton:hover { background-color:#059669; }
        """)
        print_btn.clicked.connect(self.print_qr_code)
        buttons_layout.addWidget(download_btn)
        buttons_layout.addWidget(print_btn)
        qr_layout.addLayout(buttons_layout)

        main_layout.addWidget(qr_card, 1)
        layout.addLayout(main_layout)
        layout.addStretch()
        scroll.setWidget(page)
        self.content_stack.addTab(scroll, "Profile")
        self.edit_widgets = {}
    
    def copy_to_clipboard(self, text):
        """Copy text to clipboard"""
        try:
            from PyQt5.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            logger.info(f"Copied to clipboard: {text}")
        except Exception as e:
            logger.error(f"Error copying to clipboard: {e}")
    
    def setup_shop_info_display(self):
        """Setup shop information display (read-only mode)"""
        # Clear existing widgets – (FIX: Use recursive cleanup)
        self._clear_layout(self.shop_info_layout)
        
        # Reset spacing and margins to prevent overlap
        self.shop_info_layout.setSpacing(12)
        self.shop_info_layout.setContentsMargins(0, 0, 0, 0)
        
        # Use class-level session state ONLY for rendering (no fresh DB fetch)
        shop_data = self.shopkeeper_data
        
        # Shop name
        shop_name_label = QLabel(f"Shop Name: {shop_data.get('shop_name', 'Not set')}")
        shop_name_label.setFont(QFont("Segoe UI", 12))
        shop_name_label.setStyleSheet("color: #374151; margin-bottom: 8px;")
        self.shop_info_layout.addWidget(shop_name_label)
        
        # Shopkeeper Name (NEW)
        shopkeeper_name = shop_data.get('shopkeeper_name', 'Not set')
        shopkeeper_name_label = QLabel(f"Shopkeeper Name: {shopkeeper_name}")
        shopkeeper_name_label.setFont(QFont("Segoe UI", 12))
        shopkeeper_name_label.setStyleSheet("color: #374151; margin-bottom: 8px;")
        self.shop_info_layout.addWidget(shopkeeper_name_label)
        
        # Shop address
        address_text = shop_data.get('shop_address', 'Not set')
        address_label = QLabel(f"Address: {address_text}")
        address_label.setFont(QFont("Segoe UI", 12))
        address_label.setStyleSheet("color: #6b7280; margin-bottom: 8px;")
        address_label.setWordWrap(True)
        self.shop_info_layout.addWidget(address_label)
        
        # Contact number
        contact_text = shop_data.get('contact_number', 'Not set')
        contact_label = QLabel(f"Contact: {contact_text}")
        contact_label.setFont(QFont("Segoe UI", 12))
        contact_label.setStyleSheet("color: #6b7280; margin-bottom: 8px;")
        self.shop_info_layout.addWidget(contact_label)
        
        # Email (read-only)
        email_value = shop_data.get('email') or 'Not set'
        email_label = QLabel(f"Email: {email_value}")
        email_label.setFont(QFont("Segoe UI", 12))
        email_label.setStyleSheet("color: #6b7280; margin-bottom: 8px;")
        self.shop_info_layout.addWidget(email_label)
    
    def setup_shop_info_edit(self):
        """Setup shop information edit mode"""
        # Clear existing widgets – (FIX: Use recursive cleanup)
        self._clear_layout(self.shop_info_layout)
        
        # Reset spacing and margins to prevent overlap
        self.shop_info_layout.setSpacing(12)
        self.shop_info_layout.setContentsMargins(0, 0, 0, 0)
        
        # Get current shop data
        shop_data = self.auth_manager.get_shopkeeper_by_id(self.shopkeeper_data.get('shop_id'))
        if not shop_data:
            shop_data = self.shopkeeper_data
        
        # Shop name (editable)
        shop_name_row = QHBoxLayout()
        shop_name_label = QLabel("Shop Name:")
        shop_name_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        shop_name_label.setStyleSheet("color: #374151;")
        shop_name_label.setFixedWidth(100)
        shop_name_row.addWidget(shop_name_label)
        
        self.edit_widgets['shop_name'] = QLineEdit(shop_data.get('shop_name', ''))
        self.edit_widgets['shop_name'].setFont(QFont("Segoe UI", 12))
        self.edit_widgets['shop_name'].setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                background-color: #ffffff;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
        """)
        shop_name_row.addWidget(self.edit_widgets['shop_name'])
        self.shop_info_layout.addLayout(shop_name_row)
        
        # Shopkeeper Name (editable row)
        shopkeeper_row = QHBoxLayout()
        shopkeeper_label = QLabel("Shopkeeper Name:")
        shopkeeper_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        shopkeeper_label.setStyleSheet("color: #374151;")
        shopkeeper_label.setFixedWidth(140)  # Slightly wider to accommodate "Shopkeeper Name"
        shopkeeper_row.addWidget(shopkeeper_label)
        
        # Adjusting other labels to match width for alignment if necessary
        shop_name_label.setFixedWidth(140)
        
        self.shopkeeper_name_input = QLineEdit(shop_data.get('shopkeeper_name', ''))
        self.shopkeeper_name_input.setFont(QFont("Segoe UI", 12))
        self.shopkeeper_name_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                background-color: #ffffff;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
        """)
        shopkeeper_row.addWidget(self.shopkeeper_name_input)
        self.shop_info_layout.addLayout(shopkeeper_row)
        
        # Shop address (editable)
        address_row = QHBoxLayout()
        address_label = QLabel("Address:")
        address_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        address_label.setStyleSheet("color: #374151;")
        address_label.setFixedWidth(140)
        address_row.addWidget(address_label)
        
        self.edit_widgets['shop_address'] = QLineEdit(shop_data.get('shop_address', ''))
        self.edit_widgets['shop_address'].setFont(QFont("Segoe UI", 12))
        self.edit_widgets['shop_address'].setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                background-color: #ffffff;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
        """)
        address_row.addWidget(self.edit_widgets['shop_address'])
        self.shop_info_layout.addLayout(address_row)
        
        # Contact number (editable)
        contact_row = QHBoxLayout()
        contact_label = QLabel("Contact:")
        contact_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        contact_label.setStyleSheet("color: #374151;")
        contact_label.setFixedWidth(140)
        contact_row.addWidget(contact_label)
        
        self.edit_widgets['contact_number'] = QLineEdit(shop_data.get('contact_number', ''))
        self.edit_widgets['contact_number'].setFont(QFont("Segoe UI", 12))
        self.edit_widgets['contact_number'].setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                background-color: #ffffff;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
        """)
        contact_row.addWidget(self.edit_widgets['contact_number'])
        self.shop_info_layout.addLayout(contact_row)
        
        # Email (editable)
        email_row = QHBoxLayout()
        email_label = QLabel("Email:")
        email_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        email_label.setStyleSheet("color: #374151;")
        email_label.setFixedWidth(140)
        email_row.addWidget(email_label)
        
        self.email_input = QLineEdit(shop_data.get('email', ''))
        self.email_input.setFont(QFont("Segoe UI", 12))
        self.email_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                background-color: #ffffff;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
        """)
        email_row.addWidget(self.email_input)
        self.shop_info_layout.addLayout(email_row)
        
        # Action buttons
        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        
        save_btn = QPushButton("Save")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        save_btn.clicked.connect(self.save_shop_info)
        button_row.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #374151;
                border: 1px solid #d1d5db;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #f9fafb;
            }
        """)
        cancel_btn.clicked.connect(self.cancel_edit)
        button_row.addWidget(cancel_btn)
        
        button_row.addStretch()
        
        # Add spacing before buttons to prevent overlap
        self.shop_info_layout.addSpacing(16)
        self.shop_info_layout.addLayout(button_row)
    
    def toggle_edit_mode(self):
        """Toggle between display and edit mode (FIX 2: Logic-only switch)"""
        self.is_edit_mode = True
        self.setup_shop_info_edit()
    
    def save_shop_info(self):
        """Save shop information changes (FIX 2: Strict flow)"""
        try:
            # 1. Read values from inputs
            shop_name = self.edit_widgets['shop_name'].text().strip()
            shop_address = self.edit_widgets['shop_address'].text().strip()
            contact_number = self.edit_widgets['contact_number'].text().strip()
            email = self.email_input.text().strip()
            shopkeeper_name = self.shopkeeper_name_input.text().strip()
            
            if not shop_name:
                QMessageBox.warning(self, "Validation Error", "Shop name is required")
                return
            
            # 2. Call backend update
            success, message, _ = self.auth_manager.update_shop_info(
                self.shopkeeper_data.get('shop_id'),
                shop_name=shop_name,
                shop_address=shop_address if shop_address else None,
                contact_number=contact_number if contact_number else None,
                email=email,
                shopkeeper_name=shopkeeper_name
            )
            
            if success:
                # 3. Fetch fresh data
                fresh_data = self.auth_manager.get_shopkeeper_by_id(self.shopkeeper_data.get('shop_id'))
                if fresh_data:
                    self.shopkeeper_data = fresh_data
                
                # 4. Set mode to False
                self.is_edit_mode = False
                
                # 5. Build display
                self.setup_shop_info_display()
                
                QMessageBox.information(self, "Success", "Shop information updated successfully")
            else:
                QMessageBox.warning(self, "Update Failed", message)
                
        except Exception as e:
            logger.error(f"Error saving shop info: {e}")
            QMessageBox.warning(self, "Error", f"Failed to save changes: {str(e)}")
    
    def cancel_edit(self):
        """Cancel edit mode and return to display mode (FIX 3: Logic-only switch)"""
        self.is_edit_mode = False
        self.setup_shop_info_display()
    
    @safe_database_action("LOAD_PRICING")
    def _sync_pricing_ui(self):
        """Sync central pricing state to all UI widgets across all pages"""
        try:
            # Helper to safely set text on a widget if it exists and is alive
            def safe_sync(widget, key):
                if widget and self._is_alive(widget):
                    val = str(self.pricing_state.get(key, "0.0"))
                    widget.setText(val)

            # Sync Sidebar set
            safe_sync(self.sidebar_bw_single_input, "bw_single")
            safe_sync(self.sidebar_bw_double_input, "bw_double")
            safe_sync(self.sidebar_color_single_input, "color_single")
            safe_sync(self.sidebar_color_double_input, "color_double")

            # Sync Settings set
            safe_sync(self.settings_bw_single_input, "bw_single")
            safe_sync(self.settings_bw_double_input, "bw_double")
            safe_sync(self.settings_color_single_input, "color_single")
            safe_sync(self.settings_color_double_input, "color_double")
            
        except Exception as e:
            logger.error(f"Error syncing pricing UI: {e}")

    def load_pricing(self):
        """Load pricing and shop configuration from API (with DB fallback)"""
        try:
            shop_id = self.shopkeeper_data.get('shop_id')
            if not shop_id:
                logger.warning("No shop_id available for loading config")
                return
            
            # Phase 3: Try to fetch config and pricing from API first
            api_success = False
            success, api_data, error = self.api_client.get_config(shop_id)
            
            if success and api_data:
                logger.info("Shop configuration fetched successfully from API")
                
                # Update pricing from API
                pricing_data = api_data.get('pricing', {})
                if pricing_data:
                    self.pricing_state["bw_single"] = pricing_data.get("bw_single", 2.0)
                    self.pricing_state["bw_double"] = pricing_data.get("bw_double", 1.5)
                    self.pricing_state["color_single"] = pricing_data.get("color_single", 10.0)
                    self.pricing_state["color_double"] = pricing_data.get("color_double", 8.0)
                
                # Update shop info from API (Sync to self.shopkeeper_data)
                shop_info = api_data.get('shop_info', {})
                if shop_info:
                    for key, val in shop_info.items():
                        self.shopkeeper_data[key] = val
                    logger.info("Shop info updated from API data")
                
                api_success = True
            else:
                logger.warning(f"API Config fetch failed, falling back to database: {error}")
            
            # Database Fallback
            if not api_success:
                logger.info("Using Database for Pricing/Config (Fallback)")
                pricing = self.db.query(ShopPricing).filter(ShopPricing.shop_id == shop_id).first()
                if pricing:
                    self.pricing_state["bw_single"] = pricing.bw_single
                    self.pricing_state["bw_double"] = pricing.bw_double
                    self.pricing_state["color_single"] = pricing.color_single
                    self.pricing_state["color_double"] = pricing.color_double
                else:
                    self.pricing_state.update({"bw_single": 2.0, "bw_double": 1.5, "color_single": 10.0, "color_double": 8.0})
                    
                # For shop info fallback, we rely on existing shopkeeper_data (from login)
            
            # Synchronize all UI widgets
            self._sync_pricing_ui()
            
            # If we are on profile page, refresh display
            if hasattr(self, 'current_page') and self.current_page == "profile":
                self.setup_shop_info_display()
                
        except Exception as e:
            logger.error(f"Error loading pricing: {e}")
            self._sync_pricing_ui()
    
    @safe_database_action("SAVE_PRICING")
    def save_pricing(self, checked=False):
        """Save pricing configuration from the ACTIVE page and sync UI"""
        try:
            shop_id = self.shopkeeper_data.get('shop_id')
            if not shop_id:
                QMessageBox.warning(self, "Error", "Shop ID not found")
                return
            
            # Determine which input set to read from based on current page
            # This ensures we get the values the user actually edited
            is_settings = getattr(self, 'current_page', '') == 'settings'
            
            bw_s_w = self.settings_bw_single_input if is_settings else self.sidebar_bw_single_input
            bw_d_w = self.settings_bw_double_input if is_settings else self.sidebar_bw_double_input
            col_s_w = self.settings_color_single_input if is_settings else self.sidebar_color_single_input
            col_d_w = self.settings_color_double_input if is_settings else self.sidebar_color_double_input

            # Safety check: if active page widgets aren't loaded, fallback to state (shouldn't happen on Save)
            if not bw_s_w or not self._is_alive(bw_s_w):
                return

            # Validate and parse inputs
            try:
                bw_single = float(bw_s_w.text() or "2.0")
                bw_double = float(bw_d_w.text() or "1.5")
                color_single = float(col_s_w.text() or "10.0")
                color_double = float(col_d_w.text() or "8.0")
            except ValueError:
                QMessageBox.warning(self, "Validation Error", "Please enter valid numeric values for all prices")
                return
            
            # Validate positive values
            if bw_single < 0 or bw_double < 0 or color_single < 0 or color_double < 0:
                QMessageBox.warning(self, "Validation Error", "Prices must be positive numbers")
                return
            
            # Get or create pricing record
            pricing = self.db.query(ShopPricing).filter(ShopPricing.shop_id == shop_id).first()
            
            if pricing:
                # Update existing pricing
                pricing.bw_single = bw_single
                pricing.bw_double = bw_double
                pricing.color_single = color_single
                pricing.color_double = color_double
                pricing.updated_at = datetime.utcnow()
            else:
                # Create new pricing record
                pricing = ShopPricing(
                    shop_id=shop_id,
                    bw_single=bw_single,
                    bw_double=bw_double,
                    color_single=color_single,
                    color_double=color_double
                )
                self.db.add(pricing)
            
            self.db.commit()
            
            # Update central state after successful save
            self.pricing_state["bw_single"] = bw_single
            self.pricing_state["bw_double"] = bw_double
            self.pricing_state["color_single"] = color_single
            self.pricing_state["color_double"] = color_double

            # SYNC: Push saved values to BOTH sets of UI widgets immediately
            self._sync_pricing_ui()
            
            QMessageBox.information(self, "Success", "Pricing configuration saved successfully")
            logger.info(f"Pricing saved for shop ID: {shop_id}")
            
        except Exception as e:
            logger.error(f"Error saving pricing: {e}")
            self.db.rollback()
            QMessageBox.warning(self, "Error", f"Failed to save pricing: {str(e)}")
    
    
    def create_print_jobs_page(self):
        """Create a modern, professional Print Jobs page with search, filters and styled table"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header with title, search, refresh, notification, profile
        header_layout = QHBoxLayout()
        title_label = QLabel("Print Jobs")
        title_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title_label.setStyleSheet("color: #111827;")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # Styled search bar matching provided design (rounded, inset icon, subtle border)
        self.jobs_search = QLineEdit()
        self.jobs_search.setPlaceholderText("Search jobs...")
        self.jobs_search.textChanged.connect(self.load_print_jobs)
        self.jobs_search.setMinimumWidth(200)
        self.jobs_search.setMaximumWidth(420)
        self.jobs_search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.jobs_search.setObjectName("jobsSearch")
        self.jobs_search.setStyleSheet(
            """
            QLineEdit#jobsSearch {
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 12px;
                padding-left: 36px;  /* room for magnifier icon */
                padding-right: 12px;
                padding-top: 10px;
                padding-bottom: 10px;
                color: #1F2937;
            }
            QLineEdit#jobsSearch:focus {
                border: 1px solid #93C5FD;
                box-shadow: 0 0 0 3px rgba(59,130,246,0.25);
                background: #FFFFFF;
            }
            QLineEdit#jobsSearch::placeholder { color: #6B7280; }
            """
        )
        # Add a small magnifier icon using a QLabel overlay
        try:
            search_icon = QLabel(self.jobs_search)
            # Use a simple search icon indicator instead of emoji
            search_icon.setStyleSheet("color:#6B7280; font-size:14px; font-weight:bold;")
            search_icon.setText("⌕")
            search_icon.setStyleSheet("color:#6B7280; font-size:14px;")
            search_icon.setFixedSize(20, 20)
            search_icon.move(10, int((self.jobs_search.height() - 20) / 2))
            # Keep icon positioned when the widget resizes later
            def _reposition_icon():
                try:
                    search_icon.move(10, int((self.jobs_search.height() - 20) / 2))
                except Exception:
                    pass
            # IMPORTANT: avoid returning a value from Qt event handlers.
            # Using a lambda that returns a tuple can crash with sipBadCatcherResult.
            # Replace with a proper function that returns None.
            _old_resize = self.jobs_search.resizeEvent
            def _on_search_resize(ev):
                try:
                    _reposition_icon()
                except Exception:
                    pass
                if callable(_old_resize):
                    _old_resize(ev)  # Call original handler
                # Explicitly return None (implicit in Python) to satisfy Qt
            self.jobs_search.resizeEvent = _on_search_resize
        except Exception:
            pass
        header_layout.addWidget(self.jobs_search)

        # Removed header refresh button as requested

        # Removed notifications and dark mode toggle as requested

        # Removed profile icon as requested
        # Auto Mode toggle (styled like the same slide switch), placed before Auto Refresh
        self.auto_mode_toggle = QCheckBox()
        self.auto_mode_toggle.setChecked(self.auto_mode)
        self.auto_mode_toggle.setToolTip("Auto Mode")
        self.auto_mode_toggle.toggled.connect(lambda checked: self.set_auto_mode() if checked else self.set_manual_mode())
        self.auto_mode_toggle.setStyleSheet(TOGGLE_STYLE)
        # inner knob for Auto Mode (same as Auto Refresh)
        self.auto_mode_knob = QLabel(self.auto_mode_toggle)
        self.auto_mode_knob.setObjectName("knob")
        self.auto_mode_knob.setStyleSheet(f"#knob{{ {KNOB_STYLE} }}")
        self.auto_mode_knob.resize(20,20)
        self.auto_mode_knob.move(2,2)  # initial unchecked position
        def _move_auto_mode_knob(checked):
            try:
                if self._is_alive(self.auto_mode_knob):
                    self.auto_mode_knob.move(22 if checked else 2, 2)
            except Exception:
                pass
        # ensure position matches current state and track future toggles
        _move_auto_mode_knob(self.auto_mode_toggle.isChecked())
        self.auto_mode_toggle.toggled.connect(_move_auto_mode_knob)
        auto_mode_label = QLabel("Auto Mode")
        auto_mode_label.setStyleSheet("color: #111827;")
        header_layout.addWidget(auto_mode_label)
        header_layout.addWidget(self.auto_mode_toggle)

        # Manual Refresh Button (replacing Auto Refresh toggle)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #374151;
                border: 1px solid #d1d5db;
                padding: 8px 16px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 13px;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #f9fafb;
                border-color: #9ca3af;
            }
            QPushButton:pressed {
                background-color: #f3f4f6;
            }
        """)
        self.refresh_btn.clicked.connect(self.manual_refresh)
        header_layout.addWidget(self.refresh_btn)

        layout.addLayout(header_layout)

        # Search & Filters Card
        filters_card = QFrame()
        filters_card.setStyleSheet(
            """
            QFrame { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px; }
            QLineEdit { padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 6px; }
            QComboBox { padding: 6px 10px; border: 1px solid #d1d5db; border-radius: 6px; }
            """
        )
        filters_layout = QHBoxLayout(filters_card)
        filters_layout.setContentsMargins(12, 12, 12, 12)
        filters_layout.setSpacing(12)

        # Printer selection
        filters_layout.addWidget(QLabel("Print to:"))
        self.job_printer_combo = QComboBox()
        self.job_printer_combo.setToolTip("Select printer for new print jobs")
        self.job_printer_combo.currentTextChanged.connect(self.on_job_printer_changed)
        self.job_printer_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.job_printer_combo.setMinimumContentsLength(24)
        self.job_printer_combo.setMinimumWidth(240)
        try:
            self.job_printer_combo.setView(QListView())
            self.job_printer_combo.view().setMinimumWidth(300)
        except Exception:
            pass
        filters_layout.addWidget(self.job_printer_combo, 1)

        self.filter_status = QComboBox()
        self.filter_status.addItems(["All", "Pending", "Printing", "Completed", "Failed"])
        self.filter_status.currentIndexChanged.connect(self.load_print_jobs)
        filters_layout.addWidget(self.filter_status)

        # Date filter
        self.filter_date = QComboBox()
        self.filter_date.addItems(["All", "Today", "Yesterday", "This Week", "This Month"])
        self.filter_date.currentIndexChanged.connect(self._on_date_filter_changed)
        filters_layout.addWidget(self.filter_date)
        
        # Auto-refresh timer for real-time date filtering
        self.date_refresh_timer = QTimer()
        self.date_refresh_timer.timeout.connect(self._check_date_change)
        self.date_refresh_timer.start(30000)  # Check every 30 seconds for better real-time behavior
        
        # Date input widgets removed since we no longer use Custom Range
        # self.date_from and self.date_to are no longer needed

        # Sorting selector removed as requested

        layout.addWidget(filters_card)

        # Selection action bar (hidden by default) – appears in selection mode
        self.selection_bar = QFrame()
        self.selection_bar.setStyleSheet("QFrame { background:#2b2f36; border-radius:6px; }")
        self.selection_bar.setVisible(False)
        sel_layout = QHBoxLayout(self.selection_bar)
        sel_layout.setContentsMargins(12, 6, 12, 6)
        sel_layout.setSpacing(12)
        self.sel_count_label = QLabel("0 selected")
        self.sel_count_label.setStyleSheet("color:#f3f4f6; font-weight:600;")
        sel_layout.addWidget(self.sel_count_label)
        sel_layout.addStretch()

        # Shared style for all buttons in selection bar
        btn_style = "QPushButton, QToolButton { color:#111827; background:#e5e7eb; padding:5px 12px; border:none; border-radius:4px; font-weight:500; min-width: 60px; } QPushButton:hover, QToolButton:hover { background:#d1d5db; } QPushButton:pressed, QToolButton:pressed { background:#9ca3af; }"

        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.setToolTip("Select all")
        self.btn_select_all.setStyleSheet(btn_style)
        self.btn_select_all.clicked.connect(lambda: self.toggle_all_jobs(Qt.Checked))
        sel_layout.addWidget(self.btn_select_all)

        self.btn_print_bulk = QToolButton()
        self.btn_print_bulk.setToolTip("Print")
        self.btn_print_bulk.setText("Print")
        self.btn_print_bulk.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_print_bulk.setStyleSheet(btn_style)
        self.btn_print_bulk.clicked.connect(self.bulk_print_jobs)
        sel_layout.addWidget(self.btn_print_bulk)

        self.btn_view_bulk = QToolButton()
        self.btn_view_bulk.setToolTip("View")
        self.btn_view_bulk.setText("View")
        self.btn_view_bulk.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_view_bulk.setStyleSheet(btn_style)
        self.btn_view_bulk.clicked.connect(self.bulk_view_jobs)
        sel_layout.addWidget(self.btn_view_bulk)

        self.btn_download_bulk = QToolButton()
        self.btn_download_bulk.setToolTip("Download")
        self.btn_download_bulk.setText("Download")
        self.btn_download_bulk.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_download_bulk.setStyleSheet(btn_style)
        self.btn_download_bulk.clicked.connect(self.bulk_download_jobs)
        sel_layout.addWidget(self.btn_download_bulk)

        self.btn_cancel_bulk = QToolButton()
        self.btn_cancel_bulk.setToolTip("Cancel")
        self.btn_cancel_bulk.setText("Cancel")
        self.btn_cancel_bulk.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_cancel_bulk.setStyleSheet(btn_style)
        self.btn_cancel_bulk.clicked.connect(self.bulk_cancel_jobs)
        sel_layout.addWidget(self.btn_cancel_bulk)

        self.btn_delete_bulk = QToolButton()
        self.btn_delete_bulk.setToolTip("Delete")
        self.btn_delete_bulk.setText("Delete")
        self.btn_delete_bulk.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_delete_bulk.setStyleSheet(btn_style)
        self.btn_delete_bulk.clicked.connect(self.bulk_delete_jobs)
        sel_layout.addWidget(self.btn_delete_bulk)

        self.btn_exit_select = QPushButton("Exit")
        self.btn_exit_select.setStyleSheet(btn_style)
        self.btn_exit_select.clicked.connect(self.exit_selection_mode)
        sel_layout.addWidget(self.btn_exit_select)

        layout.addWidget(self.selection_bar)

        # Status bar for refresh info
        status_layout = QHBoxLayout()
        self.last_refresh_label = QLabel("Last refresh: Never")
        self.last_refresh_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        status_layout.addWidget(self.last_refresh_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)


        # Jobs cards scroll area (card-based layout matching Connect Printer page)
        self.jobs_cards_scroll = QScrollArea()
        self.jobs_cards_scroll.setWidgetResizable(True)
        self.jobs_cards_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #f1f5f9;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #cbd5e1;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #94a3b8;
            }
        """)
        self.jobs_cards_widget = QWidget()
        self.jobs_cards_layout = QVBoxLayout(self.jobs_cards_widget)
        self.jobs_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.jobs_cards_layout.setSpacing(16)  # Match Connect Printer page spacing
        
        # Fixed Header Card - Moved out of scroll area so it stays locked at top
        self.jobs_header_card = self.create_print_jobs_header_card()
        # Add the header card to the main layout
        layout.addWidget(self.jobs_header_card)
        self.jobs_header_card.setVisible(False) # Hidden until jobs are loaded
        
        self.jobs_cards_scroll.setWidget(self.jobs_cards_widget)
        # Ensure scrollbar is always on to maintain perfect alignment with fixed header
        self.jobs_cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        layout.addWidget(self.jobs_cards_scroll)
        
        # Reduce spacing between header and scroll area for a integrated look
        layout.setSpacing(8)
        
        # Keep table for backward compatibility (hidden) - needed for selection logic
        self.jobs_table = QTableWidget()
        self.jobs_table.setColumnCount(9)
        self.jobs_table.hide()  # Hide table, use cards instead
        layout.addWidget(self.jobs_table)

        # Removed footer actions (Refresh / Clear Completed) as requested

        self.content_stack.addTab(page, "Print Jobs")
        
        # Initialize view mode based on current size
        self.update_jobs_view_mode()

        # Enable double-click to open file
        try:
            self.jobs_table.itemDoubleClicked.connect(self._on_job_item_double_clicked)
            self.jobs_table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.jobs_table.customContextMenuRequested.connect(self._on_jobs_context_menu)
        except Exception:
            pass

    def create_pricing_page(self):
        """Create pricing configuration page"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # Header
        header = QHBoxLayout()
        title = QLabel("Price Configuration")
        title.setFont(QFont("Segoe UI", 20, QFont.Bold))
        title.setStyleSheet("color: #111827;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Subtitle
        subtitle = QLabel("Set your pricing for different print services")
        subtitle.setFont(QFont("Segoe UI", 12))
        subtitle.setStyleSheet("color: #6b7280; margin-bottom: 10px;")
        layout.addWidget(subtitle)

        # Main content card
        pricing_card = QFrame()
        pricing_card.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 24px;
            }
        """)
        pricing_layout = QVBoxLayout(pricing_card)
        pricing_layout.setSpacing(24)

        # Two column layout for B/W and Color
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(24)

        # Left column: Black & White Printing
        bw_card = QFrame()
        bw_card.setStyleSheet("""
            QFrame {
                background-color: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        bw_layout = QVBoxLayout(bw_card)
        bw_layout.setSpacing(16)

        bw_title = QLabel("Black & White Printing")
        bw_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        bw_title.setStyleSheet("color: #111827; margin-bottom: 8px;")
        bw_layout.addWidget(bw_title)

        # B/W Single-sided
        bw_single_layout = QVBoxLayout()
        bw_single_label = QLabel("Single-sided (per page)")
        bw_single_label.setFont(QFont("Segoe UI", 11))
        bw_single_label.setStyleSheet("color: #374151; margin-bottom: 4px;")
        bw_single_layout.addWidget(bw_single_label)

        bw_single_input_layout = QHBoxLayout()
        currency_label = QLabel("₹")
        currency_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        currency_label.setStyleSheet("color: #111827; padding-right: 4px;")
        bw_single_input_layout.addWidget(currency_label)

        self.sidebar_bw_single_input = QLineEdit()
        self.sidebar_bw_single_input.setPlaceholderText("2.0")
        self.sidebar_bw_single_input.setReadOnly(True)
        self.sidebar_bw_single_input.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
            QLineEdit:read-only {
                background-color: #f9fafb;
            }
        """)
        bw_single_input_layout.addWidget(self.sidebar_bw_single_input)
        bw_single_layout.addLayout(bw_single_input_layout)
        bw_layout.addLayout(bw_single_layout)

        # B/W Double-sided
        bw_double_layout = QVBoxLayout()
        bw_double_label = QLabel("Double-sided (per page)")
        bw_double_label.setFont(QFont("Segoe UI", 11))
        bw_double_label.setStyleSheet("color: #374151; margin-bottom: 4px;")
        bw_double_layout.addWidget(bw_double_label)

        bw_double_input_layout = QHBoxLayout()
        currency_label2 = QLabel("₹")
        currency_label2.setFont(QFont("Segoe UI", 12, QFont.Bold))
        currency_label2.setStyleSheet("color: #111827; padding-right: 4px;")
        bw_double_input_layout.addWidget(currency_label2)

        self.sidebar_bw_double_input = QLineEdit()
        self.sidebar_bw_double_input.setPlaceholderText("1.5")
        self.sidebar_bw_double_input.setReadOnly(True)
        self.sidebar_bw_double_input.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
            QLineEdit:read-only {
                background-color: #f9fafb;
            }
        """)
        bw_double_input_layout.addWidget(self.sidebar_bw_double_input)
        bw_double_layout.addLayout(bw_double_input_layout)
        bw_layout.addLayout(bw_double_layout)

        columns_layout.addWidget(bw_card, 1)

        # Right column: Color Printing
        color_card = QFrame()
        color_card.setStyleSheet("""
            QFrame {
                background-color: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        color_layout = QVBoxLayout(color_card)
        color_layout.setSpacing(16)

        color_title = QLabel("Color Printing")
        color_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        color_title.setStyleSheet("color: #111827; margin-bottom: 8px;")
        color_layout.addWidget(color_title)

        # Color Single-sided
        color_single_layout = QVBoxLayout()
        color_single_label = QLabel("Single-sided (per page)")
        color_single_label.setFont(QFont("Segoe UI", 11))
        color_single_label.setStyleSheet("color: #374151; margin-bottom: 4px;")
        color_single_layout.addWidget(color_single_label)

        color_single_input_layout = QHBoxLayout()
        currency_label3 = QLabel("₹")
        currency_label3.setFont(QFont("Segoe UI", 12, QFont.Bold))
        currency_label3.setStyleSheet("color: #111827; padding-right: 4px;")
        color_single_input_layout.addWidget(currency_label3)

        self.sidebar_color_single_input = QLineEdit()
        self.sidebar_color_single_input.setPlaceholderText("10.0")
        self.sidebar_color_single_input.setReadOnly(True)
        self.sidebar_color_single_input.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
            QLineEdit:read-only {
                background-color: #f9fafb;
            }
        """)
        color_single_input_layout.addWidget(self.sidebar_color_single_input)
        color_single_layout.addLayout(color_single_input_layout)
        color_layout.addLayout(color_single_layout)

        # Color Double-sided
        color_double_layout = QVBoxLayout()
        color_double_label = QLabel("Double-sided (per page)")
        color_double_label.setFont(QFont("Segoe UI", 11))
        color_double_label.setStyleSheet("color: #374151; margin-bottom: 4px;")
        color_double_layout.addWidget(color_double_label)

        color_double_input_layout = QHBoxLayout()
        currency_label4 = QLabel("₹")
        currency_label4.setFont(QFont("Segoe UI", 12, QFont.Bold))
        currency_label4.setStyleSheet("color: #111827; padding-right: 4px;")
        color_double_input_layout.addWidget(currency_label4)

        self.sidebar_color_double_input = QLineEdit()
        self.sidebar_color_double_input.setPlaceholderText("8.0")
        self.sidebar_color_double_input.setReadOnly(True)
        self.sidebar_color_double_input.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
            QLineEdit:read-only {
                background-color: #f9fafb;
            }
        """)
        color_double_input_layout.addWidget(self.sidebar_color_double_input)
        color_double_layout.addLayout(color_double_input_layout)
        color_layout.addLayout(color_double_layout)

        columns_layout.addWidget(color_card, 1)
        pricing_layout.addLayout(columns_layout)

        # Button layout (bottom-right aligned)
        button_layout = QHBoxLayout()
        button_layout.addStretch()  # Push buttons to the right
        
        # Edit button (secondary style)
        edit_btn = QPushButton("Edit")
        edit_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #374151;
                border: 1px solid #d1d5db;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 500;
                font-size: 14px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #f9fafb;
                border-color: #9ca3af;
            }
        """)
        
        # Save button (primary style)
        save_btn = QPushButton("Save")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 14px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        save_btn.clicked.connect(self.save_pricing)
        
        # Edit button handler (toggle input editability)
        def toggle_edit_mode():
            is_readonly = self.sidebar_bw_single_input.isReadOnly()
            self.sidebar_bw_single_input.setReadOnly(not is_readonly)
            self.sidebar_bw_double_input.setReadOnly(not is_readonly)
            self.sidebar_color_single_input.setReadOnly(not is_readonly)
            self.sidebar_color_double_input.setReadOnly(not is_readonly)
        
        edit_btn.clicked.connect(toggle_edit_mode)
        
        button_layout.addWidget(edit_btn)
        button_layout.addSpacing(10)  # 10px spacing between buttons
        button_layout.addWidget(save_btn)
        
        pricing_layout.addLayout(button_layout)

        layout.addWidget(pricing_card)
        layout.addStretch()

        scroll.setWidget(page)
        self.content_stack.addTab(scroll, "Set Pricing")

        # Load existing pricing
        self.load_pricing()

    def _toggle_dark_mode(self, enabled: bool):
        try:
            if enabled:
                self.setStyleSheet("""
                    QWidget { background-color: #111827; color: #e5e7eb; }
                    QTableWidget { background: #1f2937; color: #e5e7eb; }
                    QHeaderView::section { background: #374151; color: #e5e7eb; }
                    QPushButton { background: #374151; color: #e5e7eb; border: 1px solid #4b5563; }
                """)
            else:
                self.setStyleSheet("")
        except Exception:
            pass

    def _on_auto_refresh_toggled(self, enabled: bool):
        try:
            if hasattr(self, 'timer'):
                if enabled:
                    self.timer.start(5000)
                else:
                    self.timer.stop()
        except Exception:
            pass
    
    def _on_job_item_double_clicked(self, item):
        try:
            row = item.row()
            # Get job_id prefix from column 0
            job_id_widget = self.jobs_table.cellWidget(row, 0)
            job_id_text = job_id_widget.text() if job_id_widget else self.jobs_table.item(row, 0).text()
            # Resolve job from DB
            db = SessionLocal()
            job = None
            for j in db.query(PrintJob).filter(PrintJob.shop_id == self.shopkeeper_data['shop_id']).all():
                if j.job_id.startswith(job_id_text):
                    job = j
                    break
            db.close()
            if not job:
                self.show_toast("Job not found")
                return

            # Cloudinary file — open in browser
            if job.cloudinary_public_id:
                import webbrowser
                from shared.cloudinary_helper import get_cloudinary_url
                url = get_cloudinary_url(job.cloudinary_public_id)
                webbrowser.open(url)

            # Local file fallback
            elif job.file_path and os.path.exists(job.file_path):
                try:
                    if sys.platform.startswith('win'):
                        os.startfile(job.file_path)
                    elif sys.platform == 'darwin':
                        import subprocess
                        subprocess.Popen(['open', job.file_path])
                    else:
                        import subprocess
                        subprocess.Popen(['xdg-open', job.file_path])
                except Exception:
                    self.show_toast("Unable to open file")

            else:
                self.show_toast("File not found")
        except Exception as e:
            logger.error(f"Error opening file: {e}")

    def _on_jobs_context_menu(self, pos: QPoint):
        try:
            index = self.jobs_table.indexAt(pos)
            if not index.isValid():
                return
            row = index.row()
            job_id_item = self.jobs_table.item(row, 1)
            if not job_id_item:
                return
            job_id = job_id_item.data(Qt.UserRole)
            if not job_id:
                return
                
            menu = QMenu(self.jobs_table)
            act_open = QAction("Open", menu)
            act_show = QAction("Show in folder", menu)
            act_copy_path = QAction("Copy path", menu)
            act_copy_id = QAction("Copy ID", menu)
            act_reprint = QAction("Reprint", menu)
            act_cancel = QAction("Cancel", menu)
            act_delete = QAction("Delete", menu)
            act_download = QAction("Download", menu)
            
            # Use job_id in lambdas to avoid detached object issues
            act_open.triggered.connect(lambda checked=False, jid=job_id: self.open_job_by_id(jid))
            act_show.triggered.connect(lambda checked=False, jid=job_id: self.reveal_job_in_folder_by_id(jid))
            act_copy_path.triggered.connect(lambda checked=False, jid=job_id: self.copy_job_path_by_id(jid))
            act_copy_id.triggered.connect(lambda checked=False, jid=job_id: QApplication.clipboard().setText(jid))
            act_reprint.triggered.connect(lambda checked=False, jid=job_id: self.reprint_job_by_id(jid))
            act_cancel.triggered.connect(lambda checked=False, jid=job_id: self.cancel_job_by_id(jid))
            act_delete.triggered.connect(lambda checked=False, jid=job_id: self.delete_job_by_id(jid))
            act_download.triggered.connect(lambda checked=False, jid=job_id: self.download_receipt_by_id(jid))
            
            for act in [act_open, act_show, act_copy_path, act_copy_id]:
                menu.addAction(act)
            menu.addSeparator()
            for act in [act_reprint, act_cancel, act_delete, act_download]:
                menu.addAction(act)
            menu.exec_(self.jobs_table.viewport().mapToGlobal(pos))
        except Exception as e:
            logger.error(f"Context menu error: {e}")

    def delete_job_by_id(self, job_id):
        """Securely delete a job by re-fetching it from DB"""
        try:
            from shared.database import PrintJob
            job = self.db.query(PrintJob).filter(PrintJob.job_id == job_id).first()
            if job:
                self.delete_job(job)
            else:
                self.show_toast("Job no longer exists")
        except Exception as e:
            logger.error(f"Error in delete_job_by_id: {e}")

    def reprint_job_by_id(self, job_id):
        job = self.db.query(PrintJob).filter(PrintJob.job_id == job_id).first()
        if job: self.print_job(job)

    def cancel_job_by_id(self, job_id):
        job = self.db.query(PrintJob).filter(PrintJob.job_id == job_id).first()
        if job: self.stop_job(job)

    def open_job_by_id(self, job_id):
        job = self.db.query(PrintJob).filter(PrintJob.job_id == job_id).first()
        if job: self._open_job_file(job)

    def reveal_job_in_folder_by_id(self, job_id):
        job = self.db.query(PrintJob).filter(PrintJob.job_id == job_id).first()
        if job: self._reveal_in_folder(job)

    def copy_job_path_by_id(self, job_id):
        job = self.db.query(PrintJob).filter(PrintJob.job_id == job_id).first()
        if job: QApplication.clipboard().setText(job.file_path or '')
        
    def download_receipt_by_id(self, job_id):
        job = self.db.query(PrintJob).filter(PrintJob.job_id == job_id).first()
        if job: self.download_receipt(job)

    def _open_job_file(self, job):
        try:
            if job and job.cloudinary_public_id:
                import webbrowser
                from shared.cloudinary_helper import get_cloudinary_url
                url = get_cloudinary_url(job.cloudinary_public_id)
                if url:
                    webbrowser.open(url)
                else:
                    self.show_toast("Unable to generate file URL")
            elif job and job.file_path and os.path.exists(job.file_path):
                if sys.platform.startswith('win'):
                    os.startfile(job.file_path)
                elif sys.platform == 'darwin':
                    import subprocess
                    subprocess.Popen(['open', job.file_path])
                else:
                    import subprocess
                    subprocess.Popen(['xdg-open', job.file_path])
            else:
                self.show_toast("File not found")

        except Exception:
            self.show_toast("Unable to open file")

    def _reveal_in_folder(self, job):
        try:
            if job and job.file_path and os.path.exists(job.file_path):
                folder = os.path.dirname(job.file_path)
                if sys.platform.startswith('win'):
                    os.startfile(folder)
                elif sys.platform == 'darwin':
                    import subprocess
                    subprocess.Popen(['open', folder])
                else:
                    import subprocess
                    subprocess.Popen(['xdg-open', folder])
            else:
                self.show_toast("Folder not found")
        except Exception:
            self.show_toast("Unable to open folder")

    def _on_date_filter_changed(self):
        try:
            # Since we removed Custom Range, we don't need to show/hide date inputs
            # Just reload the print jobs with new filter
            selected_filter = self.filter_date.currentText()
            logger.info(f"Date filter changed to: {selected_filter}")
            
            # Force refresh with real-time calculations - reset scroll on filter change
            self.load_print_jobs(preserve_scroll=False)
            
            # Show toast notification for user feedback
            if selected_filter != 'All':
                self.show_toast(f"Showing jobs for: {selected_filter}")
            
        except Exception as e:
            logger.error(f"Error in date filter change: {e}")
            self.show_toast("Error applying date filter")
    
    def _check_date_change(self):
        """Check if date has changed and refresh filters if needed"""
        try:
            # Only refresh if we're on the print jobs page and have an active date filter
            if (hasattr(self, 'current_page') and self.current_page == 'print_jobs' and 
                hasattr(self, 'filter_date') and self.filter_date.currentText() != 'All'):
                
                # Check if we need to refresh based on current filter
                current_filter = self.filter_date.currentText()
                now_local = datetime.now()  # Use local time for better accuracy
                
                # Refresh if it's a new day and we're using Today/Yesterday filters
                if current_filter in ['Today', 'Yesterday']:
                    # Check if we're in a new day (simple check)
                    if not hasattr(self, '_last_refresh_date') or self._last_refresh_date.date() != now_local.date():
                        logger.info(f"Date changed, refreshing {current_filter} filter")
                        self.load_print_jobs()
                        self._last_refresh_date = now_local
                        
                # Refresh if it's a new week and we're using This Week filter
                elif current_filter == 'This Week':
                    if not hasattr(self, '_last_refresh_week') or self._last_refresh_week.isocalendar()[1] != now_local.isocalendar()[1]:
                        logger.info(f"Week changed, refreshing {current_filter} filter")
                        self.load_print_jobs()
                        self._last_refresh_week = now_local
                        
                # Refresh if it's a new month and we're using This Month filter
                elif current_filter == 'This Month':
                    if not hasattr(self, '_last_refresh_month') or (self._last_refresh_month.year, self._last_refresh_month.month) != (now_local.year, now_local.month):
                        logger.info(f"Month changed, refreshing {current_filter} filter")
                        self.load_print_jobs()
                        self._last_refresh_month = now_local
                        
        except Exception as e:
            logger.error(f"Error in date change check: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    
    def create_settings_page(self):
        """Create Settings as a regular dashboard page with modern two-column layout."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # Header
        header = QHBoxLayout()
        title = QLabel("Settings")
        title.setFont(QFont("Segoe UI", 24, QFont.Bold))
        title.setStyleSheet("color: #111827;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Main content area (single column, full width)
        main_content = QVBoxLayout()
        main_content.setSpacing(20)
        main_content.setContentsMargins(0, 0, 0, 0)

        # Printing Modes card
        mode_card = QFrame()
        mode_card.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setSpacing(8)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        
        # Printing Modes title (plain text header, no container)
        mode_title = QLabel("Printing Modes")
        mode_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        mode_title.setStyleSheet("""
            color: #111827;
            background: transparent;
            border: none;
            padding: 0px;
            margin: 0px;
        """)
        mode_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        mode_layout.addWidget(mode_title)
        
        # Determine current mode state
        is_auto_mode = getattr(self, 'auto_mode', False)
        
        # Auto Mode card
        auto_mode_card = QFrame()
        auto_mode_card.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 10px 16px;
            }
        """)
        auto_mode_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        auto_mode_layout = QHBoxLayout(auto_mode_card)
        auto_mode_layout.setContentsMargins(0, 0, 0, 0)
        auto_mode_layout.setSpacing(12)
        
        # Icon (vertically centered)
        auto_icon = QLabel("🖨️")
        auto_icon.setStyleSheet("font-size: 20px;")
        auto_icon.setAlignment(Qt.AlignVCenter)
        auto_mode_layout.addWidget(auto_icon)
        
        # Mode name only (single line, vertically centered)
        auto_name_label = QLabel("Auto Mode")
        auto_name_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
        auto_name_label.setStyleSheet("color: #111827;")
        auto_name_label.setWordWrap(False)
        auto_name_label.setAlignment(Qt.AlignVCenter)
        auto_mode_layout.addWidget(auto_name_label)
        
        auto_mode_layout.addStretch()
        
        # Toggle switch with visible knob (matching reference image)
        self.auto_mode_toggle_settings = QCheckBox()
        self.auto_mode_toggle_settings.setChecked(is_auto_mode)
        self.auto_mode_toggle_settings.toggled.connect(lambda checked: self.set_auto_mode() if checked else self.set_manual_mode())
        self.auto_mode_toggle_settings.setStyleSheet(TOGGLE_STYLE)
        
        # Add visible black knob
        self.auto_mode_knob_settings = QLabel(self.auto_mode_toggle_settings)
        self.auto_mode_knob_settings.setObjectName("auto_mode_knob_settings")
        self.auto_mode_knob_settings.setStyleSheet(KNOB_STYLE)
        self.auto_mode_knob_settings.resize(20, 20)
        self.auto_mode_knob_settings.move(22 if is_auto_mode else 2, 2)
        
        def _move_auto_knob(checked):
            try:
                if hasattr(self, 'auto_mode_knob_settings') and self._is_alive(self.auto_mode_knob_settings):
                    self.auto_mode_knob_settings.move(22 if checked else 2, 2)
            except Exception:
                pass
        
        _move_auto_knob(self.auto_mode_toggle_settings.isChecked())
        self.auto_mode_toggle_settings.toggled.connect(_move_auto_knob)
        
        auto_mode_layout.addWidget(self.auto_mode_toggle_settings)
        
        mode_layout.addWidget(auto_mode_card)
        
        # Manual Mode card
        manual_mode_card = QFrame()
        manual_mode_card.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 10px 16px;
            }
        """)
        manual_mode_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        manual_mode_layout = QHBoxLayout(manual_mode_card)
        manual_mode_layout.setContentsMargins(0, 0, 0, 0)
        manual_mode_layout.setSpacing(12)
        
        # Icon (vertically centered)
        manual_icon = QLabel("🖨️")
        manual_icon.setStyleSheet("font-size: 20px;")
        manual_icon.setAlignment(Qt.AlignVCenter)
        manual_mode_layout.addWidget(manual_icon)
        
        # Mode name only (single line, vertically centered)
        manual_name_label = QLabel("Manual Mode")
        manual_name_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
        manual_name_label.setStyleSheet("color: #111827;")
        manual_name_label.setWordWrap(False)
        manual_name_label.setAlignment(Qt.AlignVCenter)
        manual_mode_layout.addWidget(manual_name_label)
        
        manual_mode_layout.addStretch()
        
        # Toggle switch with visible knob (matching reference image)
        self.manual_mode_toggle_settings = QCheckBox()
        self.manual_mode_toggle_settings.setChecked(not is_auto_mode)
        self.manual_mode_toggle_settings.toggled.connect(lambda checked: self.set_manual_mode() if checked else self.set_auto_mode())
        self.manual_mode_toggle_settings.setStyleSheet(TOGGLE_STYLE)
        
        # Add visible black knob
        self.manual_mode_knob_settings = QLabel(self.manual_mode_toggle_settings)
        self.manual_mode_knob_settings.setObjectName("manual_mode_knob_settings")
        self.manual_mode_knob_settings.setStyleSheet(KNOB_STYLE)
        self.manual_mode_knob_settings.resize(20, 20)
        self.manual_mode_knob_settings.move(22 if not is_auto_mode else 2, 2)
        
        def _move_manual_knob(checked):
            try:
                if hasattr(self, 'manual_mode_knob_settings') and self._is_alive(self.manual_mode_knob_settings):
                    self.manual_mode_knob_settings.move(22 if checked else 2, 2)
            except Exception:
                pass
        
        _move_manual_knob(self.manual_mode_toggle_settings.isChecked())
        self.manual_mode_toggle_settings.toggled.connect(_move_manual_knob)
        manual_mode_layout.addWidget(self.manual_mode_toggle_settings)
        
        mode_layout.addWidget(manual_mode_card)

        main_content.addWidget(mode_card)

        # Set Pricing card
        pricing_card_main = QFrame()
        pricing_card_main.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        pricing_card_main.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 24px;
            }
        """)
        pricing_group_layout = QVBoxLayout(pricing_card_main)
        pricing_group_layout.setSpacing(16)
        pricing_group_layout.setContentsMargins(0, 0, 0, 0)
        
        # Set Pricing title (plain text header, no container)
        pricing_title = QLabel("Set Pricing")
        pricing_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        pricing_title.setStyleSheet("""
            color: #111827;
            background: transparent;
            border: none;
            padding: 0px;
            margin: 0px;
        """)
        pricing_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        pricing_group_layout.addWidget(pricing_title)

        # Two column layout for B/W and Color
        pricing_columns = QHBoxLayout()
        pricing_columns.setSpacing(24)

        # Left column: Black & White Printing
        bw_card = QFrame()
        bw_card.setStyleSheet("""
            QFrame {
                background-color: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        bw_layout = QVBoxLayout(bw_card)
        bw_layout.setSpacing(18)
        bw_layout.setContentsMargins(0, 0, 0, 0)

        bw_title = QLabel("Black & White Printing")
        bw_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        bw_title.setStyleSheet("color: #111827; margin-bottom: 8px;")
        bw_layout.addWidget(bw_title)

        # B/W Single-sided
        bw_single_layout = QVBoxLayout()
        bw_single_layout.setSpacing(8)
        bw_single_layout.setContentsMargins(0, 0, 0, 0)
        bw_single_label = QLabel("Single-sided (per page)")
        bw_single_label.setFont(QFont("Segoe UI", 11))
        bw_single_label.setStyleSheet("color: #374151; margin-bottom: 6px;")
        bw_single_layout.addWidget(bw_single_label)

        bw_single_input_layout = QHBoxLayout()
        currency_label = QLabel("₹")
        currency_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        currency_label.setStyleSheet("color: #111827; padding-right: 4px;")
        bw_single_input_layout.addWidget(currency_label)

        # Create pricing inputs (Settings set)
        self.settings_bw_single_input = QLineEdit()
        self.settings_bw_single_input.setPlaceholderText("2.0")
        self.settings_bw_single_input.setReadOnly(True)
        self.settings_bw_single_input.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
            QLineEdit:read-only {
                background-color: #f9fafb;
            }
        """)
        bw_single_input_layout.addWidget(self.settings_bw_single_input)
        bw_single_layout.addLayout(bw_single_input_layout)
        bw_layout.addLayout(bw_single_layout)

        # B/W Double-sided
        bw_double_layout = QVBoxLayout()
        bw_double_layout.setSpacing(8)
        bw_double_layout.setContentsMargins(0, 0, 0, 0)
        bw_double_label = QLabel("Double-sided (per page)")
        bw_double_label.setFont(QFont("Segoe UI", 11))
        bw_double_label.setStyleSheet("color: #374151; margin-bottom: 6px;")
        bw_double_layout.addWidget(bw_double_label)

        bw_double_input_layout = QHBoxLayout()
        currency_label2 = QLabel("₹")
        currency_label2.setFont(QFont("Segoe UI", 12, QFont.Bold))
        currency_label2.setStyleSheet("color: #111827; padding-right: 4px;")
        bw_double_input_layout.addWidget(currency_label2)

        self.settings_bw_double_input = QLineEdit()
        self.settings_bw_double_input.setPlaceholderText("1.5")
        self.settings_bw_double_input.setReadOnly(True)
        self.settings_bw_double_input.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
            QLineEdit:read-only {
                background-color: #f9fafb;
            }
        """)
        bw_double_input_layout.addWidget(self.settings_bw_double_input)
        bw_double_layout.addLayout(bw_double_input_layout)
        bw_layout.addLayout(bw_double_layout)

        pricing_columns.addWidget(bw_card, 1)

        # Right column: Color Printing
        color_card = QFrame()
        color_card.setStyleSheet("""
            QFrame {
                background-color: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        color_layout = QVBoxLayout(color_card)
        color_layout.setSpacing(18)
        color_layout.setContentsMargins(0, 0, 0, 0)

        color_title = QLabel("Color Printing")
        color_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        color_title.setStyleSheet("color: #111827; margin-bottom: 8px;")
        color_layout.addWidget(color_title)

        # Color Single-sided
        color_single_layout = QVBoxLayout()
        color_single_layout.setSpacing(8)
        color_single_layout.setContentsMargins(0, 0, 0, 0)
        color_single_label = QLabel("Single-sided (per page)")
        color_single_label.setFont(QFont("Segoe UI", 11))
        color_single_label.setStyleSheet("color: #374151; margin-bottom: 6px;")
        color_single_layout.addWidget(color_single_label)

        color_single_input_layout = QHBoxLayout()
        currency_label3 = QLabel("₹")
        currency_label3.setFont(QFont("Segoe UI", 12, QFont.Bold))
        currency_label3.setStyleSheet("color: #111827; padding-right: 4px;")
        color_single_input_layout.addWidget(currency_label3)

        self.settings_color_single_input = QLineEdit()
        self.settings_color_single_input.setPlaceholderText("10.0")
        self.settings_color_single_input.setReadOnly(True)
        self.settings_color_single_input.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
            QLineEdit:read-only {
                background-color: #f9fafb;
            }
        """)
        color_single_input_layout.addWidget(self.settings_color_single_input)
        color_single_layout.addLayout(color_single_input_layout)
        color_layout.addLayout(color_single_layout)

        # Color Double-sided
        color_double_layout = QVBoxLayout()
        color_double_layout.setSpacing(8)
        color_double_layout.setContentsMargins(0, 0, 0, 0)
        color_double_label = QLabel("Double-sided (per page)")
        color_double_label.setFont(QFont("Segoe UI", 11))
        color_double_label.setStyleSheet("color: #374151; margin-bottom: 6px;")
        color_double_layout.addWidget(color_double_label)

        color_double_input_layout = QHBoxLayout()
        currency_label4 = QLabel("₹")
        currency_label4.setFont(QFont("Segoe UI", 12, QFont.Bold))
        currency_label4.setStyleSheet("color: #111827; padding-right: 4px;")
        color_double_input_layout.addWidget(currency_label4)

        self.settings_color_double_input = QLineEdit()
        self.settings_color_double_input.setPlaceholderText("8.0")
        self.settings_color_double_input.setReadOnly(True)
        self.settings_color_double_input.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
            QLineEdit:read-only {
                background-color: #f9fafb;
            }
        """)
        color_double_input_layout.addWidget(self.settings_color_double_input)
        color_double_layout.addLayout(color_double_input_layout)
        color_layout.addLayout(color_double_layout)

        pricing_columns.addWidget(color_card, 1)
        pricing_group_layout.addLayout(pricing_columns)
        main_content.addWidget(pricing_card_main)
        
        layout.addLayout(main_content)

        # ========== BOTTOM BUTTONS ==========
        footer = QHBoxLayout()
        footer.addStretch()  # Push buttons to the right
        
        # Edit button (match Set Pricing page style)
        edit_settings_btn = QPushButton("Edit")
        edit_settings_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #374151;
                border: 1px solid #d1d5db;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 500;
                font-size: 14px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #f9fafb;
                border-color: #9ca3af;
            }
        """)
        
        # Save button (match Set Pricing page style)
        save_settings_btn = QPushButton("Save")
        save_settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 14px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        save_settings_btn.clicked.connect(self.save_pricing)
        
        # Edit button handler (toggle input editability)
        def toggle_edit_mode():
            is_readonly = self.settings_bw_single_input.isReadOnly()
            self.settings_bw_single_input.setReadOnly(not is_readonly)
            self.settings_bw_double_input.setReadOnly(not is_readonly)
            self.settings_color_single_input.setReadOnly(not is_readonly)
            self.settings_color_double_input.setReadOnly(not is_readonly)
        
        edit_settings_btn.clicked.connect(toggle_edit_mode)
        
        footer.addWidget(edit_settings_btn)
        footer.addSpacing(10)
        footer.addWidget(save_settings_btn)
        
        # Add stretch and move footer inside pricing card
        pricing_group_layout.addStretch()
        pricing_group_layout.addLayout(footer)
        
        # Add page to content stack
        layout.addStretch()

        scroll.setWidget(page)
        self.content_stack.addTab(scroll, "Settings")
        
        # Populate widgets from central state
        self._sync_pricing_ui()
    
    def create_connect_printers_page(self):
        """Create Connect Printers as a regular dashboard page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Page header (matches Dashboard/Settings theme)
        header = QHBoxLayout()
        title = QLabel("Connect Printers")
        title.setFont(QFont("Segoe UI", 24, QFont.Bold))
        title.setStyleSheet("color: #111827;")
        header.addWidget(title)
        header.addStretch()
        
        # Refresh button (matches Settings page button style)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #374151;
                border: 1px solid #d1d5db;
                padding: 8px 16px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #f9fafb;
                border-color: #9ca3af;
            }
            QPushButton:pressed {
                background-color: #f3f4f6;
            }
        """)
        refresh_btn.clicked.connect(lambda: self.refresh_connect_printers_page())
        header.addWidget(refresh_btn)
        
        layout.addLayout(header)
        
        # Status info (subtext below title, matches other pages)
        self.connect_printers_status_label = QLabel("Scanning for available printers...")
        self.connect_printers_status_label.setStyleSheet("color: #6b7280; font-size: 14px; margin-top: 4px; margin-bottom: 0px;")
        layout.addWidget(self.connect_printers_status_label)
        
        # Scroll area for printer cards
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #f1f5f9;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #cbd5e1;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #94a3b8;
            }
        """)
        
        self.connect_printers_scroll_widget = QWidget()
        self.connect_printers_scroll_layout = QVBoxLayout(self.connect_printers_scroll_widget)
        self.connect_printers_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.connect_printers_scroll_layout.setSpacing(16)
        
        scroll_area.setWidget(self.connect_printers_scroll_widget)
        layout.addWidget(scroll_area)
        
        # Store references for later use
        self.connect_printers_page = page
        self.connect_printers_printer_cards = {}
        self.connect_printers_connect_buttons = {}
        self.connect_printers_status_labels = {}
        
        # Resolved printers state - UI renders ONLY from this (None = empty, dict = resolved)
        # Start with a placeholder to prevent initial empty render
        self.connect_printers_resolved_printers = {'printers': [], 'loading': True}
        
        # Track initial load to ensure discovery normalization
        self._connect_printers_initial_load = True
        
        # Load printers initially - this will complete discovery before rendering
        self.load_connect_printers_page()
        
        # Setup timer for real-time updates
        self.setup_connect_printers_timer()
        
        # Add page to content stack
        self.content_stack.addTab(page, "Connect Printers")
        
        return page
    
    def setup_connect_printers_timer(self):
        """Setup timer for real-time updates on Connect Printers page"""
        if not hasattr(self, 'connect_printers_timer'):
            self.connect_printers_timer = QTimer()
            self.connect_printers_timer.timeout.connect(self.update_connect_printers_status)
            self.connect_printers_timer.start(2000)  # Update status every 2 seconds (was 3s)
        
        if not hasattr(self, 'connect_printers_icon_timer'):
            self.connect_printers_icon_timer = QTimer()
            self.connect_printers_icon_timer.timeout.connect(self.update_connect_printers_connection_icons)
            self.connect_printers_icon_timer.start(3000)  # Update connection icons every 3 seconds (was 5s)
        
        # Auto-refresh timer for printer list (backend-driven)
        if not hasattr(self, 'connect_printers_auto_refresh_timer'):
            self.connect_printers_auto_refresh_timer = QTimer()
            self.connect_printers_auto_refresh_timer.timeout.connect(self._auto_refresh_connect_printers)
            # Timer will be started/stopped based on page visibility
        
        # Flag to prevent overlapping refresh calls
        if not hasattr(self, '_connect_printers_refreshing'):
            self._connect_printers_refreshing = False
    
    def load_connect_printers_page(self):
        """Load and display available printers on Connect Printers page"""
        try:
            # Clear all UI references and completely clear the layout (including spacers)
            if hasattr(self, 'connect_printers_printer_cards'):
                self.connect_printers_printer_cards.clear()
            
            if hasattr(self, 'connect_printers_connect_buttons'):
                self.connect_printers_connect_buttons.clear()
            
            if hasattr(self, 'connect_printers_status_labels'):
                self.connect_printers_status_labels.clear()
            
            # Robust layout clearing (removes widgets AND spacers/stretches)
            if hasattr(self, 'connect_printers_scroll_layout'):
                # Reset layout spacing and margins to ensure consistent start position
                self.connect_printers_scroll_layout.setSpacing(16)
                self.connect_printers_scroll_layout.setContentsMargins(0, 0, 0, 0)
                
                # Use takeAt(0) in a loop to remove EVERY item (widgets, spacers, stretches)
                while self.connect_printers_scroll_layout.count():
                    item = self.connect_printers_scroll_layout.takeAt(0)
                    if item:
                        widget = item.widget()
                        if widget:
                            widget.setParent(None)
                            widget.hide()
                            widget.deleteLater()
                        elif item.spacerItem():
                            # Spacers are automatically removed from layout by takeAt(0)
                            pass
            
            
            # Check if printer manager exists
            if not hasattr(self, 'printer_manager') or self.printer_manager is None:
                if hasattr(self, 'connect_printers_status_label'):
                    self.connect_printers_status_label.setText("Error: Printer manager not available")
                logger.error("Printer manager not available")
                # Set resolved state to empty (loading complete, but empty)
                self.connect_printers_resolved_printers = {'printers': [], 'loading': False}
                self._render_from_resolved_printers()
                return
            
            # ============================================================
            # STEP 1: Complete ALL discovery and classification FIRST
            # ============================================================
            
            # On initial load, ALWAYS force synchronous discovery to ensure complete data
            is_initial_load = getattr(self, '_connect_printers_initial_load', False)
            if is_initial_load:
                self._connect_printers_initial_load = False
                
                # Check if we are in application startup phase
                if getattr(self, '_is_initializing', False):
                    # Cold start path - AVOID BLOCKING
                    logger.info("Initial load (startup): Deferring printer discovery to background...")
                    
                    if hasattr(self, 'connect_printers_status_label'):
                        self.connect_printers_status_label.setText("Searching for printers in background...")
                        
                    # Return immediately - do not block!
                    # Discovery will be triggered by _start_background_printer_discovery via QTimer
                    return

                # Force synchronous discovery - don't rely on cached data
                try:
                    logger.info("Initial load: Forcing synchronous printer discovery...")
                    # Force immediate synchronous discovery
                    available_printers = self.printer_manager.thread_safe_discovery.force_refresh()
                    logger.info(f"Initial discovery returned {len(available_printers)} printers")
                except Exception as e:
                    logger.warning(f"Error in initial synchronous discovery: {e}")
                    # Fallback to regular get_available_printers()
                    try:
                        available_printers = self.printer_manager.get_available_printers()
                        logger.info(f"Fallback discovery returned {len(available_printers)} printers")
                    except Exception as e2:
                        logger.error(f"Error in fallback discovery: {e2}")
                        available_printers = []
            else:
                # Regular refresh - use normal discovery
                try:
                    available_printers = self.printer_manager.get_available_printers()
                    logger.info(f"Successfully retrieved {len(available_printers)} printers")
                except Exception as e:
                    logger.error(f"Error getting available printers: {e}")
                    if hasattr(self, 'connect_printers_status_label'):
                        self.connect_printers_status_label.setText(f"Error detecting printers: {str(e)}")
                    # Set resolved state to empty (loading complete, but empty)
                    self.connect_printers_resolved_printers = {'printers': [], 'loading': False}
                    self._render_from_resolved_printers()
                    return
            
            # Validate we got printers data
            if available_printers is None:
                available_printers = []
            
            # Get active printers
            try:
                active_printers = set(self.printer_manager.get_active_printers(
                    self.shopkeeper_data['shop_id']
                ))
            except Exception as e:
                logger.error(f"Error getting active printers: {e}")
                active_printers = set()
            
            # Get default printer
            try:
                default_printer = self.printer_manager.get_default_printer(
                    self.shopkeeper_data['shop_id']
                )
            except Exception as e:
                logger.error(f"Error getting default printer: {e}")
                default_printer = None
            
            # ============================================================
            # STEP 2: Sort printers BEFORE assigning to resolved state
            # ============================================================
            
            def get_printer_sort_key(printer_info):
                printer_name = printer_info['name']
                is_connected = printer_name in active_printers
                is_default = printer_name == default_printer
                # Priority: 0 (Default+Connected), 1 (Connected), 2 (Disconnected)
                if is_connected and is_default:
                    return 0
                elif is_connected:
                    return 1
                else:
                    return 2
            
            sorted_printers = sorted(available_printers, key=get_printer_sort_key)
            
            # ============================================================
            # STEP 3: Atomic update to resolved_printers state
            # ============================================================
            
            # Store metadata needed for rendering
            resolved_data = {
                'printers': sorted_printers,
                'active_printers': active_printers,
                'default_printer': default_printer,
                'connected_count': len(active_printers),
                'total_count': len(available_printers),
                'loading': False  # Mark as complete
            }
            
            # Atomic assignment - UI will render from this
            self.connect_printers_resolved_printers = resolved_data
            
            # ============================================================
            # STEP 4: Render UI from resolved state ONLY
            # ============================================================
            
            self._render_from_resolved_printers()
            
        except Exception as e:
            logger.error(f"Error loading printers: {e}")
            if hasattr(self, 'connect_printers_status_label'):
                self.connect_printers_status_label.setText("Error loading printers")
            # Set resolved state to empty on error (loading complete, but empty)
            self.connect_printers_resolved_printers = {'printers': [], 'loading': False}
            self._render_from_resolved_printers()
    
    def _render_from_resolved_printers(self):
        """Render UI from resolved_printers state ONLY - called after state is fully resolved"""
        # Get resolved data
        resolved_data = getattr(self, 'connect_printers_resolved_printers', None)
        
        # Don't render if still loading (initial state)
        if resolved_data and resolved_data.get('loading'):
            return
        
        # Empty state - show "No printers detected" ONLY when resolved state is empty (not loading)
        if not resolved_data or not resolved_data.get('printers'):
            # Empty state - show "No printers detected" ONLY when resolved state is empty
            no_printers_label = QLabel("No printers detected")
            no_printers_label.setStyleSheet("""
                QLabel {
                    color: #6b7280;
                    font-size: 14px;
                    padding: 40px;
                    text-align: center;
                }
            """)
            no_printers_label.setAlignment(Qt.AlignCenter)
            if hasattr(self, 'connect_printers_scroll_layout'):
                self.connect_printers_scroll_layout.addWidget(no_printers_label)
            if hasattr(self, 'connect_printers_status_label'):
                self.connect_printers_status_label.setText("No printers detected on this system")
            return
        
        # Render from resolved state
        sorted_printers = resolved_data['printers']
        active_printers = resolved_data['active_printers']
        default_printer = resolved_data['default_printer']
        connected_count = resolved_data['connected_count']
        total_count = resolved_data['total_count']
        
        # Create printer cards in sorted order
        for printer_info in sorted_printers:
            card = self.create_connect_printers_card(printer_info, active_printers, default_printer)
            if hasattr(self, 'connect_printers_scroll_layout'):
                self.connect_printers_scroll_layout.addWidget(card)
                self.connect_printers_printer_cards[printer_info['name']] = card
        
        # Add stretch to push cards to top
        if hasattr(self, 'connect_printers_scroll_layout'):
            self.connect_printers_scroll_layout.addStretch()
        
        # Update status
        if hasattr(self, 'connect_printers_status_label'):
            self.connect_printers_status_label.setText(f"Found {total_count} printer(s) • {connected_count} connected")
    
    def refresh_connect_printers_page(self):
        """Refresh printer discovery on Connect Printers page"""
        # Prevent overlapping refresh calls
        if hasattr(self, '_connect_printers_refreshing') and self._connect_printers_refreshing:
            return
        
        try:
            self._connect_printers_refreshing = True
            if hasattr(self, 'connect_printers_status_label'):
                self.connect_printers_status_label.setText("Scanning for printers (including WiFi)...")
            self.printer_manager.refresh_printer_discovery()
            self.load_connect_printers_page()
        except Exception as e:
            logger.error(f"Error refreshing printers: {e}")
            if hasattr(self, 'connect_printers_status_label'):
                self.connect_printers_status_label.setText("Error refreshing printers")
        finally:
            self._connect_printers_refreshing = False
    
    def _auto_refresh_connect_printers(self):
        """Auto-refresh printer list (called by timer, only when page is active)"""
        # Only refresh if Connect Printers page is currently active
        if hasattr(self, 'current_page') and self.current_page == "connect_printers":
            # Check if refresh is already in progress to prevent overlapping calls
            if not (hasattr(self, '_connect_printers_refreshing') and self._connect_printers_refreshing):
                self.refresh_connect_printers_page()
    
    def create_connect_printers_card(self, printer_info, active_printers, default_printer):
        """Create a modern printer card for Connect Printers page"""
        card = QFrame()
        card.setFrameStyle(QFrame.StyledPanel)
        
        printer_name = printer_info['name']
        is_connected = printer_name in active_printers
        is_default = printer_name == default_printer
        status = printer_info.get('status', 'Unknown')
        connection_type = printer_info.get('connection_type', 'Unknown')
        
        # Card styling - matches Settings page cards (border-radius: 8px, padding: 20px)
        if is_connected:
            # Highlight all connected printers with the distinctive blue border
            card.setStyleSheet("""
                QFrame {
                    background-color: #ffffff;
                    border: 2px solid #2563EB;
                    border-radius: 8px;
                    padding: 20px;
                }
            """)
        else:
            # Standard border for disconnected printers
            card.setStyleSheet("""
                QFrame {
                    background-color: #ffffff;
                    border: 1px solid #e5e7eb;
                    border-radius: 8px;
                    padding: 20px;
                }
            """)
        
        # Main layout - horizontal row layout
        main_layout = QHBoxLayout(card)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)
        
        # Left side content (icon + name + status)
        left_content = QHBoxLayout()
        left_content.setSpacing(12)
        
        # Connection icon (printer emoji)
        icon_label = QLabel("🖨️")
        icon_label.setStyleSheet("font-size: 20px;")
        icon_label.setObjectName(f"icon_{printer_name}")
        left_content.addWidget(icon_label)
        
        # Printer info (name + status)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        
        # Printer name
        name_label = QLabel(printer_name)
        name_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        name_label.setStyleSheet("color: #111827;")
        info_layout.addWidget(name_label)
        
        # Status and connection info
        status_layout = QHBoxLayout()
        status_layout.setSpacing(8)
        
        # Status indicator
        status_color = "#10b981" if status == "Online" else "#ef4444"
        status_dot = QLabel("●")
        status_dot.setStyleSheet(f"color: {status_color}; font-size: 12px;")
        status_dot.setObjectName(f"status_dot_{printer_name}")
        status_layout.addWidget(status_dot)
        
        status_text = QLabel(status)
        status_text.setStyleSheet(f"color: {status_color}; font-size: 11px; font-weight: 500;")
        status_text.setObjectName(f"status_text_{printer_name}")
        status_layout.addWidget(status_text)
        
        # Store status label reference
        if not hasattr(self, 'connect_printers_status_labels'):
            self.connect_printers_status_labels = {}
        self.connect_printers_status_labels[printer_name] = {
            'dot': status_dot,
            'text': status_text
        }
        
        # Connection type
        if connection_type == 'WiFi/Ethernet':
            if 'ip_address' in printer_info:
                conn_text = QLabel(f"• {connection_type} ({printer_info['ip_address']})")
            elif 'discovery_method' in printer_info:
                conn_text = QLabel(f"• {connection_type} ({printer_info['discovery_method']})")
            else:
                conn_text = QLabel(f"• {connection_type}")
        else:
            conn_text = QLabel(f"• {connection_type}")
        
        conn_text.setStyleSheet("color: #6b7280; font-size: 11px;")
        conn_text.setObjectName(f"conn_type_{printer_name}")
        status_layout.addWidget(conn_text)
        
        # Default indicator
        if is_default:
            default_text = QLabel("• Default")
            default_text.setStyleSheet("color: #6b7280; font-size: 11px; font-weight: 500;")
            status_layout.addWidget(default_text)
        
        status_layout.addStretch()
        info_layout.addLayout(status_layout)
        
        left_content.addLayout(info_layout)
        left_content.addStretch()
        
        # Add left content to main layout
        main_layout.addLayout(left_content)
        
        # Right side - Action buttons (matches Settings page button style)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        if is_connected:
            # Set as default button (only if not already default)
            if not is_default:
                default_btn = QPushButton("Set as Default")
                default_btn.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        color: #374151;
                        border: 1px solid #d1d5db;
                        padding: 10px 20px;
                        border-radius: 6px;
                        font-weight: 500;
                        font-size: 14px;
                        min-width: 80px;
                    }
                    QPushButton:hover {
                        background-color: #f9fafb;
                        border-color: #9ca3af;
                    }
                """)
                default_btn.clicked.connect(lambda: self.set_connect_printers_default(printer_name))
                button_layout.addWidget(default_btn)
            
            # Disconnect button
            disconnect_btn = QPushButton("Disconnect")
            disconnect_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3b82f6;
                    color: #ffffff;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 6px;
                    font-weight: 600;
                    font-size: 14px;
                    min-width: 80px;
                }
                QPushButton:hover {
                    background-color: #2563eb;
                }
            """)
            disconnect_btn.clicked.connect(lambda: self.disconnect_connect_printers_printer(printer_name))
            button_layout.addWidget(disconnect_btn)
        else:
            # Connect button
            connect_btn = QPushButton("Connect")
            connect_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3b82f6;
                    color: #ffffff;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 6px;
                    font-weight: 600;
                    font-size: 14px;
                    min-width: 80px;
                }
                QPushButton:hover {
                    background-color: #2563eb;
                }
                QPushButton:disabled {
                    background-color: #9ca3af;
                    color: #ffffff;
                    border: none;
                }
            """)
            connect_btn.setEnabled(status == "Online")
            connect_btn.setObjectName(f"connect_btn_{printer_name}")
            connect_btn.clicked.connect(lambda: self.connect_connect_printers_printer(printer_name))
            button_layout.addWidget(connect_btn)
            
            # Store Connect button reference
            if not hasattr(self, 'connect_printers_connect_buttons'):
                self.connect_printers_connect_buttons = {}
            self.connect_printers_connect_buttons[printer_name] = connect_btn
        
        # Add button layout to main layout
        main_layout.addLayout(button_layout)
        
        # Right-click context menu for Printer Settings
        card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda pos, pname=printer_name: self._show_printer_settings_menu(pos, pname, card)
        )
        
        return card
    
    def connect_connect_printers_printer(self, printer_name):
        """Connect a printer from Connect Printers page"""
        try:
            success, message = self.printer_manager.activate_printer(
                self.shopkeeper_data['shop_id'], 
                printer_name, 
                make_default=False
            )
            
            if success:
                self.load_connect_printers_page()
                self.load_job_printers()
                if self.isVisible():
                    self.show_success_toast(f"Printer {printer_name} Connected Successfully")
            else:
                QMessageBox.warning(self, "Connection Failed", message)
                
        except Exception as e:
            logger.error(f"Error connecting printer: {e}")
            QMessageBox.warning(self, "Error", f"Failed to connect: {str(e)}")
    
    def disconnect_connect_printers_printer(self, printer_name):
        """Disconnect a printer from Connect Printers page"""
        try:
            success, message = self.printer_manager.deactivate_printer(
                self.shopkeeper_data['shop_id'], 
                printer_name
            )
            
            if success:
                self.load_connect_printers_page()
                self.load_job_printers()
                if self.isVisible():
                    self.show_success_toast(f"Disconnected from {printer_name}")
            else:
                QMessageBox.warning(self, "Disconnection Failed", message)
                
        except Exception as e:
            logger.error(f"Error disconnecting printer: {e}")
            QMessageBox.warning(self, "Error", f"Failed to disconnect: {str(e)}")
    
    def set_connect_printers_default(self, printer_name):
        """Set a printer as default from Connect Printers page"""
        try:
            success, message = self.printer_manager.set_default_printer(
                self.shopkeeper_data['shop_id'], 
                printer_name
            )
            
            if success:
                self.load_connect_printers_page()
                self.load_job_printers()
                if self.isVisible():
                    self.show_success_toast(f"{printer_name} is now the default printer")
            else:
                QMessageBox.warning(self, "Set Default Failed", message)
                
        except Exception as e:
            logger.error(f"Error setting default printer: {e}")
            QMessageBox.warning(self, "Error", f"Failed to set default: {str(e)}")

    def _show_printer_settings_menu(self, pos, printer_name, card):
        """Show right-click context menu for printer settings"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                color: #111827;
                padding: 8px 20px;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
            }
            QMenu::item:selected {
                background-color: #3b82f6;
                color: #ffffff;
                border-radius: 4px;
            }
        """)
        settings_action = QAction("Printer Settings", self)
        settings_action.triggered.connect(lambda: self._open_printer_settings_dialog(printer_name))
        menu.addAction(settings_action)
        self._suspend_jobs_refresh = True
        menu.exec_(card.mapToGlobal(pos))
        self._suspend_jobs_refresh = False

    def _open_printer_settings_dialog(self, printer_name):
        """Open printer capability settings dialog"""
        try:
            from shared.database import Printer, SessionLocal
            
            # Load current saved config
            db = SessionLocal()
            printer_record = db.query(Printer).filter(
                Printer.printer_name == printer_name,
                Printer.shop_id == self.shopkeeper_data['shop_id']
            ).first()
            
            current_duplex = getattr(printer_record, 'duplex_override', None) if printer_record else None
            current_color = getattr(printer_record, 'color_override', None) if printer_record else None
            db.close()
            
            # Create dialog
            dialog = QDialog(self)
            dialog.setWindowTitle("Printer Settings")
            dialog.setFixedWidth(380)
            dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
            dialog.setStyleSheet("""
                QDialog { background-color: #ffffff; }
                QLabel { font-family: 'Segoe UI', sans-serif; }
                QRadioButton { font-size: 13px; font-family: 'Segoe UI', sans-serif; padding: 4px; }
            """)
            
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(24, 20, 24, 20)
            layout.setSpacing(16)
            
            # Title
            title = QLabel("⚙️  Printer Settings")
            title.setFont(QFont("Segoe UI", 15, QFont.Bold))
            title.setStyleSheet("color: #111827;")
            layout.addWidget(title)
            
            # Printer name
            pname_label = QLabel(printer_name)
            pname_label.setStyleSheet("color: #6b7280; font-size: 13px;")
            layout.addWidget(pname_label)
            
            # Divider
            div = QFrame()
            div.setFixedHeight(1)
            div.setStyleSheet("background-color: #e5e7eb;")
            layout.addWidget(div)
            
            # Auto-detect note
            note = QLabel("⚠️  Settings auto-detected. Change only if needed.")
            note.setStyleSheet("""
                background-color: #fef3c7;
                color: #92400e;
                border: 1px solid #fde68a;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 12px;
            """)
            note.setWordWrap(True)
            layout.addWidget(note)
            
            # --- DUPLEX SECTION ---
            duplex_label = QLabel("Duplex Mode:")
            duplex_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
            duplex_label.setStyleSheet("color: #111827; margin-top: 4px;")
            layout.addWidget(duplex_label)
            
            from PyQt5.QtWidgets import QButtonGroup
            duplex_group = QButtonGroup(dialog)
            
            duplex_auto = QRadioButton("Auto Detect")
            duplex_on = QRadioButton("Force Enable")
            duplex_off = QRadioButton("Disable")
            
            for rb in [duplex_auto, duplex_on, duplex_off]:
                rb.setStyleSheet("QRadioButton { color: #374151; }")
                duplex_group.addButton(rb)
                layout.addWidget(rb)
            
            # Set current value
            if current_duplex is None:
                duplex_auto.setChecked(True)
            elif current_duplex:
                duplex_on.setChecked(True)
            else:
                duplex_off.setChecked(True)
            
            # --- COLOR SECTION ---
            color_label = QLabel("Color Mode:")
            color_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
            color_label.setStyleSheet("color: #111827; margin-top: 8px;")
            layout.addWidget(color_label)
            
            color_group = QButtonGroup(dialog)
            
            color_auto = QRadioButton("Auto Detect")
            color_on = QRadioButton("Force Color")
            color_off = QRadioButton("Force B&W Only")
            
            for rb in [color_auto, color_on, color_off]:
                rb.setStyleSheet("QRadioButton { color: #374151; }")
                color_group.addButton(rb)
                layout.addWidget(rb)
            
            # Set current value
            if current_color is None:
                color_auto.setChecked(True)
            elif current_color:
                color_on.setChecked(True)
            else:
                color_off.setChecked(True)
            
            # Divider
            div2 = QFrame()
            div2.setFixedHeight(1)
            div2.setStyleSheet("background-color: #e5e7eb; margin-top: 4px;")
            layout.addWidget(div2)
            
            # Buttons
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            
            cancel_btn = QPushButton("Cancel")
            cancel_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f3f4f6;
                    color: #374151;
                    border: 1px solid #d1d5db;
                    padding: 8px 20px;
                    border-radius: 6px;
                    font-weight: 500;
                    font-size: 13px;
                }
                QPushButton:hover { background-color: #e5e7eb; }
            """)
            cancel_btn.clicked.connect(dialog.reject)
            
            save_btn = QPushButton("Save")
            save_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3b82f6;
                    color: #ffffff;
                    border: none;
                    padding: 8px 20px;
                    border-radius: 6px;
                    font-weight: 600;
                    font-size: 13px;
                }
                QPushButton:hover { background-color: #2563eb; }
            """)
            
            def save_settings():
                import traceback
                try:
                    from shared.database import Printer, SessionLocal
                    new_duplex = None if duplex_auto.isChecked() else (True if duplex_on.isChecked() else False)
                    new_color = None if color_auto.isChecked() else (True if color_on.isChecked() else False)
                    
                    db2 = SessionLocal()
                    record = db2.query(Printer).filter(
                        Printer.printer_name == printer_name,
                        Printer.shop_id == self.shopkeeper_data['shop_id']
                    ).first()
                    if record:
                        record.duplex_override = new_duplex
                        record.color_override = new_color
                        db2.commit()
                        logger.info(f"Saved printer settings for '{printer_name}': duplex={new_duplex}, color={new_color}")
                    else:
                        logger.warning(f"Printer record not found for '{printer_name}' — settings not saved")
                    db2.close()
                    
                    # Full cache reset
                    self.printer_manager.printer_capabilities = {}
                    
                    self.show_success_toast(f"Settings saved for {printer_name}")
                    dialog.accept()
                except Exception as e:
                    traceback.print_exc()
                    logger.error(f"Error saving printer settings: {e}")
                    QMessageBox.warning(dialog, "Error", f"Failed to save: {str(e)}")
            
            save_btn.clicked.connect(save_settings)
            btn_layout.addWidget(cancel_btn)
            btn_layout.addSpacing(8)
            btn_layout.addWidget(save_btn)
            layout.addLayout(btn_layout)
            
            dialog.exec_()
            
        except Exception as e:
            logger.error(f"Error opening printer settings dialog: {e}")
            QMessageBox.warning(self, "Error", f"Failed to open settings: {str(e)}")
    
    def update_connect_printers_status(self):
        """Update printer status in real-time on Connect Printers page"""
        try:
            # Only update if page is visible
            if hasattr(self, 'connect_printers_page') and self.connect_printers_page and self.connect_printers_page.isVisible():
                self.update_connect_printers_status_efficiently()
        except Exception as e:
            logger.error(f"Error updating printer status: {e}")
    
    def update_connect_printers_status_efficiently(self):
        """Efficiently update printer status without reloading entire UI"""
        try:
            # Handle any new printers
            self.handle_connect_printers_new_printers()
            
            # Get current printer status
            available_printers = self.printer_manager.get_available_printers()
            
            # Get active printers
            try:
                active_printers = set(
                    self.printer_manager.get_active_printers(
                        self.shopkeeper_data['shop_id']
                    )
                )
            except Exception:
                active_printers = set()
            
            # Create status map
            printer_status_map = {}
            for printer in available_printers:
                name = printer.get('name')
                status = printer.get('status', 'Unknown')
                printer_status_map[name] = status
            
            # Update each existing printer card's status
            for printer_name, status in printer_status_map.items():
                self.update_connect_printers_single_status(printer_name, status)
                
        except Exception as e:
            logger.error(f"Error in efficient printer status update: {e}")
    
    def update_connect_printers_single_status(self, printer_name, status):
        """Update status for a single printer on Connect Printers page"""
        try:
            # Update status labels
            if hasattr(self, 'connect_printers_status_labels') and printer_name in self.connect_printers_status_labels:
                status_labels = self.connect_printers_status_labels[printer_name]
                status_color = "#10b981" if status == "Online" else "#ef4444"
                
                if self._is_alive(status_labels['dot']):
                    status_labels['dot'].setStyleSheet(f"color: {status_color}; font-size: 12px;")
                
                if self._is_alive(status_labels['text']):
                    status_labels['text'].setText(status)
                    status_labels['text'].setStyleSheet(f"color: {status_color}; font-size: 11px; font-weight: 500;")
            
            # Update Connect button state
            if hasattr(self, 'connect_printers_connect_buttons') and printer_name in self.connect_printers_connect_buttons:
                connect_btn = self.connect_printers_connect_buttons[printer_name]
                if self._is_alive(connect_btn):
                    is_online = status == "Online"
                    connect_btn.setEnabled(is_online)
                    if is_online:
                        connect_btn.setText("Connect")
                        connect_btn.setToolTip("Click to connect this printer")
                    else:
                        connect_btn.setText("Offline")
                        connect_btn.setToolTip("Printer is offline - cannot connect")
                        
        except Exception as e:
            logger.error(f"Error updating single printer status for {printer_name}: {e}")
    
    def handle_connect_printers_new_printers(self):
        """Handle newly discovered printers on Connect Printers page"""
        try:
            available_printers = self.printer_manager.get_available_printers()
            if not hasattr(self, 'connect_printers_printer_cards'):
                self.connect_printers_printer_cards = {}
            current_printer_names = set(self.connect_printers_printer_cards.keys())
            new_printer_names = set(printer['name'] for printer in available_printers)
            
            # Find new printers
            newly_discovered = new_printer_names - current_printer_names
            
            if newly_discovered:
                logger.info(f"Found {len(newly_discovered)} new printers: {newly_discovered}")
                
                # Get active printers and default printer
                try:
                    active_printers = set(self.printer_manager.get_active_printers(
                        self.shopkeeper_data['shop_id']
                    ))
                except Exception:
                    active_printers = set()
                
                try:
                    default_printer = self.printer_manager.get_default_printer(
                        self.shopkeeper_data['shop_id']
                    )
                except Exception:
                    default_printer = None
                
                # Create cards for new printers
                for printer_info in available_printers:
                    if printer_info['name'] in newly_discovered:
                        card = self.create_connect_printers_card(printer_info, active_printers, default_printer)
                        if hasattr(self, 'connect_printers_scroll_layout'):
                            # Insert before stretch widget
                            count = self.connect_printers_scroll_layout.count()
                            if count > 0:
                                self.connect_printers_scroll_layout.insertWidget(count - 1, card)
                            else:
                                self.connect_printers_scroll_layout.addWidget(card)
                            self.connect_printers_printer_cards[printer_info['name']] = card
                
                # Update status label
                connected_count = len(active_printers)
                if hasattr(self, 'connect_printers_status_label'):
                    self.connect_printers_status_label.setText(f"Found {len(available_printers)} printer(s) • {connected_count} connected")
                
        except Exception as e:
            logger.error(f"Error handling new printers: {e}")
    
    def update_connect_printers_connection_icons(self):
        """Update connection icons for all printer cards on Connect Printers page"""
        try:
            # PERFORMANCE GUARD: Only update icons if Connect Printers page is currently visible
            if not (hasattr(self, 'current_page') and self.current_page == "connect_printers"):
                return
                
            if not hasattr(self, 'connect_printers_printer_cards'):
                return
                
            for printer_name, card in self.connect_printers_printer_cards.items():
                if not self._is_alive(card):
                    continue
                    
                # Get connection info
                conn_info = self.printer_manager.get_printer_connection_info(printer_name)
                current_connection_type = conn_info['connection_type']
                is_dual_connection = conn_info['is_dual_connection']
                
                # Update icon
                icon_label = card.findChild(QLabel, f"icon_{printer_name}")
                if icon_label:
                    icon_label.setText("🖨️")
                
                # Update connection type text
                conn_label = card.findChild(QLabel, f"conn_type_{printer_name}")
                if conn_label:
                    if is_dual_connection:
                        conn_text = f"• {current_connection_type} (Dual USB/WiFi)"
                    else:
                        conn_text = f"• {current_connection_type}"
                    conn_label.setText(conn_text)
                    
        except Exception as e:
            logger.error(f"Error updating connection icons: {e}")
    
    
    


    @safe_ui_action("ADD_PRINTER_DIALOG")
    def show_add_printer_dialog(self):
        """Show modal dialog to add printers."""
        available = self.printer_manager.get_available_printers()
        if not available:
            QMessageBox.information(self, "Printers", "No printers detected by system.")
            return
        
        dialog = AddPrinterDialog(available, self)
        if dialog.exec_() == QDialog.Accepted:
            connected_count = 0
            for printer in dialog.selected_printers:
                success, message = self.printer_manager.activate_printer(
                    self.shopkeeper_data['shop_id'], 
                    printer['name'], 
                    make_default=False
                )
                if success:
                    connected_count += 1
                    # Show success message for each connected printer
                    QMessageBox.information(self, "Success", f"Printer {printer['name']} Connected Successfully")
                else:
                    logger.warning(f"Failed to activate printer {printer['name']}: {message}")
            
            # Set first added printer as default if no default exists
            default_name = self.printer_manager.get_default_printer(self.shopkeeper_data['shop_id'])
            if not default_name and dialog.selected_printers:
                first_printer = dialog.selected_printers[0]['name']
                self.printer_manager.set_default_printer(self.shopkeeper_data['shop_id'], first_printer)
            
            self.load_job_printers()


    @safe_ui_action("REMOVE_PRINTER")
    def remove_printer(self, printer_name, *args, **kwargs):
        """Remove a printer."""
        reply = QMessageBox.question(
            self, 
            "Remove Printer", 
            f"Are you sure you want to remove '{printer_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success, message = self.printer_manager.deactivate_printer(self.shopkeeper_data['shop_id'], printer_name)
            if success:
                # If removed printer was current, clear it
                try:
                    if self.printer_manager.current_printer == printer_name:
                        self.printer_manager.current_printer = self.printer_manager.get_default_printer(self.shopkeeper_data['shop_id'])
                except Exception:
                    pass
                # Refresh UI lists and combos consistently
                self.load_job_printers()
                self.show_success_toast(f"Printer '{printer_name}' has been removed")
            else:
                # Soft-fail: show warning but do not raise
                try:
                    logger.warning(f"Remove printer failed for '{printer_name}': {message}")
                except Exception:
                    pass
                QMessageBox.warning(self, "Error", message or "Unable to remove printer")

    def show_success_toast(self, message):
        """Show a success toast message on the dashboard"""
        try:
            # Only show if dashboard is visible
            if not self.isVisible():
                return
            
            # Create a temporary label for toast (as child of dashboard)
            toast = QLabel(message, self)
            toast.setStyleSheet("""
                QLabel {
                    background-color: #27ae60;
                    color: white;
                    padding: 10px 20px;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 14px;
                }
            """)
            toast.setAlignment(Qt.AlignCenter)
            toast.setWordWrap(True)
            
            # Calculate position relative to dashboard window
            toast_width = 400
            toast_height = 60
            x = (self.width() - toast_width) // 2
            y = 50
            toast.setGeometry(x, y, toast_width, toast_height)
            toast.raise_()  # Bring to front
            toast.show()
            
            # Auto-hide after 3 seconds
            QTimer.singleShot(3000, toast.close)
            
        except Exception as e:
            logger.error(f"Error showing toast: {e}")


    def load_job_printers(self):
        """Load active printers into job printer combo."""
        try:
            self.job_printer_combo.clear()
            active_names = self.printer_manager.get_active_printers(self.shopkeeper_data['shop_id'])
            default_name = self.printer_manager.get_default_printer(self.shopkeeper_data['shop_id'])
            
            if not active_names:
                self.job_printer_combo.addItem("No printers connected")
                return
            
            # Get available printers to look up display_name for UI
            available_printers_raw = self.printer_manager.get_available_printers()
            display_name_map = {p.get('name'): p.get('display_name', p.get('name')) for p in available_printers_raw if p.get('name')}
            
            for printer_name in active_names:
                friendly_name = display_name_map.get(printer_name, printer_name)
                display_name = f"{friendly_name}"
                if printer_name == default_name:
                    display_name = f"{friendly_name} (Default)"
                self.job_printer_combo.addItem(display_name, printer_name)
                # Set tooltip with full name
                idx = self.job_printer_combo.count() - 1
                self.job_printer_combo.setItemData(idx, printer_name, Qt.ToolTipRole)
            
            # Select default printer
            if default_name:
                for i in range(self.job_printer_combo.count()):
                    if self.job_printer_combo.itemData(i) == default_name:
                        self.job_printer_combo.setCurrentIndex(i)
                        break
                        
        except Exception as e:
            logger.error(f"Error loading job printers: {e}")

    def on_job_printer_changed(self, text):
        """Handle job printer selection change."""
        try:
            if hasattr(self, "auto_select_checkbox") and not self.auto_select_checkbox.isChecked():
                # Manual mode - use selected printer
                current_data = self.job_printer_combo.currentData()
                if current_data:
                    self.printer_manager.current_printer = current_data
                    if hasattr(self, "printer_status_label"):
                        self.printer_status_label.setText(f"Selected printer: {current_data}")
                else:
                    # No selection -> clear current to force prompt on print
                    self.printer_manager.current_printer = None
        except Exception as e:
            logger.error(f"Error handling job printer change: {e}")
    
    
    
    def test_printer(self):
        """Test printer connection"""
        try:
            success, message = self.printer_manager.test_printer()
            
            if success:
                QMessageBox.information(self, "Success", message)
            else:
                QMessageBox.warning(self, "Error", message)
                
        except Exception as e:
            logger.error(f"Error testing printer: {e}")
            QMessageBox.warning(self, "Error", f"Printer test failed: {str(e)}")

    
    def set_auto_mode(self):
        """Set printing mode to automatic"""
        self.auto_mode = True
        if hasattr(self, "auto_mode_btn"):
            self._safe_set_checked(self.auto_mode_btn, True)
        if hasattr(self, "manual_mode_btn"):
            self._safe_set_checked(self.manual_mode_btn, False)
        if hasattr(self, "auto_mode_toggle_settings"):
            try:
                was_blocked = self.auto_mode_toggle_settings.blockSignals(True)
                self.auto_mode_toggle_settings.setChecked(True)
                self.auto_mode_toggle_settings.blockSignals(was_blocked)
                # Update knob position
                if hasattr(self, 'auto_mode_knob_settings') and self._is_alive(self.auto_mode_knob_settings):
                    self.auto_mode_knob_settings.move(22, 2)
            except Exception:
                pass
        if hasattr(self, "manual_mode_toggle_settings"):
            try:
                was_blocked = self.manual_mode_toggle_settings.blockSignals(True)
                self.manual_mode_toggle_settings.setChecked(False)
                self.manual_mode_toggle_settings.blockSignals(was_blocked)
                # Update knob position
                if hasattr(self, 'manual_mode_knob_settings') and self._is_alive(self.manual_mode_knob_settings):
                    self.manual_mode_knob_settings.move(2, 2)
            except Exception:
                pass
        if hasattr(self, "auto_mode_toggle"):
            try:
                was_blocked = self.auto_mode_toggle.blockSignals(True)
            except Exception:
                was_blocked = False
            try:
                self.auto_mode_toggle.setChecked(True)
            finally:
                try:
                    self.auto_mode_toggle.blockSignals(was_blocked)
                except Exception:
                    pass
            # Ensure the toggle's knob visually updates even if signal was blocked
            try:
                if hasattr(self, "auto_mode_knob") and self._is_alive(self.auto_mode_knob):
                    self.auto_mode_knob.move(22, 2)
            except Exception:
                pass
        if hasattr(self, "mode_status_label"):
            self._safe_set_text(self.mode_status_label, "Mode: Auto")
            try:
                if self._is_alive(self.mode_status_label):
                    self.mode_status_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
            except Exception:
                pass
        if hasattr(self, "mode_description_label"):
            self._safe_set_text(self.mode_description_label, "Auto: Jobs print automatically when they arrive")
        
        logger.info("Switched to Auto printing mode")
        
        # Check for pending jobs and print them automatically
        self.check_and_print_pending_jobs()
    
    def set_manual_mode(self):
        """Set printing mode to manual"""
        self.auto_mode = False
        if hasattr(self, "auto_mode_btn"):
            self._safe_set_checked(self.auto_mode_btn, False)
        if hasattr(self, "manual_mode_btn"):
            self._safe_set_checked(self.manual_mode_btn, True)
        if hasattr(self, "auto_mode_toggle_settings"):
            try:
                was_blocked = self.auto_mode_toggle_settings.blockSignals(True)
                self.auto_mode_toggle_settings.setChecked(False)
                self.auto_mode_toggle_settings.blockSignals(was_blocked)
                # Update knob position
                if hasattr(self, 'auto_mode_knob_settings') and self._is_alive(self.auto_mode_knob_settings):
                    self.auto_mode_knob_settings.move(2, 2)
            except Exception:
                pass
        if hasattr(self, "manual_mode_toggle_settings"):
            try:
                was_blocked = self.manual_mode_toggle_settings.blockSignals(True)
                self.manual_mode_toggle_settings.setChecked(True)
                self.manual_mode_toggle_settings.blockSignals(was_blocked)
                # Update knob position
                if hasattr(self, 'manual_mode_knob_settings') and self._is_alive(self.manual_mode_knob_settings):
                    self.manual_mode_knob_settings.move(22, 2)
            except Exception:
                pass
        if hasattr(self, "auto_mode_toggle"):
            try:
                was_blocked = self.auto_mode_toggle.blockSignals(True)
            except Exception:
                was_blocked = False
            try:
                self.auto_mode_toggle.setChecked(False)
            finally:
                try:
                    self.auto_mode_toggle.blockSignals(was_blocked)
                except Exception:
                    pass
            # Ensure the toggle's knob visually updates even if signal was blocked
            try:
                if hasattr(self, "auto_mode_knob") and self._is_alive(self.auto_mode_knob):
                    self.auto_mode_knob.move(2, 2)
            except Exception:
                pass
        if hasattr(self, "mode_status_label"):
            self._safe_set_text(self.mode_status_label, "Mode: Manual")
            try:
                if self._is_alive(self.mode_status_label):
                    self.mode_status_label.setStyleSheet("font-weight: bold; color: #2196F3;")
            except Exception:
                pass
        if hasattr(self, "mode_description_label"):
            self._safe_set_text(self.mode_description_label, "Manual: Click 'Print' to print each job")
        
        logger.info("Switched to Manual printing mode")
    
    @safe_ui_action("SETUP_SOCKETIO")
    def setup_websocket(self):
        """Setup SocketIO connection with fallback to polling - non-blocking"""
        try:
            # Initialize thread-safe SocketIO manager
            self.websocket_client = ThreadSafeSocketIOManager(
                shop_id=self.shopkeeper_data['shop_id'],
                server_url=EZPRINT_BASE_URL,
                token=self.session_token
            )
            
            # Start thread-safe SocketIO client
            self.websocket_client.start(callback=self._on_websocket_message)
            
            # Set initial status
            if hasattr(self, "connection_status_label"):
                self.connection_status_label.setText("Connecting...")
            
            # Start polling as fallback after a short delay
            QTimer.singleShot(3000, self.start_fallback_polling)
            
            # Setup periodic SocketIO reconnection attempts (if needed, but manager handles it)
            # self.setup_websocket_reconnection()
            
        except Exception as e:
            logger.error(f"WebSocket initialization failed: {e}")
            # Ensure fallback polling starts immediately if WebSocket fails
            self.thread_safe_signal.emit("start_polling_fallback", None)
            if hasattr(self, "connection_status_label"):
                self.connection_status_label.setText("Live updates unavailable, using polling")
    
    def setup_polling_timer(self):
        """Setup fallback polling timer for when WebSocket is unavailable"""
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.load_print_jobs)
        self.poll_timer.setSingleShot(False)
        # Don't start immediately - only start when WebSocket fails
    
    def start_polling_fallback(self):
        """Start polling fallback from main thread"""
        if hasattr(self, 'poll_timer') and not self.poll_timer.isActive():
            self.poll_timer.start(5000)  # Start polling every 5 seconds
            if hasattr(self, "connection_status_label"):
                self.connection_status_label.setText("Live updates unavailable, using polling")
            logger.info("Started fallback polling for print jobs")
    
    def stop_polling_fallback(self):
        """Stop polling fallback from main thread"""
        if hasattr(self, 'poll_timer') and self.poll_timer.isActive():
            self.poll_timer.stop()
            logger.info("Stopped fallback polling for print jobs")
    
    def setup_websocket_reconnection(self):
        """Setup periodic WebSocket reconnection attempts"""
        self.websocket_reconnect_timer = QTimer()
        self.websocket_reconnect_timer.timeout.connect(self.attempt_websocket_reconnection)
        self.websocket_reconnect_timer.start(30000)  # Try every 30 seconds
    
    def attempt_websocket_reconnection(self):
        """Attempt to reconnect SocketIO if it's not running (fallback check)"""
        # Manager handles its own reconnection, but we check if the manager itself is alive
        if not self.websocket_client or not getattr(self.websocket_client, 'running', False):
            logger.info("Re-initializing SocketIO manager...")
            self.setup_websocket()
    
    def start_fallback_polling(self):
        """Start fallback polling if SocketIO is not connected"""
        if hasattr(self, 'poll_timer') and not self.poll_timer.isActive():
            # Check if SocketIO is connected
            if not self.websocket_client or not self.websocket_client.is_connected():
                self.poll_timer.start(5000)
                if hasattr(self, "connection_status_label"):
                    self.connection_status_label.setText("Live updates unavailable, using polling")
                logger.info("Started fallback polling for print jobs")
    
    def setup_printer_connectivity_polling(self):
        """Setup timer for real-time printer connectivity status updates"""
        try:
            self.printer_connectivity_timer = QTimer()
            self.printer_connectivity_timer.timeout.connect(self.update_printer_connectivity_status)
            self.printer_connectivity_timer.start(5000)  # Update every 5 seconds
            logger.info("Printer connectivity status polling started")
        except Exception as e:
            logger.error(f"Error setting up printer connectivity polling: {e}")
    

    def _start_background_printer_discovery(self):
        """Start background printer discovery to avoid startup freeze."""
        logger.info("Starting background printer discovery (isolated worker)...")
        
        # Create and start isolated worker
        self.cold_start_worker = ColdStartPrinterDiscoveryWorker(self)
        self.cold_start_worker.finished.connect(self._on_cold_discovery_finished)
        self.cold_start_worker.start()

    def _on_cold_discovery_finished(self):
        """Handle completion of cold start printer discovery"""
        logger.info("Background discovery finished. Updating UI...")
        try:
            # Mark initialization as complete
            self._is_initializing = False
            
            # Refresh the Connect Printers page using the now-cached data
            # This will pick up the printers discovered by the background worker
            self.load_connect_printers_page()
            
            # Update status label if visible
            if hasattr(self, 'connect_printers_status_label'):
                 # Clear "Searching..." message
                 # The load_connect_printers_page call above should have handled this, 
                 # but we ensure it here if needed or if the page was empty
                 pass
                 
        except Exception as e:
            logger.error(f"Error handling cold discovery completion: {e}")
            if hasattr(self, 'connect_printers_status_label'):
                self.connect_printers_status_label.setText("Discovery completed with errors")

    
    def check_and_show_printer_disconnect_popup(self):
        """Check printer status and show popup if disconnected (helper method)"""
        try:
            # Only show popup if dashboard is visible and ready (authenticated context)
            if not self.isVisible() or not self.dashboard_ready:
                return
            
            # Get current printer status from printer manager
            active_printers = self.printer_manager.get_active_printers(self.shopkeeper_data['shop_id'])
            
            # Reintroduce physical connectivity validation using cached discovery layer
            available_printers = self.printer_manager.get_available_printers()
            has_connected_printer = any(p.get('name') in active_printers and p.get('status') == 'Online' 
                                      for p in available_printers)
            
            # If printer is disconnected and popup hasn't been shown yet
            if not has_connected_printer and not self.printer_disconnect_popup_shown:
                self.show_printer_disconnected_popup()
                self.printer_disconnect_popup_shown = True
            # If printer reconnects, reset the flag so popup can show again on next disconnect
            elif has_connected_printer:
                self.printer_disconnect_popup_shown = False
        except Exception as e:
            logger.error(f"Error checking printer disconnect status: {e}")
    
    def update_printer_connectivity_status(self):
        """Update the printer connectivity status and show popup on disconnect"""
        try:
            # Get current printer status from printer manager
            active_printers = self.printer_manager.get_active_printers(self.shopkeeper_data['shop_id'])
            
            # Reintroduce physical connectivity validation using cached discovery layer
            available_printers = self.printer_manager.get_available_printers()
            has_connected_printer = any(p.get('name') in active_printers and p.get('status') == 'Online' 
                                      for p in available_printers)
            
            # Check for transition from connected to disconnected
            if (self.previous_printer_connected is not None and 
                self.previous_printer_connected == True and 
                has_connected_printer == False):
                # Printer just disconnected - show popup using helper method
                self.check_and_show_printer_disconnect_popup()
            
            # Reset flag when printer reconnects (allows popup to show again on next disconnect)
            if has_connected_printer:
                self.printer_disconnect_popup_shown = False
            
            # Update previous state
            self.previous_printer_connected = has_connected_printer
            
            # Update UI elements if they exist (for other parts of the app)
            if hasattr(self, "connection_status_label"):
                status_color = "#10b981" if has_connected_printer else "#ef4444"
                old_status_text = "Connected" if has_connected_printer else "Disconnected"
                self.connection_status_label.setText(old_status_text)
                self.connection_status_label.setStyleSheet(f"color: {status_color}; font-weight: 500; font-family: 'Segoe UI', sans-serif;")
            
            # Update status icon if it exists
            status_icon_label = self.findChild(QLabel, "printer_status_icon")
            if status_icon_label:
                status_type = 'connected' if has_connected_printer else 'disconnected'
                status_icon_label.setPixmap(get_status_icon(status_type).pixmap(14, 14))
            
            # Also update the "No Active Printer" section to be consistent
            self.update_dashboard_printer_status(has_connected_printer)
            
            logger.debug(f"Printer connectivity status updated: {'Connected' if has_connected_printer else 'Disconnected'}")
            
        except Exception as e:
            logger.error(f"Error updating printer connectivity status: {e}")
            # Set to disconnected on error
            if hasattr(self, "connection_status_label"):
                self.connection_status_label.setText("Error")
                self.connection_status_label.setStyleSheet("color: #ef4444; font-weight: 500; font-family: 'Segoe UI', sans-serif;")
            # Update status icon if it exists
            status_icon_label = self.findChild(QLabel, "printer_status_icon")
            if status_icon_label:
                status_icon_label.setPixmap(get_status_icon('disconnected').pixmap(14, 14))
            # Update previous state on error (treat as disconnected)
            if self.previous_printer_connected is not None and self.previous_printer_connected == True:
                self.previous_printer_connected = False
                self.show_printer_disconnected_popup()
    
    def show_printer_disconnected_popup(self):
        """Show modal popup when printer disconnects"""
        try:
            msg = QMessageBox(self)
            msg.setWindowTitle("Printer Disconnected")
            msg.setText("Please connect printer to the dashboard.")
            msg.setIcon(QMessageBox.Warning)
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()
        except Exception as e:
            logger.error(f"Error showing printer disconnected popup: {e}")
    
    def update_dashboard_printer_status(self, has_connected_printer):
        """Update the dashboard to reflect printer connection status"""
        try:
            # This method can be used to update other parts of the dashboard
            # that should be consistent with printer status
            # For now, we'll just log the status
            logger.debug(f"Dashboard printer status: {'Connected' if has_connected_printer else 'Disconnected'}")
            
            # You can add more dashboard updates here if needed
            # For example, showing/hiding certain sections based on printer status
            
        except Exception as e:
            logger.error(f"Error updating dashboard printer status: {e}")

    
    @safe_ui_action("WEBSOCKET_MESSAGE")
    def handle_thread_safe_operation(self, operation, data):
        """Handle thread-safe operations from background threads"""
        try:
            if operation == "start_polling_fallback":
                self.start_polling_fallback()
            elif operation == "stop_polling_fallback":
                self.stop_polling_fallback()
            elif operation == "load_print_jobs":
                self.load_print_jobs()
            elif operation == "handle_websocket_message":
                self.handle_websocket_message(data)
            elif operation == "update_job_status":
                job_id, status, progress, details = data
                self.update_job_status_in_ui(job_id, status, progress, details)
            elif operation == "check_and_print_pending_jobs":
                self.check_and_print_pending_jobs()
            elif operation == "refresh_connect_printers":
                self.load_connect_printers_page()
        except Exception as e:
            logger.error(f"Error in thread-safe operation {operation}: {e}")
    
    def _on_websocket_message(self, message):
        """Handle WebSocket/SocketIO messages from thread-safe client"""
        try:
            # Emit signal to process message in main thread
            self.thread_safe_signal.emit("handle_websocket_message", message.data)
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")
    
    def handle_websocket_message(self, data):
        """Handle WebSocket messages"""
        message_type = data.get('type')
        
        if message_type == 'ws_status':
            status = data.get('status')
            if status == 'retrying' or status == 'disconnected':
                self.show_toast("Live updates paused, retrying…")
                self.start_polling_fallback()
                if hasattr(self, "connection_status_label"):
                    self.connection_status_label.setText("Live updates paused, retrying...")
            elif status == 'failed':
                self.show_toast("Live updates unavailable, using polling fallback.")
                self.start_polling_fallback()
                if hasattr(self, "connection_status_label"):
                    self.connection_status_label.setText("Live updates unavailable, using polling")
            elif status == 'connected':
                self.show_toast("Live updates restored.")
                self.stop_polling_fallback()
                if hasattr(self, "connection_status_label"):
                    self.connection_status_label.setText("Live updates available")
            return

        if message_type == 'new_print_job':
            # Receive new job notification and refresh immediately
            job_data = data.get('job', {})
            job_id = job_data.get('job_id', 'unknown')
            job_status = job_data.get('status', 'Pending')
            
            # TRACE G: Dashboard received new_print_job
            logger.info(f"TRACE G: Dashboard received new_print_job for job_id={job_id} status={job_status}")
            logger.info(f"📥 Received new_print_job notification: job_id={job_id}, status={job_status}")
            
            # TRACE H: Dashboard refreshing job list after WebSocket
            logger.info(f"TRACE H: Dashboard refreshing job list after WebSocket for job_id={job_id}")
            
            # Load print jobs in main thread to refresh the UI immediately
            self.load_print_jobs()
            logger.info(f"✓ Refreshed job list after receiving new_print_job notification for job {job_id}")
            
            # If in auto mode, automatically print the new job
            if self.auto_mode:
                self.check_and_print_pending_jobs()
                
        elif message_type == 'job_update':
            # Update UI efficiently for job status changes
            job_id = data.get('job_id')
            status = data.get('status')
            if job_id and status:
                self.update_job_status_in_ui(job_id, status, None, None)
            else:
                # Fallback to full reload if no specific job info
                self.load_print_jobs()

    def handle_new_job_popup(self, job):
        """Add new job to popup queue and trigger display logic with duplicate avoidance"""
        try:
            if not job:
                return
            
            # Auto Mode dismissal guard: Skip jobs dismissed via X
            is_auto = hasattr(self, 'auto_mode') and self.auto_mode
            if is_auto and hasattr(self, 'dismissed_auto_jobs') and job.job_id in self.dismissed_auto_jobs:
                logger.debug(f"Auto Mode: Skipping dismissed job {job.job_id}")
                return
                
            # Avoid queuing the same job ID multiple times if it's already in queue or active
            if any(q_job.job_id == job.job_id for q_job in self.popup_job_queue):
                return
            if any(p.job.job_id == job.job_id for p in self._active_job_popups if self._is_alive(p)):
                return
                
            self.popup_job_queue.append(job)
            logger.info(f"Job {job.job_id} enqueued for popup. Queue size: {len(self.popup_job_queue)}")
            
            # Trigger display logic (will return early if a popup is already active)
            self.display_next_popup()
        except Exception as e:
            logger.error(f"Error queuing new job popup: {e}")

    def display_next_popup(self):
        """Display the next job popup in the queue if none is currently active"""
        try:
            # SELF-CORRECTION: Reset flag if no popups are actually visible/alive
            # This protects against any scenario where the flag gets stuck in True state
            actual_visible_popups = [p for p in self._active_job_popups if self._is_alive(p) and p.isVisible()]
            if self.is_popup_active and not actual_visible_popups and not self._cancel_dialog_active:
                logger.warning("STUCK POPUP GUARD DETECTED: is_popup_active was True but no visible popups found. Self-correcting.")
                self.is_popup_active = False

            # STRICT GUARD: Only one popup at a time. 
            if self.is_popup_active or self._cancel_dialog_active or actual_visible_popups:
                return


            if not self.popup_job_queue:
                self.is_popup_active = False
                return
                
            job = self.popup_job_queue.pop(0)
            self.is_popup_active = True
            
            popup = JobPopupDialog(job, self)
            self._active_job_popups.append(popup)
            
            # REQUIREMENT: Next popup MUST open ONLY after PICKUP is clicked.
            # We connect to accepted() signal which is specifically emitted when 
            # the dialog is closed via the PICKUP button (calling self.accept()).
            def on_pickup_accepted():
                logger.info(f"PICKUP confirmed for job {job.job_id}. Triggering next queued job.")
                # Delay slightly to ensure current dialog is fully closed/destroyed
                QTimer.singleShot(100, self.display_next_popup)

            # Reset flag and cleanup on any finish (including X button or cancel)
            def on_popup_finished():
                if popup in self._active_job_popups:
                    self._active_job_popups.remove(popup)
                self.is_popup_active = False
                logger.debug(f"Popup for job {job.job_id} closed/finished. Guard reset.")
                
            popup.accepted.connect(on_pickup_accepted)
            popup.finished.connect(on_popup_finished)
            
            popup.show()
            logger.info(f"Notification popup shown for job: {job.job_id}")
        except Exception as e:
            logger.error(f"Error displaying next popup: {e}")
            self.is_popup_active = False
            # Try to recover and check queue again after failure
            QTimer.singleShot(200, self.display_next_popup)
    
    def check_and_print_pending_jobs(self):
        """Check for pending jobs and print them automatically if in auto mode"""
        if not self.auto_mode:
            return

        # REQUIREMENT: If a popup is active, do NOT start next printing in background.
        # This ensures Auto Mode is strictly pickup-gated; the next job starts 
        # only after the shopkeeper clicks PICKUP on the current popup.
        if self.is_popup_active:
            # logger.debug("Auto-print skipped: popup active")
            return
            
        try:
            # Get pending jobs
            pending_jobs = self.db.query(PrintJob).filter(
                PrintJob.shop_id == self.shopkeeper_data['shop_id'],
                PrintJob.status == 'Pending'
            ).all()
            
            for job in pending_jobs:
                # Funnel into popup system instead of printing directly.
                # This ensures the job is enqueued and then handled sequentially.
                self.handle_new_job_popup(job)
                
        except Exception as e:
            logger.error(f"Error in auto-printing: {e}")
    
    
    def load_print_jobs(self, *args, **kwargs):
        """Load print jobs from database (Scroll-preserving)"""
        if self._is_refreshing_jobs:
            return
            
        # Determine if we should preserve scroll position (default True for non-signal calls)
        # Signals like textChanged or currentIndexChanged pass arguments, which we use to detect filter changes
        preserve_scroll = kwargs.get('preserve_scroll', len(args) == 0)
        
        # Save current scroll position before UI is cleared
        scroll_pos = 0
        if preserve_scroll and hasattr(self, 'jobs_cards_scroll'):
            try:
                scroll_pos = self.jobs_cards_scroll.verticalScrollBar().value()
            except Exception:
                preserve_scroll = False

        try:
            # Prevent UI refresh from interrupting open menus
            if self._suspend_jobs_refresh:
                return
            
            self._is_refreshing_jobs = True
            
            # Create a new database session for this operation
            db_session = SessionLocal()
            
            jobs_query = db_session.query(PrintJob).filter(
                PrintJob.shop_id == self.shopkeeper_data['shop_id']
            )
            # Get all jobs first (no date filtering at database level)
            jobs = jobs_query.order_by(PrintJob.created_at.desc()).all()
            
            # Detect new jobs for popup notification
            current_job_ids = {j.job_id for j in jobs}
            new_job_ids = [j.job_id for j in jobs if j.job_id not in self.known_job_ids]
            
            # Trigger popups for new jobs (skip on first load to prevent flooding)
            if not self.is_first_load:
                for j_id in new_job_ids:
                    nj = next((j for j in jobs if j.job_id == j_id), None)
                    if nj:
                        self.handle_new_job_popup(nj)
            
            # Update known state
            self.known_job_ids.update(current_job_ids)
            self.is_first_load = False
            
            # Apply search and filters
            query = jobs
            term = (self.jobs_search.text().strip().lower() if hasattr(self, 'jobs_search') and self.jobs_search.text() else '')
            status_filter = (self.filter_status.currentText() if hasattr(self, 'filter_status') else 'All')
            date_filter = (self.filter_date.currentText() if hasattr(self, 'filter_date') else 'All')
            # removed print type filter in new UI

            # Date filtering logic (moved to application level)
            def is_job_in_date_range(job, date_filter_mode):
                """Check if job falls within the specified date range"""
                if date_filter_mode == 'All':
                    return True
                    
                try:
                    from datetime import datetime, timedelta, timezone
                    job_date = job.created_at
                    
                    # Handle timezone issues - try both UTC and local time
                    now_local = datetime.now()
                    now_utc = datetime.utcnow()
                    
                    # Try local time first
                    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                    today_start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                    
                    if date_filter_mode == 'Today':
                        # Today: from 00:00:00 today to now
                        # Try both local and UTC to handle timezone issues
                        local_match = job_date >= today_start_local
                        utc_match = job_date >= today_start_utc
                        
                        logger.debug(f"Today filter: job_date={job_date}, local_start={today_start_local}, utc_start={today_start_utc}")
                        logger.debug(f"Today filter: local_match={local_match}, utc_match={utc_match}")
                        
                        # Use the one that makes sense (prefer local time)
                        return local_match
                        
                    elif date_filter_mode == 'Yesterday':
                        # Yesterday: from 00:00:00 yesterday to 23:59:59 yesterday
                        yesterday_start_local = today_start_local - timedelta(days=1)
                        yesterday_end_local = today_start_local
                        
                        yesterday_start_utc = today_start_utc - timedelta(days=1)
                        yesterday_end_utc = today_start_utc
                        
                        # Try both local and UTC
                        local_match = yesterday_start_local <= job_date < yesterday_end_local
                        utc_match = yesterday_start_utc <= job_date < yesterday_end_utc
                        
                        logger.debug(f"Yesterday filter: job_date={job_date}")
                        logger.debug(f"Yesterday filter local: {yesterday_start_local} <= {job_date} < {yesterday_end_local} = {local_match}")
                        logger.debug(f"Yesterday filter UTC: {yesterday_start_utc} <= {job_date} < {yesterday_end_utc} = {utc_match}")
                        
                        # Use the one that makes sense (prefer local time)
                        return local_match
                        
                    elif date_filter_mode == 'This Week':
                        # This Week: from Monday 00:00:00 to now
                        days_since_monday = now_local.weekday()  # Monday = 0, Sunday = 6
                        week_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
                        logger.debug(f"This Week filter: job_date={job_date}, week_start={week_start}")
                        return job_date >= week_start
                        
                    elif date_filter_mode == 'This Month':
                        # This Month: from 1st day of current month 00:00:00 to now
                        month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                        logger.debug(f"This Month filter: job_date={job_date}, month_start={month_start}")
                        return job_date >= month_start
                        
                except Exception as e:
                    logger.error(f"Error in date filtering for job {job.job_id}: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    return True  # Include job if date filtering fails
                    
                return True

            # Debug logging
            logger.info(f"Applying filters - Date: {date_filter}, Status: {status_filter}, Search: '{term}'")
            logger.info(f"Total jobs before filtering: {len(query)}")
            
            filtered_jobs = []
            for j in query:
                # Search by job id or filename
                if term and (term not in j.job_id.lower() and term not in (j.filename or '').lower()):
                    continue
                    
                # Date filter
                if not is_job_in_date_range(j, date_filter):
                    continue
                    
                # Status filter
                if status_filter != 'All':
                    if status_filter == 'Pending' and j.status not in ['In Queue', 'Pending', 'Processing', 'Printing Started']:
                        continue
                    if status_filter == 'Printing' and j.status not in ['Printing', 'Printing Started']:
                        continue
                    if status_filter == 'Completed' and j.status.lower() != 'completed':
                        continue
                    if status_filter == 'Failed' and j.status.lower() != 'failed':
                        continue
                        
                # Print type filter (derive text)
                color = (j.color_mode or 'Color')
                side = ('Duplex' if (j.print_side or 'Single') in ['Duplex', 'Double'] else 'Single')
                type_text = f"{'B&W' if color.lower().startswith('black') else 'Color'} • {side}"
                filtered_jobs.append((j, type_text))
            
            logger.info(f"Total jobs after filtering: {len(filtered_jobs)}")

            # Sorting removed - jobs will be displayed in default order (newest first)

            # Keep table for backward compatibility (hidden)
            self.jobs_table.setRowCount(len(filtered_jobs))
            
            # Clear cards and job map
            if hasattr(self, 'job_cards_map'):
                self.job_cards_map.clear()
            
            # Clear cards and map
            self.job_cards_map = {}
            if hasattr(self, 'jobs_cards_layout'):
                while self.jobs_cards_layout.count():
                    item = self.jobs_cards_layout.takeAt(0)
                    if item:
                        widget = item.widget()
                        if widget:
                            widget.setParent(None)
            
            # Toggle header card visibility (maintained in create_print_jobs_page)
            if hasattr(self, 'jobs_header_card'):
                self.jobs_header_card.setVisible(len(filtered_jobs) > 0)
            
            # Create cards for each job
            for row, pair in enumerate(filtered_jobs):
                job, type_text = pair
                card = self.create_print_job_card(job, type_text, row)
                self.job_cards_map[job.job_id] = {'card': card, 'job': job}
                if hasattr(self, 'jobs_cards_layout'):
                    self.jobs_cards_layout.addWidget(card)
            
            # Add stretch to push cards to top
            if hasattr(self, 'jobs_cards_layout'):
                self.jobs_cards_layout.addStretch()
            
            # Keep table population for backward compatibility (hidden table)
            for row, pair in enumerate(filtered_jobs):
                job, type_text = pair
                
                # Column 0: Select checkbox
                checkbox = QCheckBox()
                checkbox.setChecked(False)
                # Disable checkbox for completed jobs
                if (job.status or '').lower() == 'completed':
                    checkbox.setEnabled(False)
                checkbox.stateChanged.connect(lambda state, jid=job.job_id: self.handle_job_selection(jid, state))
                self.jobs_table.setCellWidget(row, 0, checkbox)
                
                # Column 1: Job ID (use item for reliable rendering)
                job_id_text = (job.job_id or "")[:8]
                job_id_item = QTableWidgetItem(job_id_text)
                job_id_item.setData(Qt.UserRole, job.job_id)
                job_id_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                f = job_id_item.font()
                f.setBold(True)
                job_id_item.setFont(f)
                if (job.status or '').lower() == 'failed':
                    job_id_item.setForeground(Qt.red)
                self.jobs_table.setItem(row, 1, job_id_item)

                # Column 2: File Name (with icon and tooltip)
                display_name = self._format_job_display_name(job)
                file_item = QTableWidgetItem(display_name)
                file_item.setIcon(self._icon_for_type(job.file_type))
                file_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                tooltip = f"Name: {self._format_job_display_name(job)}\nType: {job.file_type or '-'}\nSize: {self._human_size(job.file_size)}\nPath: {job.file_path or '-'}"
                file_item.setToolTip(tooltip)
                self.jobs_table.setItem(row, 2, file_item)

                # Column 3: Time (exact upload time)
                time_text = (job.created_at or datetime.utcnow()).strftime("%Y-%m-%d %H:%M")
                time_item = QTableWidgetItem(time_text)
                time_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.jobs_table.setItem(row, 3, time_item)

                # Column 4: Print Side
                side_label = 'Double' if (job.print_side or 'Single') in ['Duplex', 'Double'] else 'Single'
                side_item = QTableWidgetItem(side_label)
                side_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.jobs_table.setItem(row, 4, side_item)

                # Column 5: Color Mode
                color_label = 'Black & White' if (job.color_mode or '').lower().startswith('black') else 'Color'
                color_item = QTableWidgetItem(color_label)
                color_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.jobs_table.setItem(row, 5, color_item)

                # Column 6: Amount (total price for this print job)
                amount_value = job.amount if job.amount is not None else 0.0
                amount_text = f"₹ {amount_value:.2f}"
                amount_item = QTableWidgetItem(amount_text)
                amount_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignRight)
                self.jobs_table.setItem(row, 6, amount_item)

                # Column 7: Status badge (normalized label + colors)
                norm_text, norm_style = self._status_display_and_style(job.status)
                # Center-aligned, consistent size status chip
                status_badge = QLabel(norm_text)
                status_badge.setAlignment(Qt.AlignCenter)
                status_badge.setLayoutDirection(Qt.LeftToRight)
                # Fixed height to avoid text distortion/wrapping; bold, consistent size
                st_font = status_badge.font()
                st_font.setWeight(QFont.DemiBold)  # 600
                st_font.setPointSize(max(10, st_font.pointSize()))
                status_badge.setFont(st_font)
                status_badge.setFixedHeight(22)
                status_badge.setStyleSheet(f"padding:4px 10px; min-width:110px; border-radius:8px; font-size:13px; margin-right:12px; {norm_style}")
                self.jobs_table.setCellWidget(row, 7, status_badge)

                # Column 8: Inline action icons (only Print as requested)
                actions_widget = QWidget()
                actions_layout = QHBoxLayout(actions_widget)
                # Add extra left margin to increase distance from Status column
                actions_layout.setContentsMargins(18, 0, 12, 0)
                actions_layout.setSpacing(6)

                # Consistent Print action button within the Actions column - Clean rectangular design
                btn_reprint = QPushButton("Print")
                btn_reprint.setToolTip("Reprint")
                btn_reprint.setCursor(Qt.PointingHandCursor)
                # No icon - text only for clean professional look
                try:
                    from PyQt5.QtWidgets import QSizePolicy
                    btn_reprint.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
                except Exception:
                    pass
                # Clean rectangular button with rounded corners - Height matches Status badge (22px)
                btn_reprint.setStyleSheet(
                    """
                    QPushButton {
                        background-color: #3b82f6;
                        color: #ffffff;
                        border: none;
                        padding: 4px 14px;
                        border-radius: 4px;
                        font-weight: 500;
                        font-size: 12px;
                        font-family: 'Segoe UI', sans-serif;
                        text-align: center;
                    }
                    QPushButton:hover {
                        background-color: #2563eb;
                    }
                    QPushButton:pressed {
                        background-color: #1d4ed8;
                    }
                    QPushButton:disabled {
                        background-color: #93c5fd;
                        color: #f3f4f6;
                    }
                    """
                )
                # Match Status badge height exactly (22px) for visual consistency
                try:
                    btn_reprint.setMinimumWidth(90)
                    btn_reprint.setFixedHeight(22)
                    btn_reprint.setMaximumHeight(22)
                    btn_reprint.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                except Exception:
                    pass
                btn_reprint.clicked.connect(self.create_reprint_handler(job))
                actions_layout.addWidget(btn_reprint)
                # Ensure the button's contents are visually centered within the cell
                try:
                    actions_layout.setAlignment(btn_reprint, Qt.AlignCenter)
                except Exception:
                    pass

                self.jobs_table.setCellWidget(row, 8, actions_widget)

                # Highlight current printing row (for hidden table)
                if (job.status or '').lower().startswith('printing'):
                    for c in range(0, 9):  # Updated to 9 columns
                        item = self.jobs_table.item(row, c)
                        if not item:
                            item = QTableWidgetItem('')
                            self.jobs_table.setItem(row, c, item)
                        item.setBackground(QColor('#FFF9C4'))  # light yellow
            
            # TRACE I: Jobs visible in dashboard list (after table is fully populated)
            if filtered_jobs:
                job_ids_visible = [job.job_id for job, _ in filtered_jobs[:5]]  # Log first 5 job IDs
                logger.info(f"TRACE I: Jobs visible in dashboard list (showing first 5): {job_ids_visible}")
            
            # Close the database session
            db_session.close()
            
            # Update window title (without job count)
            self.setWindowTitle("EzPrint Dashboard")
            
            # Update last refresh time in 12-hour format
            from datetime import datetime
            current_time = datetime.now().strftime("%I:%M:%S %p")
            if hasattr(self, "last_refresh_label"):
                self.last_refresh_label.setText(f"Last refresh: {current_time}")
            
            logger.info(f"Loaded {len(jobs)} print jobs")
            
            # Update Dashboard KPIs whenever print jobs are loaded/refreshed
            # Pass pre-fetched jobs to avoid redundant DB queries
            self._is_initializing = False
            self.update_dashboard_kpis(jobs)
            
            # Restore scroll position after UI rebuild (Manual Mode & Background updates)
            if preserve_scroll and hasattr(self, 'jobs_cards_scroll'):
                QTimer.singleShot(0, lambda: self._safe_restore_jobs_scroll(scroll_pos))
            
        except Exception as e:
            logger.error(f"Error loading print jobs: {e}")
            # Show error in status if available
            if hasattr(self, "connection_status_label"):
                self.connection_status_label.setText("Error loading data")
            # Friendly message instead of blocking error
            self.show_toast("Error loading print jobs, retrying...")
            # Ensure polling continues even if there's an error
            if hasattr(self, 'poll_timer') and not self.poll_timer.isActive():
                self.poll_timer.start(5000)
        finally:
            self._is_refreshing_jobs = False
    
    
    def create_print_jobs_header_card(self):
        """Create column header card for print jobs list with full-width proportional columns"""
        header = QFrame()
        header.setFrameStyle(QFrame.StyledPanel)
        
        # Header styling - subtle background to differentiate from job rows
        header.setStyleSheet("""
            QFrame {
                background-color: #f9fafb;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 12px 20px;
            }
        """)
        
        # Main layout - horizontal row matching job cards
        main_layout = QHBoxLayout(header)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)
        
        # Column 1: Job ID (content-aware - no stretch, minimum size policy)
        job_id_header = QLabel("Job ID")
        job_id_header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        job_id_header.setStyleSheet("color: #111827;")
        job_id_header.setMinimumWidth(85)
        job_id_header.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        main_layout.addWidget(job_id_header, 0)
        
        # Column 2: File Name (stretch factor 2 - swapped with Amount)
        file_name_header = QLabel("File Name")
        file_name_header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        file_name_header.setStyleSheet("color: #111827;")
        file_name_header.setMinimumWidth(100)
        main_layout.addWidget(file_name_header, 2)
        
        # Column 3: Time (content-aware - no stretch, minimum size policy)
        time_header = QLabel("Time")
        time_header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        time_header.setStyleSheet("color: #111827;")
        time_header.setMinimumWidth(135)
        time_header.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        main_layout.addWidget(time_header, 0)
        
        # Column 4: Print Side (stretch factor 2 - increased to reclaim space from File Name)
        side_header = QLabel("Print Side")
        side_header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        side_header.setStyleSheet("color: #111827;")
        side_header.setMinimumWidth(110)
        main_layout.addWidget(side_header, 2)
        
        # Column 5: Color Mode (stretch factor 2 - medium)
        color_header = QLabel("Color Mode")
        color_header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        color_header.setStyleSheet("color: #111827;")
        color_header.setMinimumWidth(120)
        main_layout.addWidget(color_header, 2)
        
        # Column 6: Amount (stretch factor 1 - swapped with File Name)
        amount_header = QLabel("Amount")
        amount_header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        amount_header.setStyleSheet("color: #111827;")
        amount_header.setMinimumWidth(145)
        main_layout.addWidget(amount_header, 1)
        
        # Column 7: Status (stretch factor 2 - medium)
        status_header = QLabel("Status")
        status_header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        status_header.setStyleSheet("color: #111827;")
        status_header.setMinimumWidth(110)
        main_layout.addWidget(status_header, 2)
        
        # Action header (aligned above Print buttons)
        action_header = QLabel("Action")
        action_header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        action_header.setStyleSheet("color: #111827;")
        # Allow full visibility and natural reflow
        action_header.setMinimumWidth(90)
        main_layout.addWidget(action_header, 1)
        
        return header
    
    def create_print_job_card(self, job, type_text, row):
        """Create a row-style print job card with proportional columns matching header"""
        card = QFrame()
        card.setFrameStyle(QFrame.StyledPanel)
        
        # Card styling - maintains existing theme
        card.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 12px 20px;
            }
        """)
        
        # Main layout - horizontal row layout
        main_layout = QHBoxLayout(card)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)
        
        # Column 1: Job ID (content-aware - no stretch, minimum size policy)
        job_id_short = (job.job_id or "")[:8]  # First 8 characters to match customer view
        job_id_value = QLabel(job_id_short)
        job_id_value.setFont(QFont("Segoe UI", 11, QFont.Bold))
        job_id_value.setStyleSheet("color: #374151;")
        job_id_value.setMinimumWidth(85)
        job_id_value.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        job_id_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        main_layout.addWidget(job_id_value, 0)
        
        # Column 2: File Name (stretch factor 2 - swapped with Amount)
        file_name = job.filename or "Unknown File"
        file_name_value = QLabel(file_name)
        file_name_value.setStyleSheet("color: #374151; font-size: 11px;")
        file_name_value.setMinimumWidth(100)
        file_name_value.setWordWrap(False)
        file_name_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # Enable text truncation with ellipsis
        file_name_value.setTextFormat(Qt.PlainText)
        file_name_value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        main_layout.addWidget(file_name_value, 2)
        
        # Column 3: Time (converted to local system time and COMPACT 12-hour format)
        utc_time = job.created_at or datetime.utcnow()
        local_time = utc_time.replace(tzinfo=timezone.utc).astimezone(None)
        time_text = local_time.strftime("%d %b %Y, %I:%M %p")
        time_value = QLabel(time_text)
        time_value.setStyleSheet("color: #374151; font-size: 11px;")
        time_value.setMinimumWidth(135)
        time_value.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        time_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        time_value.setAttribute(Qt.WA_TransparentForMouseEvents)
        main_layout.addWidget(time_value, 0)
        
        # Column 4: Print Side (stretch factor 2)
        side_value_text = 'Double' if (job.print_side or 'Single') in ['Duplex', 'Double'] else 'Single'
        side_value = QLabel(side_value_text)
        side_value.setStyleSheet("color: #374151; font-size: 11px;")
        side_value.setMinimumWidth(110)
        side_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        side_value.setAttribute(Qt.WA_TransparentForMouseEvents)
        main_layout.addWidget(side_value, 2)
        
        # Column 5: Color Mode (stretch factor 2)
        color_value_text = 'Black & White' if (job.color_mode or '').lower().startswith('black') else 'Color'
        color_value = QLabel(color_value_text)
        color_value.setStyleSheet("color: #374151; font-size: 11px;")
        color_value.setMinimumWidth(120)
        color_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        color_value.setAttribute(Qt.WA_TransparentForMouseEvents)
        main_layout.addWidget(color_value, 2)
        
        # Column 6: Amount (BOLD)
        amount_value_num = job.amount if job.amount is not None else 0.0
        amount_value = QLabel(f"₹ {amount_value_num:.2f}")
        amount_value.setFont(QFont("Segoe UI", 11, QFont.Bold))
        amount_value.setStyleSheet("color: #0369a1;")
        amount_value.setMinimumWidth(145)
        amount_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        amount_value.setAttribute(Qt.WA_TransparentForMouseEvents)
        main_layout.addWidget(amount_value, 1)
        
        # Column 7: Status chip
        status = job.status or 'Pending'
        
        # Explicit status-to-chip color mapping
        if status.lower() == 'completed':
            status_bg = "#dcfce7"
            status_color = "#15803d"
            status_text = "Completed"
        elif status.lower() == 'failed':
            status_bg = "#fee2e2"
            status_color = "#dc2626"
            status_text = "Failed"
        elif status.lower() in ['printing', 'printing started']:
            status_bg = "#dbeafe"
            status_color = "#1e40af"
            status_text = "Printing"
        elif status.lower() == 'cancelled':
            status_bg = "#f3f4f6"
            status_color = "#374151"
            status_text = "Cancelled"
        else:  # Pending, In Queue, Processing
            status_bg = "#fef3c7"
            status_color = "#d97706"
            status_text = "Pending"
        
        status_chip = QLabel(status_text)
        status_chip.setObjectName(f"status_chip_{job.job_id}")  # Unique ID for targeted updates
        status_chip.setAlignment(Qt.AlignCenter)
        status_chip.setStyleSheet(f"background-color: {status_bg}; color: {status_color}; border-radius: 4px; padding: 2px 8px; font-weight: 600; font-size: 11px;")
        # Explicitly set font weight to DemiBold (600) to ensure it renders bold
        st_chip_font = status_chip.font()
        st_chip_font.setWeight(QFont.DemiBold)
        status_chip.setFont(st_chip_font)
        status_chip.setAttribute(Qt.WA_TransparentForMouseEvents)
        main_layout.addWidget(status_chip, 2)
        
        # Column 8: Action header space (matches header layout)
        print_btn = QPushButton("Print")
        print_btn.setStyleSheet("""
            QPushButton {
                min-width: 90px;
                max-width: 90px;
                min-height: 28px;
                max-height: 28px;
                padding: 4px 8px;
                border-radius: 5px;
                font-size: 9px;
                font-weight: 500;
                text-align: center;
                background-color: #3b82f6;
                color: #ffffff;
                border: 1px solid #2563eb;
            }
            QPushButton:hover {
                background-color: #2563eb;
                border-color: #1d4ed8;
            }
            QPushButton:disabled {
                background-color: #9ca3af;
                color: #ffffff;
                border: 1px solid #6b7280;
            }
        """)
        
        # Create reprint handler
        def reprint_handler():
            try:
                self.print_job(job)
            except Exception as e:
                logger.error(f"Error reprinting job {job.job_id}: {e}")
                QMessageBox.warning(self, "Error", f"Failed to reprint job {job.job_id}")
        
        print_btn.clicked.connect(reprint_handler)
        main_layout.addWidget(print_btn, 0)
        
        self.job_cards_map[job.job_id] = {'card': card, 'job': job}
        
        # Double click to toggle selection
        def on_double_click(event):
            try:
                # Toggle selection on double-click
                state = Qt.Unchecked if job.job_id in self.selected_job_ids else Qt.Checked
                self.handle_job_selection(job.job_id, state)
            except Exception:
                pass
        
        card.mouseDoubleClickEvent = on_double_click
        
        # Final child setup: ensure Job ID and File Name also bubble events
        job_id_value.setAttribute(Qt.WA_TransparentForMouseEvents)
        file_name_value.setAttribute(Qt.WA_TransparentForMouseEvents)
        
        # If this job was previously selected (e.g. during a refresh), restore style
        if job.job_id in self.selected_job_ids:
            card.setStyleSheet("QFrame { background-color: #f0f9ff; border: 2px solid #3b82f6; border-radius: 8px; padding: 12px 20px; }")
            
        return card
    
    @safe_ui_action("PRINT_JOB")
    def print_job(self, job):
        """Print a job silently applying all customer settings"""
        # RELAXED CHECK: If current_printer is not set, we still proceed if routing is enabled.
        # This fixes Auto Mode where current_printer might not be initialized yet.
        if not self.printer_manager.current_printer:
            if not self.auto_mode:
                QMessageBox.warning(self, "Warning", "No printer selected. Please connect a printer first.")
                return
            else:
                logger.info("Auto-print: No current_printer set, relying on intelligent routing.")

        # STATUS RE-SYNC FIX: Recovery from premature FAILED status
        # If the job was wrongly marked as Failed by the background tracker 
        # while waiting in queue/popup, force reset its status before printing.
        if job.status in ['Failed', 'Error']:
            logger.info(f"Resyncing job {job.job_id} from {job.status} to Pending before printing.")
            job.status = 'Pending'
            job.error_message = None
            self.db.commit()
        
        # Ensure any stale polling threads are cleaned up before starting new print
        if hasattr(self.printer_manager, 'stop_job_status_polling'):
            self.printer_manager.stop_job_status_polling(job.job_id)
        
        # Update job status via authoritative reporter
        self.report_job_status(job.job_id, 'In Queue', 0, "Initializing...")
        
        # Build settings dict to apply on printer
        settings = {
            'copies': job.copies or 1,
            'page_range': job.page_range or '',
            'page_size': job.page_size or 'A4',
            'orientation': job.orientation or 'Portrait',
            'print_side': job.print_side or 'Single',
            'color_mode': job.color_mode or 'Color',
            'layout_pages': job.layout_pages or 1
        }

        # Start print worker using silent settings-aware printing
        class _SettingsPrintWorker(PrintJobWorker):
            def __init__(self, dashboard, job_id, file_path, file_type, settings, printer_manager, websocket_client):
                super().__init__(job_id, file_path, printer_manager)
                self.dashboard = dashboard # Store reference to dashboard for thread-safe signaling
                self.file_type = file_type
                self.settings = settings
                self.websocket_client = websocket_client
            def run(self):
                try:
                    # Mark printing started via authoritative reporter
                    self.dashboard.report_job_status(self.job_id, 'Printing Started')
                    
                    # Start real-time status polling
                    def status_callback(job_id, status, progress, details):
                        self.dashboard.report_job_status(job_id, status, progress, details)
                    
                    # Start polling for this job
                    self.printer_manager.start_job_status_polling(self.job_id, status_callback)
                    
                    result = self.printer_manager.print_document_with_settings(self.file_path, self.file_type, self.settings, job_id=self.job_id)
                    # FIX 3: Guard against None / non-tuple return from @safe_printer_action
                    if result is None or not isinstance(result, (tuple, list)):
                        ok, msg = False, "Print pipeline returned no result (internal error)"
                    else:
                        ok, msg = result[0], result[1] if len(result) > 1 else "Unknown error"
                    # Do not mark completed immediately; rely on poller callback.
                    # If the print call itself fails, emit failure now.
                    if not ok:
                        self.job_failed.emit(self.job_id, msg)
                except Exception as e:
                    # Outer safety net — replaces missing @safe_thread_action on overridden run()
                    logger.error(f"_SettingsPrintWorker unhandled exception for job {self.job_id}: {e}")
                    try:
                        self.job_failed.emit(self.job_id, f"Print worker error: {str(e)}")
                    except Exception:
                        logger.error(f"CRITICAL: Could not emit job_failed for {self.job_id}: {e}")

        worker = _SettingsPrintWorker(self, job.job_id, job.file_path, job.file_type, settings, self.printer_manager, self.websocket_client)
        worker.job_completed.connect(self.on_job_completed)
        worker.job_failed.connect(self.on_job_failed)
        worker.start()
        
        self.print_workers[job.job_id] = worker
        
        # Show message only in manual mode
        if not self.auto_mode:
            logger.info(f"Started printing job: {job.job_id}")
        
        # Refresh jobs list
        self.load_print_jobs()
    
    def on_job_completed(self, job_id, status):
        """Handle job completion"""
        try:
            job = self.db.query(PrintJob).filter(PrintJob.job_id == job_id).first()
            if job:
                job.status = status
                job.completed_at = datetime.utcnow()
                self.db.commit()
            
            # Clean up worker
            if job_id in self.print_workers:
                del self.print_workers[job_id]
            
            # Refresh jobs list
            self.load_print_jobs()
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error handling job completion: {e}")
    
    def on_job_failed(self, job_id, error_message):
        """Handle job failure"""
        try:
            job = self.db.query(PrintJob).filter(PrintJob.job_id == job_id).first()
            if job:
                job.status = 'Failed'
                job.error_message = error_message
                self.db.commit()
            
            # Clean up worker
            if job_id in self.print_workers:
                del self.print_workers[job_id]
            
            # Show error message only in manual mode
            if not self.auto_mode:
                QMessageBox.warning(self, "Print Failed", f"Job failed: {error_message}")
            else:
                logger.error(f"Auto-print job failed: {error_message}")
            
            # Refresh jobs list
            self.load_print_jobs()
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error handling job failure: {e}")
    
    def manual_refresh(self):
        """Manual refresh with visual feedback"""
        try:
            # Find refresh button by object name or icon
            refresh_btn = None
            for child in self.findChildren(QPushButton):
                # Check if button has refresh icon or contains "Refresh" in text
                if child.icon().isNull() == False and "Refresh" in child.text():
                    refresh_btn = child
                    break
                elif "Refresh" in child.text() and not child.icon().isNull():
                    refresh_btn = child
                    break
            
            if refresh_btn:
                original_text = refresh_btn.text()
                original_enabled = refresh_btn.isEnabled()
                refresh_btn.setText("Refreshing...")
                refresh_btn.setEnabled(False)
                
                # Load jobs
                if not getattr(self, '_suspend_jobs_refresh', False):
                    self.load_print_jobs()
                
                # Restore button state
                refresh_btn.setText(original_text)
                refresh_btn.setEnabled(original_enabled)
                
                logger.info("Manual refresh completed")
            else:
                # Fallback if button not found
                if not getattr(self, '_suspend_jobs_refresh', False):
                    self.load_print_jobs()
                if hasattr(self, "last_refresh_label"):
                    from datetime import datetime
                    self.last_refresh_label.setText(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")
                
        except Exception as e:
            logger.error(f"Error in manual refresh: {e}")
            QMessageBox.warning(self, "Error", f"Refresh failed: {str(e)}")
            
            # Restore button state on error
            refresh_btn = None
            for child in self.findChildren(QPushButton):
                if "Refreshing" in child.text():
                    refresh_btn = child
                    break
            
            if refresh_btn:
                refresh_btn.setText("Refresh")
                refresh_btn.setEnabled(True)

    def delete_job(self, job):
        """Delete a specific print job"""
        try:
            # Confirm deletion
            reply = QMessageBox.question(
                self, 
                "Delete Job", 
                f"Are you sure you want to delete job '{job.filename}'?\n\nThis action cannot be undone.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Stop any running worker for this job
                if job.job_id in self.print_workers:
                    worker = self.print_workers[job.job_id]
                    worker.quit()
                    worker.wait()
                    del self.print_workers[job.job_id]
                
                # Clean up file
                if os.path.exists(job.file_path):
                    try:
                        os.remove(job.file_path)
                    except Exception as e:
                        logger.warning(f"Could not delete file {job.file_path}: {e}")
                
                # Remove from database
                logger.info(f"[DEBUG_DELETE] Before delete: {job.job_id}")
                job = self.db.merge(job)
                self.db.delete(job)
                self.db.commit()
                
                # Verify deletion from DB
                from shared.database import PrintJob
                still_exists = self.db.query(PrintJob).filter(PrintJob.job_id == job.job_id).first()
                logger.info(f"[DEBUG_DELETE] After commit: still in DB? {bool(still_exists)}")
                
                # Refresh jobs list
                self.load_print_jobs()
                
                # Verify deletion from map
                in_map = job.job_id in self.job_cards_map
                logger.info(f"[DEBUG_DELETE] After refresh: still in job_cards_map? {in_map}")
                
                QMessageBox.information(self, "Success", "Job deleted successfully")
                
        except Exception as e:
            logger.error(f"Error deleting job: {e}")
            QMessageBox.warning(self, "Error", f"Failed to delete job: {str(e)}")

    def clear_completed_jobs(self):
        """Clear completed jobs from database"""
        try:
            completed_jobs = self.db.query(PrintJob).filter(
                PrintJob.shop_id == self.shopkeeper_data['shop_id'],
                PrintJob.status == 'Completed'
            ).all()
            
            for job in completed_jobs:
                # Clean up files
                if os.path.exists(job.file_path):
                    os.remove(job.file_path)
                self.db.delete(job)
            
            self.db.commit()
            self.load_print_jobs()
            
            QMessageBox.information(self, "Success", f"Cleared {len(completed_jobs)} completed jobs")
            
        except Exception as e:
            logger.error(f"Error clearing completed jobs: {e}")
            QMessageBox.warning(self, "Error", f"Failed to clear jobs: {str(e)}")
    
    def download_receipt(self, job):
        """Placeholder: Download receipt for a job (extend as needed)"""
        try:
            QMessageBox.information(self, "Receipt", f"Receipt downloaded for job {job.job_id[:8]}")
        except Exception as e:
            logger.error(f"Error downloading receipt: {e}")

    # ---------------------------------------------------------
    # Selection Mode & Bulk Actions Implementation
    # ---------------------------------------------------------
    def handle_job_selection(self, job_id, state):
        """Handle individual job selection/deselection"""
        try:
            if state == Qt.Checked:
                self.selected_job_ids.add(job_id)
                # Visual feedback for card
                if job_id in self.job_cards_map:
                    card = self.job_cards_map[job_id]['card']
                    card.setStyleSheet("QFrame { background-color: #f0f9ff; border: 2px solid #3b82f6; border-radius: 8px; padding: 12px 20px; }")
            else:
                self.selected_job_ids.discard(job_id)
                # Reset visual feedback
                if job_id in self.job_cards_map:
                    card = self.job_cards_map[job_id]['card']
                    card.setStyleSheet("QFrame { background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 20px; }")
            
            # Show/hide selection bar based on count
            if len(self.selected_job_ids) > 0:
                self.selection_bar.setVisible(True)
                self.selection_mode = True
            else:
                self.selection_bar.setVisible(False)
                self.selection_mode = False
            
            self.update_selection_count()
        except Exception as e:
            logger.error(f"Error handling job selection: {e}")

    def update_selection_count(self):
        """Update the number of selected items in the selection bar"""
        if hasattr(self, 'sel_count_label'):
            count = len(self.selected_job_ids)
            self.sel_count_label.setText(f"{count} selected")

    def exit_selection_mode(self):
        """Clear all selections and hide the selection bar"""
        try:
            self.selected_job_ids.clear()
            self.selection_bar.setVisible(False)
            self.selection_mode = False
            
            # Reset all card styles
            for row_data in self.job_cards_map.values():
                card = row_data['card']
                card.setStyleSheet("QFrame { background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 20px; }")
                # If there's a checkbox in the card (optional for future), uncheck it here
                
            self.update_selection_count()
        except Exception as e:
            logger.error(f"Error exiting selection mode: {e}")

    def toggle_all_jobs(self, state):
        """Select or deselect all visible jobs"""
        try:
            # We want to select all jobs that are currently mapped
            all_ids = list(self.job_cards_map.keys())
            
            if state == Qt.Checked:
                for jid in all_ids:
                    self.handle_job_selection(jid, Qt.Checked)
            else:
                self.exit_selection_mode()
        except Exception as e:
            logger.error(f"Error toggling all jobs: {e}")

    def bulk_print_jobs(self):
        """Print all selected jobs"""
        if not self.selected_job_ids:
            return
            
        jobs_to_print = [self.job_cards_map[jid]['job'] for jid in self.selected_job_ids if jid in self.job_cards_map]
        if not jobs_to_print:
            return
            
        reply = QMessageBox.question(
            self, "Bulk Print", 
            f"Are you sure you want to print {len(jobs_to_print)} selected jobs?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            for job in jobs_to_print:
                self.print_job(job)
            self.exit_selection_mode()

    def bulk_view_jobs(self):
        """View the selected job correctly (Open first selected)"""
        try:
            import os
            
            # Step 1: Validate selection
            if not self.selected_job_ids:
                QMessageBox.warning(self, "View Job", "Please select a job to view.")
                return
                
            # Step 2: Resolve file path safely
            # Get selected jobs
            selected_ids = sorted(list(self.selected_job_ids))
            first_id = selected_ids[0]
            
            if first_id not in self.job_cards_map:
                QMessageBox.warning(self, "View Job", "Please select a job to view.")
                return
                
            job_data = self.job_cards_map[first_id]
            job = job_data.get('job')
            
            if not job:
                QMessageBox.critical(self, "Error", "Job data missing for the selected item.")
                return
            
            file_path = getattr(job, 'file_path', None)
            
            if job.cloudinary_public_id:
                import webbrowser
                from shared.cloudinary_helper import get_cloudinary_url
                url = get_cloudinary_url(job.cloudinary_public_id)
                webbrowser.open(url)
            elif file_path and os.path.exists(file_path):
                try:
                    os.startfile(file_path)
                except Exception as e:
                    logger.error(f"Error opening file {file_path}: {e}")
                    QMessageBox.critical(self, "Error", "Unable to open the file. Please check file permissions.")
            else:
                QMessageBox.critical(self, "File Error", "File not found for this job.")
                
        except Exception as e:
            logger.error(f"Fatal error in bulk_view_jobs: {e}")
            # Avoid the generic error message as requested, but log it

    def bulk_download_jobs(self):
        """Download all selected jobs"""
        if not self.selected_job_ids:
            return
            
        jobs_to_download = [self.job_cards_map[jid]['job'] for jid in self.selected_job_ids if jid in self.job_cards_map]
        if not jobs_to_download:
            return
            
        # Instruction says: "Add a safe stub that shows a message dialog"
        # We can implement a simple copy-to-folder or just the stub.
        # Let's do the stub first as requested.
        
        try:
            suggested_dir = QFileDialog.getExistingDirectory(self, "Select Download Directory")
            if suggested_dir:
                import shutil
                count = 0
                for job in jobs_to_download:
                    if os.path.exists(job.file_path):
                        dest = os.path.join(suggested_dir, os.path.basename(job.file_path))
                        # Handle duplicate filenames
                        if os.path.exists(dest):
                            base, ext = os.path.splitext(os.path.basename(job.file_path))
                            dest = os.path.join(suggested_dir, f"{base}_{job.job_id[:4]}{ext}")
                        shutil.copy2(job.file_path, dest)
                        count += 1
                
                QMessageBox.information(self, "Download Complete", f"Successfully downloaded {count} jobs to {suggested_dir}")
                self.exit_selection_mode()
        except Exception as e:
            logger.error(f"Error downloading jobs: {e}")
            QMessageBox.warning(self, "Download Error", f"An error occurred while downloading: {str(e)}")

    def bulk_cancel_jobs(self):
        """Cancel all selected jobs"""
        if not self.selected_job_ids:
            return
            
        jobs_to_cancel = [self.job_cards_map[jid]['job'] for jid in self.selected_job_ids if jid in self.job_cards_map]
        
        reply = QMessageBox.question(
            self, "Bulk Cancel", 
            f"Are you sure you want to cancel {len(jobs_to_cancel)} selected jobs?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            for job in jobs_to_cancel:
                # Skip internal confirmation for bulk actions
                self.stop_job(job, ask=False)
            self.exit_selection_mode()

    def bulk_delete_jobs(self):
        """Delete all selected jobs"""
        if not self.selected_job_ids:
            return
        
        # Safe extraction
        jobs_to_delete = []
        for jid in self.selected_job_ids:
            if jid not in self.job_cards_map:
                continue
            item = self.job_cards_map[jid]
            job = item.get("job")
            if job:
                jobs_to_delete.append(job)
        
        reply = QMessageBox.question(
            self, "Bulk Delete", 
            f"Are you sure you want to delete {len(jobs_to_delete)} selected jobs?\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            for job in jobs_to_delete:
                # Direct deletion logic to avoid multiple confirmation dialogs
                try:
                    logger.info(f"[DEBUG_BULK_DELETE] Before delete: {job.job_id}")
                    # FIX 1: Attach Job to Active Session Before Delete
                    job = self.db.merge(job)
                    # Clean up file
                    if os.path.exists(job.file_path):
                        os.remove(job.file_path)
                    # Remove from database
                    self.db.delete(job)
                except Exception as e:
                    logger.error(f"Error in bulk deletion for job {job.job_id}: {e}")
            
            self.db.commit()
            logger.info("[DEBUG_BULK_DELETE] After commit")
            self.load_print_jobs()
            
            # Post-refresh check
            still_in_map = [jid for jid in [j.job_id for j in jobs_to_delete] if jid in self.job_cards_map]
            logger.info(f"[DEBUG_BULK_DELETE] After refresh: stale IDs in map? {still_in_map}")
            
            self.exit_selection_mode()
            QMessageBox.information(self, "Success", "Selected jobs deleted.")
    
    def setup_timer(self):
        """Setup refresh timer"""
        self.timer = QTimer()
        self.timer.timeout.connect(self.timer_refresh)
        self.timer.start(10000)  # Refresh every 10 seconds (silent background refresh)
        
        # Real-time status monitoring timer
        self.status_monitor_timer = QTimer()
        self.status_monitor_timer.timeout.connect(self.monitor_active_jobs)
        self.status_monitor_timer.start(2000)  # Check every 2 seconds

        # Phase 4: Token Refresh Timer (every 30 minutes)
        self.token_refresh_timer = QTimer()
        self.token_refresh_timer.timeout.connect(self.refresh_session_token)
        self.token_refresh_timer.start(30 * 60 * 1000) # 30 minutes
        
        # Fallback polling timer (disabled by default)
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.load_print_jobs)
        # If WS hasn't connected in 3s, start polling, then stop when connected
        try:
            # Start polling after 3 seconds if WebSocket not connected
            def start_polling_if_needed():
                if not self.websocket_client or not self.websocket_client.is_connected():
                    self.poll_timer.start(5000)
            QTimer.singleShot(3000, start_polling_if_needed)
        except Exception:
            pass
    
    def timer_refresh(self):
        """Timer refresh - loads jobs and checks for auto-printing"""
        if not getattr(self, '_suspend_jobs_refresh', False):
            # TRACE K: Dashboard refreshed job list via polling
            # Note: We'll log specific job_id in load_print_jobs if we can identify it
            logger.info("TRACE K: Dashboard refreshing job list via polling")
            self.load_print_jobs()
        
        # Update dashboard KPIs and status indicators
        if self.current_page == "dashboard":
            self.update_dashboard_kpis()

    @safe_ui_action("MONITOR_ACTIVE_JOBS")
    def monitor_active_jobs(self):
        """Monitor active print jobs for real-time status updates"""
        try:
            # Get active jobs (printing or already in spooler)
            # DO NOT monitor 'Pending' jobs here - they are handled by the popup queue 
            # and only begin polling AFTER being sent to the printer in print_job().
            # Monitoring 'Pending' too early causes them to time out and show 'Failed'.
            active_jobs = self.db.query(PrintJob).filter(
                PrintJob.shop_id == self.shopkeeper_data['shop_id'],
                PrintJob.status.in_(['Processing', 'Printing', 'In Queue', 'Printing Started'])
            ).all()
            
            for job in active_jobs:
                # Check if we're already monitoring this job
                if job.job_id not in getattr(self.printer_manager, 'job_status_threads', {}):
                    # Start monitoring this job
                    def status_callback(job_id, status, progress, details):
                        self.report_job_status(job_id, status, progress, details)
                    
                    # Start monitoring this job
                    self.printer_manager.start_job_status_polling(job.job_id, status_callback)
                    
        except Exception as e:
            logger.error(f"Error monitoring active jobs: {e}")
        
        # Check for pending jobs in auto mode
        if self.auto_mode:
            self.check_and_print_pending_jobs()
        # Update current printer status label
        try:
            current = self.printer_manager.current_printer
            if current:
                ok, msg = self.printer_manager.test_printer()
                suffix = msg.split(" is ")[-1] if ok else 'Unknown'
                # Keep the printer name part stable
                if hasattr(self, 'printer_status_label'):
                    self.printer_status_label.setText(f"Current: {current} — {suffix}")
        except Exception:
            pass

    def refresh_session_token(self):
        """Automatically refresh the JWT session token"""
        try:
            # Only refresh if we have a token
            if not self.api_client.session_token:
                return
                
            logger.debug("Attempting to refresh API session token")
            success, data, error = self.api_client.refresh_token()
            if success and data and 'session_token' in data:
                new_token = data['session_token']
                self.shopkeeper_data['session_token'] = new_token
                # ApiClient.refresh_token() already calls set_session_token internally
                # Sync with AuthManager's client as well
                self.auth_manager.api_client.set_session_token(new_token)
                self.session_token = new_token
                logger.info("Session token refreshed successfully")
            else:
                logger.warning(f"Session token refresh failed: {error}")
        except Exception as e:
            logger.error(f"Error refreshing session token: {e}")

    
    def setup_shortcuts(self):
        """Setup keyboard shortcuts"""
        # F5 for refresh
        refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        refresh_shortcut.activated.connect(self.manual_refresh)
        
        # Ctrl+R for refresh (alternative)
        ctrl_r_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        ctrl_r_shortcut.activated.connect(self.manual_refresh)
        
        # Switch view on resize
    
    def report_job_status(self, job_id, status, progress=0, details=''):
        """
        Phase 5: Centralized job status reporting with authoritative WebSocket first, 
        and DB write as fallback.
        """
        try:
            # 1. Authoritative: Send to backend via WebSocket/API
            # Get printer_name from printer_manager tracking
            printer_name = getattr(self.printer_manager, 'job_printers', {}).get(job_id)
            
            ws_success = False
            if self.websocket_client and self.websocket_client.is_connected():
                ws_success = self.websocket_client.report_job_status(
                    job_id=job_id,
                    status=status,
                    progress=progress,
                    details=details,
                    printer_name=printer_name
                )
            
            # 2. DB write is NOT done here — this method runs on a background
            # poller thread, and creating a separate SessionLocal() races with
            # self.db writes on the main thread (on_job_completed / on_job_failed).
            # Instead, we defer the DB write to update_job_status_in_ui() which
            # runs on the main thread via thread_safe_signal, serializing all
            # PrintJob row writes through self.db.
            if not ws_success:
                logger.info(f"WS disconnected for job {job_id} -> {status}; DB write deferred to main thread")
            
            # 3. UI Update + DB write (deferred to main thread via signal)
            self.thread_safe_signal.emit("update_job_status", (job_id, status, progress, details))
            
        except Exception as e:
            logger.error(f"Error in report_job_status top-level: {e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self.update_jobs_view_mode()
        except Exception:
            pass
    
    def update_jobs_view_mode(self):
        """Always show cards (unified UI with Connect Printers page)"""
        if not hasattr(self, 'jobs_table'):
            return
        # Always hide table and show cards for unified UI
        if hasattr(self, 'jobs_cards_scroll'):
            self.jobs_table.hide()
            self.jobs_cards_scroll.show()
    
    def showEvent(self, event):
        """Handle window show event - mark dashboard as ready and check printer status after delay"""
        super().showEvent(event)
        # Mark dashboard as ready (authenticated and visible)
        self.dashboard_ready = True
        # Check and show popup if printer is disconnected (after 3-second delay)
        QTimer.singleShot(3000, self.delayed_printer_disconnect_check)
    
    def delayed_printer_disconnect_check(self):
        """Check printer status and show popup after dashboard is shown (called after 3-second delay)"""
        try:
            # Only proceed if dashboard is still visible and ready
            if not self.isVisible() or not self.dashboard_ready:
                return
            # Check and show popup if printer is disconnected
            self.check_and_show_printer_disconnect_popup()
        except Exception as e:
            logger.error(f"Error in delayed printer disconnect check: {e}")
    
    def closeEvent(self, event):
        """Handle window close event"""

        # Agar logout flow se aa raha hai to sirf close karo, force quit mat karo
        if getattr(self, '_is_logout_destroy', False):
            logger.info("Dashboard window closed after logout cleanup")
            event.accept()
            return

        # Normal window close (X button) — tab bhi graceful shutdown
        logger.info("Dashboard window closing via X button - starting shutdown...")
        event.accept()
        self.hide()

        # Force exit after 3 seconds max (safety net)
        def force_exit_after_timeout():
            logger.warning("Shutdown timeout reached, forcing exit")
            import os
            try:
                os._exit(0)
            except Exception:
                import sys
                sys.exit(0)

        from PyQt5.QtCore import QTimer
        QTimer.singleShot(3000, force_exit_after_timeout)

        # Run cleanup + quit in background
        import threading

        def shutdown_cleanup():
            try:
                self._stop_all_timers()
                self._stop_websocket_services()
                self._stop_printer_services()
                self._stop_background_workers()
                self._close_database()
            except Exception as e:
                logger.error(f"Error during shutdown cleanup: {e}")
            finally:
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, self._force_application_quit)

        t = threading.Thread(target=shutdown_cleanup, daemon=True)
        t.start()

    def _check_system_resume(self):
        import time
        current_time = time.time()
        if current_time - self._last_activity_time > 20:
            logger.info("System resume detected - recovering services")
            self._recover_after_sleep()
        self._last_activity_time = current_time

    def _recover_after_sleep(self):
        try:
            logger.info("Starting sleep recovery...")
            if hasattr(self, 'printer_manager') and self.printer_manager:
                try:
                    self.printer_manager.reinitialize_printer()
                except Exception as e:
                    logger.error(f"Printer recovery failed: {e}")
            if hasattr(self, 'websocket_client') and self.websocket_client:
                try:
                    self.websocket_client.reconnect()
                except Exception as e:
                    logger.error(f"WebSocket reconnect failed: {e}")
            try:
                self.refresh_job_list()
            except Exception as e:
                logger.error(f"Job refresh failed: {e}")
            logger.info("Sleep recovery completed")
        except Exception as e:
            logger.error(f"Sleep recovery failed: {e}")

    
    def _stop_all_timers(self):
        """Stop all QTimer instances"""
        logger.info("Stopping all timers...")
        
        timers_to_stop = [
            'timer', 'status_monitor_timer', 'poll_timer', 'printer_connectivity_timer',
            'websocket_reconnect_timer', 'icon_timer',
            'payments_refresh_timer', 'connect_printers_auto_refresh_timer'
        ]
        
        for timer_name in timers_to_stop:
            try:
                if hasattr(self, timer_name):
                    timer = getattr(self, timer_name)
                    if timer and hasattr(timer, 'stop'):
                        timer.stop()
                        logger.debug(f"Stopped timer: {timer_name}")
            except Exception as e:
                logger.error(f"Error stopping timer {timer_name}: {e}")
    
    def _stop_websocket_services(self):
        """Stop WebSocket client and reconnection threads"""
        logger.info("Stopping WebSocket client...")
        
        try:
            if self.websocket_client:
                # Stop WebSocket client with aggressive timeout
                self.websocket_client.stop()
                
                # Force stop if still running after a short delay
                import threading
                def force_stop_websocket():
                    try:
                        if hasattr(self.websocket_client, 'client') and self.websocket_client.client:
                            if hasattr(self.websocket_client.client, 'running') and self.websocket_client.client.running:
                                logger.warning("WebSocket still running, forcing stop")
                                self.websocket_client.client.running = False
                    except Exception:
                        pass
                
                # Schedule force stop after 100ms
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(100, force_stop_websocket)
                
                logger.info("WebSocket client stopped")
            else:
                logger.debug("No WebSocket client to stop")
        except Exception as e:
            logger.error(f"Error stopping WebSocket client: {e}")
    
    def _stop_printer_services(self):
        """Stop printer discovery and connectivity services"""
        logger.info("Stopping printer discovery...")
        
        try:
            if hasattr(self, 'printer_manager') and self.printer_manager:
                self.printer_manager.cleanup()
                logger.info("Printer manager cleanup completed")
            else:
                logger.debug("No printer manager to cleanup")
        except Exception as e:
            logger.error(f"Error cleaning up printer manager: {e}")
    
    def _stop_background_workers(self):
        """Terminate all background workers with aggressive timeout"""
        logger.info("Stopping background workers...")
        
        try:
            if hasattr(self, 'print_workers') and self.print_workers:
                for job_id, worker in list(self.print_workers.items()):
                    try:
                        logger.debug(f"Stopping worker for job {job_id}")
                        
                        # Try graceful quit first
                        worker.quit()
                        
                        # Very short timeout for graceful shutdown
                        if not worker.wait(500):  # 500ms timeout
                            logger.warning(f"Worker for job {job_id} timed out, forcing termination")
                            worker.terminate()
                            
                            # Very short timeout for force termination
                            if not worker.wait(200):  # 200ms timeout
                                logger.error(f"Failed to terminate worker for job {job_id}, killing process")
                                # Force kill the worker thread
                                try:
                                    import threading
                                    if hasattr(worker, '_thread') and worker._thread.is_alive():
                                        # This is a last resort - force kill
                                        pass  # Let the process exit handle it
                                except Exception:
                                    pass
                        else:
                            logger.debug(f"Worker for job {job_id} stopped successfully")
                            
                    except Exception as e:
                        logger.error(f"Error stopping worker for job {job_id}: {e}")
                
                # Clear workers dictionary immediately
                self.print_workers.clear()
                logger.info("All background workers stopped")
            else:
                logger.debug("No background workers to stop")
        except Exception as e:
            logger.error(f"Error stopping background workers: {e}")
    
    def _close_database(self):
        """Close database session"""
        logger.info("Closing DB session...")
        
        try:
            if hasattr(self, 'db') and self.db:
                self.db.close()
                logger.info("Database session closed")
            else:
                logger.debug("No database session to close")
        except Exception as e:
            logger.error(f"Error closing database: {e}")
    
    def _force_application_quit(self):
        """Force application to quit immediately"""
        logger.info("Forcing application quit...")
        
        try:
            # Get the QApplication instance and quit
            from PyQt5.QtWidgets import QApplication
            from PyQt5.QtCore import QCoreApplication
            import sys
            import os
            
            app = QApplication.instance()
            if app:
                # Try multiple methods to ensure quit
                app.quit()
                QCoreApplication.quit()
                app.exit(0)
                logger.info("QApplication quit methods called")
            else:
                logger.warning("No QApplication instance found")
            
            # Force process termination as last resort
            def force_exit():
                try:
                    logger.info("Force exiting process...")
                    os._exit(0)  # More aggressive than sys.exit()
                except Exception:
                    sys.exit(0)
            
            # Schedule force exit after a short delay
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(100, force_exit)  # 100ms delay
            
        except Exception as e:
            logger.error(f"Error forcing application quit: {e}")
            # Last resort - force exit immediately
            import sys
            import os
            try:
                os._exit(0)
            except Exception:
                sys.exit(0)

    def logout(self):
        """Perform logout and return to login window"""
        logger.info("Logout requested - performing cleanup...")

        # Immediately disable the logout button to prevent double-click
        try:
            sender = self.sender()
            if sender:
                sender.setEnabled(False)
        except Exception:
            pass

        # Stop all timers immediately (safe on UI thread, no blocking)
        self._stop_all_timers()

        # Close database immediately (non-blocking)
        self._close_database()

        # Show login window immediately — don't wait for cleanup
        if self.on_logout_cb:
            self.on_logout_cb()

        # Hide dashboard immediately
        self.hide()

        # Now do all blocking cleanup in a background thread
        import threading

        def background_cleanup():
            try:
                # API logout (blocking network call — safe in background thread)
                if hasattr(self, 'auth_manager'):
                    shop_id = self.shopkeeper_data.get('shop_id')
                    logger.info(f"Triggering API logout for shop_id: {shop_id}")
                    try:
                        success, message = self.auth_manager.logout_shopkeeper(shop_id)
                        if success:
                            logger.info(f"API logout successful: {message}")
                        else:
                            logger.warning(f"API logout failed: {message}")
                    except Exception as e:
                        logger.error(f"API logout error: {e}")

                # Stop WebSocket (may block briefly, safe in background)
                try:
                    self._stop_websocket_services()
                    if self.websocket_client:
                        self.websocket_client = None
                except Exception as e:
                    logger.error(f"WebSocket stop error: {e}")

                # Stop printer services (has join timeout, safe in background)
                try:
                    self._stop_printer_services()
                except Exception as e:
                    logger.error(f"Printer stop error: {e}")

                # Stop background workers (has wait() calls, safe in background)
                try:
                    self._stop_background_workers()
                except Exception as e:
                    logger.error(f"Worker stop error: {e}")

                logger.info("Background cleanup completed successfully")

            except Exception as e:
                logger.error(f"Error during background cleanup: {e}")
            finally:
                # Schedule window destruction on UI thread after cleanup
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, self._destroy_window)

        cleanup_thread = threading.Thread(target=background_cleanup, daemon=True)
        cleanup_thread.start()

    def _destroy_window(self):
        """Safely destroy the dashboard window after cleanup is complete"""
        try:
            logger.info("Destroying dashboard window...")
            # Disconnect close event to prevent _force_application_quit from running
            self._is_logout_destroy = True
            self.close()
        except Exception as e:
            logger.error(f"Error destroying window: {e}")    

    def stop_job(self, job, ask=True):
        """Stop a queued/printing job (Hardened - FIX 1-5)"""
        if ask:
            self._cancel_dialog_active = True
            
        try:
            # FIX 1: Fresh status check to prevent corrupting completed history
            from shared.database import PrintJob
            self.db.expire_all()
            db_job = self.db.query(PrintJob).filter(PrintJob.job_id == job.job_id).first()
            
            if not db_job:
                return
                
            if db_job.status in ["Completed", "Failed"]:
                self.show_toast(f"Action Invalid: Job is already {db_job.status}")
                return

            if ask:
                reply = QMessageBox.question(
                    self,
                    "Stop Job",
                    f"Stop job '{job.filename}' now?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return
            
            # FIX 3: Immediate soft-cancel for Pending jobs
            if db_job.status in ['Pending', 'In Queue']:
                self.report_job_status(job.job_id, 'Cancelled', 0, "Requested by user")
                self.load_print_jobs()
                self.show_toast("Job removed from queue.")
                return

            # Attempt to cancel via printer manager (returns success, message)
            ok, message = self.printer_manager.cancel_job(job.job_id)
            
            # FIX 2: Removal of UI thread blocking (DO NOT WAIT)
            if job.job_id in self.print_workers:
                try:
                    w = self.print_workers[job.job_id]
                    w.quit()
                    # We do NOT call w.wait() here to keep UI responsive
                    del self.print_workers[job.job_id]
                except Exception:
                    pass

            if ok:
                # Hardware stop confirmed (or best effort succeeded)
                self.report_job_status(job.job_id, 'Cancelled', 0, "Requested by user")
                self.load_print_jobs()
                if ask:
                    QMessageBox.information(self, "Stopped", f"Job stopped successfully.\n\n{message}")
            else:
                # Hardware stop failed - mark appropriately via authoritative reporter
                self.report_job_status(job.job_id, 'Stopping Failed', 0, message)
                self.load_print_jobs()
                if ask:
                    QMessageBox.warning(self, "Unable to Stop", f"{message}\n\nPrinting may continue if already processed by printer.")
        except Exception as e:
            logger.error(f"Error in hardened stop_job: {e}")
            try:
                if ask:
                    QMessageBox.warning(self, "Error", f"Failed to stop job: {str(e)}")
            except Exception:
                pass
        finally:
            if ask:
                self._cancel_dialog_active = False
                # Explicitly resume the popup queue after the ENTIRE cancel flow is gone.
                QTimer.singleShot(0, self.display_next_popup)

    def ensure_qr_code_exists(self):
        """Ensure QR code exists, generate if missing"""
        try:
            # Check if QR code path exists in shopkeeper data
            qr_path = self.shopkeeper_data.get('qr_code_path')
            
            # If path exists and file exists, return it
            if qr_path and os.path.exists(qr_path):
                return qr_path
            
            # If path doesn't exist or file is missing, generate new QR code
            from shared.qr_generator import generate_qr_code
            
            shop_id = self.shopkeeper_data['shop_id']
            shop_name = self.shopkeeper_data['shop_name']
            
            # Generate new QR code
            new_qr_path = generate_qr_code(shop_id, shop_name)
            
            # Update shopkeeper data
            self.shopkeeper_data['qr_code_path'] = new_qr_path
            
            # Update database
            try:
                from shared.database import Shopkeeper
                shopkeeper = self.db.query(Shopkeeper).filter(Shopkeeper.shop_id == shop_id).first()
                if shopkeeper:
                    shopkeeper.qr_code_path = new_qr_path
                    self.db.commit()
                    logger.info(f"Updated QR code path for shopkeeper {shop_id}")
            except Exception as e:
                logger.warning(f"Could not update QR code path in database: {e}")
            
            return new_qr_path
            
        except Exception as e:
            logger.error(f"Error ensuring QR code exists: {e}")
            return None

    def download_qr_code(self):
        """Allow user to download/save the QR code image"""
        try:
            qr_path = self.ensure_qr_code_exists()
            if not qr_path or not os.path.exists(qr_path):
                QMessageBox.warning(self, "QR Code", "QR code image not found")
                return
            suggested = os.path.join(os.path.expanduser('~'), f"qr_{self.shopkeeper_data['shop_name']}.png")
            save_path, _ = QFileDialog.getSaveFileName(self, "Save QR Code", suggested, "Images (*.png *.jpg *.jpeg *.bmp)")
            if save_path:
                import shutil
                shutil.copyfile(qr_path, save_path)
                QMessageBox.information(self, "Saved", f"QR code saved to:\n{save_path}")
        except Exception as e:
            logger.error(f"Error saving QR: {e}")
            QMessageBox.warning(self, "Error", f"Failed to save QR code: {str(e)}")

    def print_qr_code(self):
        """Print the QR code using current printer"""
        try:
            qr_path = self.ensure_qr_code_exists()
            if not qr_path or not os.path.exists(qr_path):
                QMessageBox.warning(self, "QR Code", "QR code image not found")
                return
            if not self.printer_manager.current_printer:
                QMessageBox.warning(self, "Printer", "Please select a printer first")
                return
            # Build minimal settings for image print
            settings = {
                'copies': 1,
                'page_range': '',
                'page_size': 'A4',
                'orientation': 'Portrait',
                'print_side': 'Single',
                'color_mode': 'Black & White',
                'layout_pages': 1
            }
            ok, msg = self.printer_manager.print_document_with_settings(qr_path, 'png', settings)
            if ok:
                QMessageBox.information(self, "Print", "QR code sent to printer")
            else:
                QMessageBox.warning(self, "Print", f"Failed to print QR: {msg}")
        except Exception as e:
            logger.error(f"Error printing QR: {e}")
            QMessageBox.warning(self, "Error", f"Failed to print QR code: {str(e)}")
