from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTokens:
    app_background: str = "#0F172A"
    surface: str = "#1E293B"
    surface_secondary: str = "#263449"
    sidebar: str = "#0B1220"
    sidebar_hover: str = "#172338"
    sidebar_selected: str = "#25456B"
    primary: str = "#2563EB"
    primary_hover: str = "#1D4ED8"
    primary_pressed: str = "#1E40AF"
    success: str = "#15803D"
    success_soft: str = "#123B2A"
    warning: str = "#F59E0B"
    warning_soft: str = "#4A3510"
    danger: str = "#F87171"
    danger_soft: str = "#4A2025"
    info_soft: str = "#173A61"
    muted: str = "#94A3B8"
    text: str = "#F1F5F9"
    text_soft: str = "#CBD5E1"
    border: str = "#334155"
    border_strong: str = "#475569"
    selected: str = "#1E3A5F"
    disabled: str = "#64748B"
    radius_small: int = 4
    radius: int = 7
    radius_large: int = 10
    space_1: int = 4
    space_2: int = 8
    space_3: int = 12
    space_4: int = 16
    space_5: int = 24
    space_6: int = 32


TOKENS = ThemeTokens()


def load_stylesheet() -> str:
    t = TOKENS
    return f"""
QMainWindow, QDialog {{
    background: {t.app_background};
}}

QWidget {{
    color: {t.text};
    font-family: "Segoe UI";
    font-size: 13px;
}}

QWidget#MainContent {{
    background: {t.app_background};
}}

QFrame#Sidebar {{
    background: {t.sidebar};
    border: 0;
}}

QLabel[role="brand"] {{
    color: #F8FAFC;
    font-size: 17px;
    font-weight: 600;
}}

QLabel[role="version"] {{
    color: #94A3B8;
    font-size: 11px;
}}

QLabel[role="navGroup"] {{
    color: #7F8DA3;
    font-size: 10px;
    font-weight: 600;
    padding: 14px 12px 5px 12px;
}}

QListWidget#SidebarNav {{
    background: transparent;
    color: #D7DFEA;
    border: 0;
    outline: 0;
    padding: 0 8px 8px 8px;
}}

QListWidget#SidebarNav::item {{
    border: 0;
    border-radius: {t.radius}px;
    min-height: 34px;
    padding: 4px 10px;
    margin: 1px 0;
}}

QListWidget#SidebarNav::item:hover {{
    background: {t.sidebar_hover};
    color: #FFFFFF;
}}

QListWidget#SidebarNav::item:selected {{
    background: {t.sidebar_selected};
    color: #FFFFFF;
    border-left: 3px solid #60A5FA;
}}

QFrame#TopCommandBar {{
    background: {t.surface};
    border: 0;
    border-bottom: 1px solid {t.border};
}}

QLabel[role="pageTitle"] {{
    color: {t.text};
    font-size: 22px;
    font-weight: 600;
}}

QLabel[role="pageDescription"] {{
    color: {t.muted};
    font-size: 12px;
}}

QLabel[role="sectionTitle"] {{
    color: {t.text};
    font-size: 16px;
    font-weight: 600;
}}

QLabel[role="sectionDescription"], QLabel[tone="muted"] {{
    color: {t.muted};
    font-size: 12px;
}}

QLabel[role="metricValue"] {{
    color: {t.text};
    font-size: 26px;
    font-weight: 600;
}}

QLabel[role="metricLabel"] {{
    color: {t.text_soft};
    font-size: 12px;
    font-weight: 600;
}}

QLabel[role="metricSupport"] {{
    color: {t.muted};
    font-size: 11px;
}}

QFrame[surface="card"] {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius_large}px;
}}

QFrame[surface="subtle"] {{
    background: {t.surface_secondary};
    border: 1px solid {t.border};
    border-radius: {t.radius}px;
}}

QFrame[accent="primary"] {{ border-left: 3px solid {t.primary}; }}
QFrame[accent="success"] {{ border-left: 3px solid {t.success}; }}
QFrame[accent="warning"] {{ border-left: 3px solid {t.warning}; }}
QFrame[accent="danger"] {{ border-left: 3px solid {t.danger}; }}
QFrame[accent="neutral"] {{ border-left: 3px solid {t.border_strong}; }}

QPushButton {{
    min-height: 30px;
    border: 1px solid {t.border_strong};
    border-radius: {t.radius}px;
    padding: 2px 12px;
    background: {t.surface};
    color: {t.text_soft};
    font-weight: 500;
}}

QPushButton:hover {{
    background: {t.surface_secondary};
    border-color: #94A3B8;
}}

QPushButton:pressed {{
    background: #334155;
}}

QPushButton:focus {{
    border: 2px solid #60A5FA;
    padding: 1px 11px;
}}

QPushButton[role="primary"] {{
    background: {t.primary};
    border-color: {t.primary};
    color: #FFFFFF;
    font-weight: 600;
}}

QPushButton[role="primary"]:hover {{ background: {t.primary_hover}; border-color: {t.primary_hover}; }}
QPushButton[role="primary"]:pressed {{ background: {t.primary_pressed}; border-color: {t.primary_pressed}; }}

QPushButton[role="secondary"] {{
    background: {t.surface};
    border-color: {t.border_strong};
    color: {t.text};
}}

QPushButton[role="tertiary"] {{
    background: transparent;
    border-color: transparent;
    color: {t.primary};
}}

QPushButton[role="tertiary"]:hover {{ background: {t.selected}; border-color: {t.selected}; }}

QPushButton[role="danger"] {{
    background: {t.surface};
    border-color: #FCA5A5;
    color: {t.danger};
    font-weight: 600;
}}

QPushButton[role="danger"]:hover {{ background: {t.danger_soft}; border-color: #EF4444; }}

QPushButton:disabled {{
    background: #263449;
    border-color: {t.border};
    color: {t.disabled};
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
    min-height: 30px;
    background: {t.surface};
    border: 1px solid {t.border_strong};
    border-radius: {t.radius_small}px;
    padding: 1px 8px;
    selection-background-color: {t.primary};
    selection-color: #FFFFFF;
}}

QTextEdit, QPlainTextEdit {{
    background: {t.surface};
    border: 1px solid {t.border_strong};
    border-radius: {t.radius_small}px;
    padding: 7px;
    selection-background-color: {t.primary};
    selection-color: #FFFFFF;
}}

QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QTextEdit:hover, QPlainTextEdit:hover {{
    border-color: #94A3B8;
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid #60A5FA;
}}

QLineEdit[fieldState="error"], QComboBox[fieldState="error"] {{
    border: 2px solid #DC2626;
    background: #3B1F25;
}}

QCheckBox {{ spacing: 7px; min-height: 24px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}

QGroupBox {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius}px;
    margin-top: 12px;
    padding: 12px 10px 8px 10px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {t.text};
}}

QTableWidget, QTableView {{
    background: {t.surface};
    alternate-background-color: {t.surface_secondary};
    border: 1px solid {t.border};
    border-radius: {t.radius}px;
    gridline-color: transparent;
    selection-background-color: {t.selected};
    selection-color: {t.text};
    outline: 0;
}}

QTableWidget::item, QTableView::item {{
    border-bottom: 1px solid #334155;
    padding: 4px 8px;
}}

QTableWidget::item:hover, QTableView::item:hover {{ background: #2B3A50; }}
QTableWidget::item:selected, QTableView::item:selected {{ background: {t.selected}; color: {t.text}; }}

QHeaderView::section {{
    background: {t.surface_secondary};
    color: {t.text_soft};
    border: 0;
    border-bottom: 1px solid {t.border_strong};
    padding: 8px;
    font-size: 11px;
    font-weight: 600;
}}

QTabWidget::pane {{
    border: 1px solid {t.border};
    background: {t.surface};
    border-radius: 0 0 {t.radius}px {t.radius}px;
}}

QTabBar::tab {{
    background: transparent;
    color: {t.muted};
    border: 0;
    border-bottom: 2px solid transparent;
    padding: 9px 13px;
    font-weight: 500;
}}

QTabBar::tab:hover {{ color: {t.text}; background: {t.surface_secondary}; }}
QTabBar::tab:selected {{ color: {t.primary}; border-bottom-color: {t.primary}; font-weight: 600; }}

QLabel[badge="true"] {{
    border-radius: 9px;
    padding: 2px 7px;
    font-size: 10px;
    font-weight: 600;
}}

QLabel[badgeTone="primary"] {{ background: {t.info_soft}; color: #1D4ED8; }}
QLabel[badgeTone="success"] {{ background: {t.success_soft}; color: #166534; }}
QLabel[badgeTone="warning"] {{ background: {t.warning_soft}; color: #92400E; }}
QLabel[badgeTone="danger"] {{ background: {t.danger_soft}; color: #991B1B; }}
QLabel[badgeTone="neutral"] {{ background: #334155; color: #CBD5E1; }}

QFrame[bannerTone="info"] {{ background: #172F4D; border: 1px solid #28598B; border-radius: {t.radius}px; }}
QFrame[bannerTone="success"] {{ background: #123B2A; border: 1px solid #23734A; border-radius: {t.radius}px; }}
QFrame[bannerTone="warning"] {{ background: #4A3510; border: 1px solid #8A641A; border-radius: {t.radius}px; }}
QFrame[bannerTone="danger"] {{ background: #4A2025; border: 1px solid #8F3A44; border-radius: {t.radius}px; }}
QFrame[bannerTone="private"] {{ background: #302653; border: 1px solid #604E99; border-radius: {t.radius}px; }}

QProgressBar {{
    min-height: 7px;
    max-height: 7px;
    border: 0;
    border-radius: 3px;
    background: #334155;
    text-align: center;
}}

QProgressBar::chunk {{ background: {t.primary}; border-radius: 3px; }}

QSplitter::handle {{ background: {t.border}; width: 1px; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #475569; border-radius: 5px; min-height: 28px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: #64748B; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #475569; border-radius: 5px; min-width: 28px; margin: 2px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QToolTip {{
    background: {t.sidebar};
    color: #F8FAFC;
    border: 1px solid #334155;
    padding: 5px 7px;
}}

QMenu {{ background: {t.surface}; border: 1px solid {t.border}; padding: 5px; }}
QMenu::item {{ padding: 7px 24px 7px 9px; border-radius: {t.radius_small}px; }}
QMenu::item:selected {{ background: {t.selected}; color: {t.text}; }}

QDialogButtonBox QPushButton {{ min-width: 88px; }}
"""


def set_button_role(button, role: str) -> None:
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)


def repolish(widget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
