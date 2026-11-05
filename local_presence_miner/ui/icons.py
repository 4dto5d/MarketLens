from __future__ import annotations

from PySide6.QtWidgets import QStyle, QWidget

ICON_MAP = {
    "search": QStyle.StandardPixmap.SP_FileDialogContentsView,
    "refresh": QStyle.StandardPixmap.SP_BrowserReload,
    "open": QStyle.StandardPixmap.SP_DialogOpenButton,
    "save": QStyle.StandardPixmap.SP_DialogSaveButton,
    "edit": QStyle.StandardPixmap.SP_FileDialogDetailedView,
    "delete": QStyle.StandardPixmap.SP_TrashIcon,
    "copy": QStyle.StandardPixmap.SP_FileDialogNewFolder,
    "settings": QStyle.StandardPixmap.SP_FileDialogListView,
    "report": QStyle.StandardPixmap.SP_FileIcon,
    "folder": QStyle.StandardPixmap.SP_DirOpenIcon,
    "next": QStyle.StandardPixmap.SP_ArrowForward,
    "previous": QStyle.StandardPixmap.SP_ArrowBack,
    "success": QStyle.StandardPixmap.SP_DialogApplyButton,
    "warning": QStyle.StandardPixmap.SP_MessageBoxWarning,
    "error": QStyle.StandardPixmap.SP_MessageBoxCritical,
    "info": QStyle.StandardPixmap.SP_MessageBoxInformation,
    "add": QStyle.StandardPixmap.SP_FileDialogNewFolder,
}


def app_icon(widget: QWidget, name: str):
    return widget.style().standardIcon(ICON_MAP.get(name, QStyle.StandardPixmap.SP_FileIcon))
