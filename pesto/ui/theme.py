"""Design tokens shared by the HUD, tray and dashboard.

One restrained dark palette; colour is used only to encode state:
green = listening/dictation, blue = command (PASTA), amber = needs you,
red = failure. Everything else is neutral.
"""

from PySide6.QtGui import QColor, QFont

BG = QColor(17, 19, 23)
SURFACE = QColor(24, 27, 32)
SURFACE_2 = QColor(32, 36, 42)
BORDER = QColor(255, 255, 255, 22)
TEXT = QColor(236, 238, 241)
TEXT_2 = QColor(160, 166, 176)
TEXT_3 = QColor(110, 116, 126)

GREEN = QColor(74, 222, 128)
BLUE = QColor(96, 165, 250)
AMBER = QColor(251, 191, 36)
RED = QColor(248, 113, 113)
NEUTRAL = QColor(161, 161, 170)

HEX = {
    "bg": "#111317", "surface": "#181b20", "surface2": "#20242a", "border": "rgba(255,255,255,0.09)",
    "text": "#eceef1", "text2": "#a0a6b0", "text3": "#6e747e", "green": "#4ade80", "blue": "#60a5fa",
    "amber": "#fbbf24", "red": "#f87171",
}


def ui_font(size: float = 10.0, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont("Segoe UI Variable Text")
    if not f.exactMatch():
        f = QFont("Segoe UI")
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


STYLESHEET = f"""
QWidget {{ background: {HEX['bg']}; color: {HEX['text']}; font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 10pt; }}
QLabel[role="h1"] {{ font-size: 17pt; font-weight: 600; }}
QLabel[role="h2"] {{ font-size: 11.5pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {HEX['text2']}; }}
QLabel[role="faint"] {{ color: {HEX['text3']}; font-size: 9pt; }}
QLabel[role="metric"] {{ font-size: 20pt; font-weight: 600; }}
QFrame[role="card"] {{ background: {HEX['surface']}; border: 1px solid {HEX['border']}; border-radius: 10px; }}
QFrame[role="card"] QLabel, QFrame[role="card"] QWidget {{ background: transparent; }}
QFrame[role="card"] QLineEdit, QFrame[role="card"] QComboBox, QFrame[role="card"] QSpinBox {{ background: {HEX['surface2']}; }}
QListWidget#nav {{ background: {HEX['bg']}; border: none; outline: none; padding: 8px; }}
QListWidget#nav::item {{ padding: 9px 12px; border-radius: 7px; color: {HEX['text2']}; margin: 1px 0; }}
QListWidget#nav::item:selected {{ background: {HEX['surface2']}; color: {HEX['text']}; }}
QListWidget#nav::item:hover:!selected {{ background: {HEX['surface']}; }}
QPushButton {{ background: {HEX['surface2']}; border: 1px solid {HEX['border']}; border-radius: 7px; padding: 6px 14px; }}
QPushButton:hover {{ background: #2a2f37; }}
QPushButton[role="primary"] {{ background: #2563eb; border: none; color: white; }}
QPushButton[role="primary"]:hover {{ background: #3b82f6; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {HEX['surface2']}; border: 1px solid {HEX['border']};
    border-radius: 6px; padding: 5px 8px; selection-background-color: #2563eb; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {HEX['surface2']}; border: 1px solid {HEX['border']}; selection-background-color: #2563eb; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid #4b5563; background: {HEX['surface2']}; }}
QCheckBox::indicator:checked {{ background: #2563eb; border: 1px solid #3b82f6; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QTableView {{ background: {HEX['surface']}; border: 1px solid {HEX['border']}; border-radius: 8px; gridline-color: transparent;
    selection-background-color: #1e3a5f; alternate-background-color: #1b1e23; }}
QHeaderView::section {{ background: {HEX['surface']}; color: {HEX['text2']}; border: none; border-bottom: 1px solid {HEX['border']};
    padding: 6px 8px; font-weight: 600; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2c3139; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {HEX['surface2']}; color: {HEX['text']}; border: 1px solid {HEX['border']}; padding: 4px 6px; }}
QMenu {{ background: {HEX['surface']}; border: 1px solid {HEX['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {HEX['surface2']}; }}
QMenu::separator {{ height: 1px; background: {HEX['border']}; margin: 4px 8px; }}
"""
