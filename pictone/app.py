import sys
import os
import queue
import threading
from pathlib import Path


def _configure_tk_runtime() -> None:
    if not getattr(sys, "frozen", False):
        return
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    tcl_library = bundle_root / "_tcl_data"
    tk_library = bundle_root / "_tk_data"
    if tcl_library.is_dir():
        os.environ["TCL_LIBRARY"] = str(tcl_library)
    if tk_library.is_dir():
        os.environ["TK_LIBRARY"] = str(tk_library)


_configure_tk_runtime()

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageTk

from .engine import build_matte, composition_crop_box, render_cutout, render_matte_preview, render_photo
from .face import suggest_layout
from .model import DocumentState, PHOTO_SIZES, ProcessingSettings
from .output import BatchExportRecord, collision_safe_path, make_print_sheet, save_image, validate_export, write_batch_report
from .preferences import AppPreferences, add_recent_file, load_preferences, save_preferences
from .quality import inspect_photo
from .widgets import COLORS, InspectorSection, PhotoViewport, ValueScale


APP_NAME = "证件照换底色"
APP_ICON_NAME = "app_icon.ico"
APP_BACKGROUND_NAME = "app_background.png"
IMAGE_TYPES = [("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp"), ("所有文件", "*.*")]
BACKGROUND_PRESETS = (
    ("蓝色", "#438EDB"),
    ("红色", "#E94B4B"),
    ("白色", "#FFFFFF"),
    ("浅灰", "#E8EBEF"),
    ("深蓝", "#1B365D"),
)


def prepare_app_background(image: Image.Image, width: int, height: int) -> Image.Image:
    """Create a softened, center-cropped background that fully covers the window."""
    width = max(1, int(width))
    height = max(1, int(height))
    source = image.convert("RGB")
    scale = max(width / source.width, height / source.height)
    resized = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    covered = resized.crop((left, top, left + width, top + height))
    covered = ImageEnhance.Color(covered).enhance(0.18).filter(ImageFilter.GaussianBlur(4.0))
    veil = Image.new("RGB", covered.size, "#F6F5F8")
    return Image.blend(covered, veil, 0.78)


class PicToneApplication:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.state = DocumentState()
        self.preferences = load_preferences()
        self.settings = ProcessingSettings(
            background=self.preferences.background,
            size_key=self.preferences.size_key,
            dpi=self.preferences.dpi,
            max_bytes=self.preferences.max_bytes_kb * 1024,
        )
        self._render_job = None
        self._quality_job = None
        self._preferences_job = None
        self._last_quality_signature = None
        self._scales = []
        self._worker_results = queue.SimpleQueue()
        self._batch_results = queue.SimpleQueue()
        self._closing = False
        saved_export_dir = Path(self.preferences.last_export_dir) if self.preferences.last_export_dir else None
        self._last_export_dir = saved_export_dir if saved_export_dir and saved_export_dir.is_dir() else None
        self._last_export_path = None
        self._batch_cancel = threading.Event()
        self._batch_active = False
        self._drop_proc = None
        self._previous_wndproc = None
        self._drop_hwnd = None
        self._background_job = None
        self._background_source = None
        self._background_photo = None

        self.background = tk.StringVar(value=self.settings.background)
        self.size_label = tk.StringVar(value=PHOTO_SIZES[self.settings.size_key].label)
        self.tolerance = tk.IntVar(value=self.settings.tolerance)
        self.edge_cleanup = tk.IntVar(value=self.settings.edge_cleanup)
        self.feather = tk.DoubleVar(value=self.settings.feather)
        self.brightness = tk.IntVar(value=self.settings.brightness)
        self.zoom = tk.IntVar(value=self.settings.zoom)
        self.offset_x = tk.IntVar(value=self.settings.offset_x)
        self.offset_y = tk.IntVar(value=self.settings.offset_y)
        self.show_original = tk.BooleanVar(value=False)
        self.show_guides = tk.BooleanVar(value=False)
        self.preview_mode = tk.StringVar(value="result")
        self.edit_mode = tk.StringVar(value="keep")
        self.brush_size = tk.IntVar(value=24)
        self.rotation = tk.DoubleVar(value=self.settings.rotation)
        self.dpi = tk.IntVar(value=self.settings.dpi)
        self.max_bytes = tk.IntVar(value=self.settings.max_bytes // 1024)
        self.status_text = tk.StringVar(value="就绪")
        self.progress_text = tk.StringVar(value="未打开图片")
        self.source_meta = tk.StringVar(value="尚未导入")
        self.output_summary = tk.StringVar(value="")
        self.quality_score = tk.StringVar(value="--")
        self.quality_status = tk.StringVar(value="导入照片后自动检查")
        self._button_icons = {}

        self._configure_window()
        self._configure_styles()
        self._create_button_icons()
        self._build_background()
        self._build_menu()
        self._build_toolbar()
        self._build_workspace()
        self._build_statusbar()
        self._bind_shortcuts()
        self._update_actions()
        self.root.after(50, self._poll_worker_results)
        self.root.after(200, self._enable_file_drop)

    def _configure_window(self) -> None:
        self.root.title(APP_NAME)
        icon_path = self._resource_path(APP_ICON_NAME, "assets")
        if icon_path.is_file():
            try:
                self.root.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass
        self.root.geometry("1440x900")
        self.root.minsize(1100, 700)
        self.root.configure(background="#F4F4F7")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        app_bg = "#F4F4F7"
        surface = COLORS["surface"]
        panel_soft = "#FAFAFC"
        chrome = COLORS["chrome"]
        chrome_soft = COLORS["chrome_soft"]
        line = COLORS["line"]
        primary = COLORS["primary"]
        primary_soft = COLORS["primary_soft"]

        style.configure(".", font=("Microsoft YaHei UI", 9), background=app_bg, foreground=COLORS["text"])
        style.configure("App.TFrame", background=app_bg)
        style.configure("ToolbarNav.TFrame", background=chrome)
        style.configure("Toolbar.TFrame", background=chrome)
        style.configure("AccentLine.TFrame", background="#E8E8ED")
        style.configure("ToolbarDivider.TFrame", background="#E6E6EB")
        style.configure("Step.TLabel", background=chrome, foreground="#9A9BA5", padding=(9, 6), font=("Microsoft YaHei UI", 9))
        style.configure("StepActive.TLabel", background=primary_soft, foreground=primary, padding=(11, 6), font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("StepArrow.TLabel", background=chrome, foreground="#C5C6CD", font=("Segoe UI", 9))
        style.configure("ReferenceShell.TFrame", background=panel_soft, borderwidth=1, relief="solid", bordercolor="#E2E2E7")
        style.configure("Reference.TFrame", background=panel_soft)
        style.configure("SidebarTitle.TLabel", background=panel_soft, foreground=COLORS["text"], font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("SidebarMeta.TLabel", background=panel_soft, foreground=COLORS["muted"], font=("Microsoft YaHei UI", 8))
        style.configure("Editor.TFrame", background=COLORS["canvas"], borderwidth=1, relief="solid", bordercolor="#E0E1E7")
        style.configure("EditorBar.TFrame", background=surface)
        style.configure("EditorTitle.TLabel", background=surface, foreground=COLORS["text"], font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("EditorMeta.TLabel", background=surface, foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("Viewport.TFrame", background=surface)
        style.configure("ViewportHeader.TFrame", background=surface)
        style.configure("ViewportTitle.TLabel", background=surface, foreground=COLORS["text"], font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("ViewportInfo.TLabel", background=surface, foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("Badge.TLabel", background="#F1F1F4", foreground="#71727C", padding=(7, 2), font=("Microsoft YaHei UI", 8))
        style.configure("AccentBadge.TLabel", background=primary_soft, foreground=primary, padding=(7, 2), font=("Microsoft YaHei UI", 8, "bold"))
        style.configure("Inspector.TFrame", background=surface)
        style.configure("InspectorShell.TFrame", background=surface, borderwidth=1, relief="solid", bordercolor="#E2E2E7")
        style.configure("SectionTitle.TLabel", background=surface, foreground=COLORS["text"], font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Field.TLabel", background=surface, foreground="#4A4B55", font=("Microsoft YaHei UI", 9))
        style.configure("Value.TLabel", background=surface, foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("ValuePill.TLabel", background="#F2F2F5", foreground="#555660", padding=(7, 3), font=("Segoe UI", 8, "bold"))
        style.configure("Status.TFrame", background=surface)
        style.configure("Status.TLabel", background=surface, foreground="#73747E", font=("Microsoft YaHei UI", 9))
        style.configure("CanvasTools.TFrame", background=surface)
        style.configure("Zoom.TLabel", background=surface, foreground="#555660", width=6, anchor="center", font=("Segoe UI", 9, "bold"))
        style.configure("InspectorHeader.TFrame", background=panel_soft)
        style.configure("InspectorTitle.TLabel", background=panel_soft, foreground=COLORS["text"], font=("Microsoft YaHei UI", 13, "bold"))
        style.configure("InspectorHint.TLabel", background=panel_soft, foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("Summary.TFrame", background=primary_soft)
        style.configure("SummaryLabel.TLabel", background=primary_soft, foreground=primary, font=("Segoe UI", 8, "bold"))
        style.configure("SummaryValue.TLabel", background=primary_soft, foreground="#4B3540", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("QualityHero.TFrame", background=primary_soft)
        style.configure("QualityScore.TLabel", background=primary_soft, foreground="#42363B", font=("Segoe UI", 25, "bold"))
        style.configure("QualityUnit.TLabel", background=primary_soft, foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("QualityStatus.TLabel", background=primary_soft, foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("QualityRow.TFrame", background=surface)
        style.configure("QualityName.TLabel", background=surface, foreground=COLORS["text"], font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("QualityValue.TLabel", background=surface, foreground=COLORS["muted"], font=("Microsoft YaHei UI", 8))

        style.configure("Mode.TButton", padding=(14, 7), relief="flat", borderwidth=1, background="#F4F4F7", foreground="#74757F", bordercolor="#F4F4F7", focuscolor=primary)
        style.map("Mode.TButton", background=[("active", "#EEEEF2"), ("pressed", "#E7E7EC")], foreground=[("disabled", "#B2B3BA")])
        style.configure("ModeActive.TButton", padding=(14, 7), relief="flat", borderwidth=1, background=primary_soft, foreground=primary, bordercolor="#FFD0DA", focuscolor=primary, font=("Microsoft YaHei UI", 9, "bold"))
        style.map("ModeActive.TButton", background=[("active", "#FFE5EA"), ("pressed", "#FFDCE4")], bordercolor=[("focus", primary), ("active", "#FFB7C5")])
        for button_style, padding in (("Utility.TButton", (11, 8)), ("Secondary.TButton", (12, 8)), ("Export.TButton", (13, 9)), ("TButton", (12, 8)), ("Compact.TButton", (8, 6))):
            style.configure(button_style, padding=padding, relief="flat", borderwidth=1, background=surface, foreground="#4B4C55", bordercolor="#DCDDE3", focuscolor=primary)
            style.map(button_style, background=[("active", primary_soft), ("pressed", "#FFE2E8"), ("disabled", "#F6F6F8")], bordercolor=[("active", "#FFC1CE"), ("focus", primary), ("disabled", "#EAEAEE")], foreground=[("disabled", "#B3B4BA")])
        style.configure("Export.TButton", anchor="w")
        style.configure("Inspector.TNotebook", background=surface, borderwidth=0, tabmargins=(12, 6, 12, 0))
        style.configure("Inspector.TNotebook.Tab", padding=(17, 10), background="#F5F5F7", foreground="#777881", borderwidth=0, font=("Microsoft YaHei UI", 9))
        style.map("Inspector.TNotebook.Tab", background=[("selected", surface), ("active", primary_soft)], foreground=[("selected", primary), ("active", primary)])
        style.configure("Toolbar.TButton", padding=(13, 8), relief="flat", borderwidth=1, background=chrome, foreground="#555660", bordercolor="#E1E1E6", focuscolor=primary)
        style.map("Toolbar.TButton", background=[("active", primary_soft), ("pressed", "#FFE0E7"), ("disabled", "#F8F8FA")], bordercolor=[("active", "#FFC1CE"), ("focus", primary), ("disabled", "#ECECF0")], foreground=[("disabled", "#B3B4BA")])
        style.configure("ToolbarMenu.TButton", padding=(11, 8), relief="flat", borderwidth=0, background=chrome, foreground="#54555F", focuscolor=primary, font=("Microsoft YaHei UI", 9))
        style.map("ToolbarMenu.TButton", background=[("active", primary_soft), ("pressed", "#FFE2E8")], foreground=[("active", primary), ("pressed", primary)])
        style.configure("Primary.TButton", padding=(17, 9), relief="flat", borderwidth=1, background=primary, foreground="#FFFFFF", bordercolor=primary, focuscolor="#FFFFFF", font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Primary.TButton", background=[("active", COLORS["primary_hover"]), ("pressed", "#D93C5D"), ("disabled", "#F2B6C2")], bordercolor=[("active", COLORS["primary_hover"]), ("focus", "#FFB2C1"), ("disabled", "#F2B6C2")], foreground=[("disabled", "#FFF7F8")])
        style.configure("TCombobox", padding=(9, 7), fieldbackground=surface, background=surface, bordercolor="#DADBE1", lightcolor="#DADBE1", darkcolor="#DADBE1", arrowcolor="#676872")
        style.configure("TSpinbox", padding=(8, 6), fieldbackground=surface, bordercolor="#DADBE1", lightcolor="#DADBE1", darkcolor="#DADBE1", arrowcolor="#676872")
        style.configure("Accent.Horizontal.TScale", background=surface, troughcolor="#ECECF1", sliderthickness=16)
        style.configure("TRadiobutton", background=surface, foreground="#4F5059", indicatorcolor=surface)
        style.map("TRadiobutton", background=[("active", surface)], indicatorcolor=[("selected", primary)])
        style.configure("TCheckbutton", background=surface, foreground="#555660", indicatorcolor=surface)
        style.map("TCheckbutton", background=[("active", surface)], indicatorcolor=[("selected", primary)])
        style.configure("TSeparator", background=line)
        style.configure("Work.Horizontal.TProgressbar", troughcolor="#ECECF1", background=primary, borderwidth=0, lightcolor=primary, darkcolor=primary)

    def _create_button_icons(self) -> None:
        paths = {
            "open": (((2, 5), (6, 5), (7, 7), (14, 7), (12, 13), (2, 13), (2, 5)), ((2, 5), (2, 3), (7, 3), (9, 5))),
            "save": (((8, 2), (8, 10)), ((5, 7), (8, 10), (11, 7)), ((3, 13), (13, 13))),
            "check": (((8, 2), (13, 4), (13, 8), (11, 12), (8, 14), (5, 12), (3, 8), (3, 4), (8, 2)), ((5, 8), (7, 10), (11, 6))),
            "swap": (((3, 5), (12, 5)), ((9, 2), (12, 5), (9, 8)), ((13, 11), (4, 11)), ((7, 8), (4, 11), (7, 14))),
            "magic": (((4, 13), (11, 6)), ((9, 4), (11, 6)), ((12, 2), (12, 5)), ((10, 3), (14, 3)), ((4, 3), (4, 6)), ((2, 5), (6, 5))),
            "reset": (((12, 5), (12, 2), (9, 2)), ((12, 3), (10, 2), (7, 2), (4, 4), (3, 7), (4, 11), (7, 13), (11, 12), (13, 9))),
            "undo": (((6, 4), (2, 8), (6, 12)), ((3, 8), (9, 8), (12, 10), (13, 13))),
            "redo": (((10, 4), (14, 8), (10, 12)), ((13, 8), (7, 8), (4, 10), (3, 13))),
            "palette": (((8, 2), (4, 3), (2, 6), (2, 10), (5, 13), (8, 14), (10, 13), (10, 11), (13, 11), (14, 8), (13, 5), (11, 3), (8, 2)), ((5, 6), (5, 6)), ((9, 5), (9, 5)), ((5, 10), (5, 10))),
            "cutout": (((8, 2), (11, 4), (12, 7), (11, 10), (13, 14)), ((8, 2), (5, 4), (4, 7), (5, 10), (3, 14)), ((5, 11), (11, 11))),
            "layers": (((8, 2), (14, 6), (8, 10), (2, 6), (8, 2)), ((3, 10), (8, 13), (13, 10))),
            "print": (((4, 5), (4, 2), (12, 2), (12, 5)), ((3, 6), (13, 6), (14, 8), (14, 11), (12, 11)), ((4, 9), (12, 9), (12, 14), (4, 14), (4, 9))),
            "folder": (((2, 5), (6, 5), (7, 7), (14, 7), (13, 13), (2, 13), (2, 5)), ((9, 10), (12, 10)), ((10, 9), (10, 12))),
            "cancel": (((4, 4), (12, 12)), ((12, 4), (4, 12))),
        }
        for tone, color in (("dark", "#555660"), ("light", "#666771"), ("white", "#FFFFFF")):
            for name, strokes in paths.items():
                image = tk.PhotoImage(master=self.root, width=16, height=16)
                for stroke in strokes:
                    for start, end in zip(stroke, stroke[1:]):
                        self._draw_icon_line(image, start, end, color)
                    if len(stroke) == 2 and stroke[0] == stroke[1]:
                        x, y = stroke[0]
                        image.put(color, to=(x, y, x + 2, y + 2))
                self._button_icons[f"{name}:{tone}"] = image

    @staticmethod
    def _draw_icon_line(image: tk.PhotoImage, start, end, color: str) -> None:
        x1, y1 = start
        x2, y2 = end
        dx = abs(x2 - x1)
        dy = -abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        error = dx + dy
        while True:
            image.put(color, to=(x1, y1, min(16, x1 + 2), min(16, y1 + 2)))
            if x1 == x2 and y1 == y2:
                break
            doubled = 2 * error
            if doubled >= dy:
                error += dy
                x1 += sx
            if doubled <= dx:
                error += dx
                y1 += sy

    def _make_button(self, parent, text, command, style="Secondary.TButton", icon=None, tone="dark", **kwargs):
        options = {
            "text": text,
            "command": command,
            "style": style,
            "cursor": "hand2",
            "takefocus": True,
        }
        if icon:
            options.update(image=self._button_icons[f"{icon}:{tone}"], compound="left")
        options.update(kwargs)
        return ttk.Button(parent, **options)

    @staticmethod
    def _resource_path(name: str, directory: str = "") -> Path:
        """Resolve bundled resources in both source and PyInstaller modes."""
        if getattr(sys, "frozen", False):
            root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        else:
            root = Path(__file__).resolve().parent.parent
        bundled = root / directory / name
        if bundled.exists() or getattr(sys, "frozen", False):
            return bundled
        return root / "pictone" / directory / name

    def _build_background(self) -> None:
        background_path = self._resource_path(APP_BACKGROUND_NAME, "assets")
        if background_path.is_file():
            try:
                with Image.open(background_path) as image:
                    self._background_source = image.convert("RGB")
            except OSError:
                self._background_source = None
        self._background_label = tk.Label(self.root, background="#F4F4F7", borderwidth=0, highlightthickness=0)
        self._background_label.place(x=0, y=0, relwidth=1, relheight=1)
        self._background_label.lower()
        self.root.bind("<Configure>", self._schedule_background_render, add="+")
        self.root.after_idle(self._render_background)

    def _schedule_background_render(self, event=None) -> None:
        if event is not None and event.widget is not self.root:
            return
        if self._background_source is None or self._closing:
            return
        if self._background_job:
            self.root.after_cancel(self._background_job)
        self._background_job = self.root.after(80, self._render_background)

    def _render_background(self) -> None:
        self._background_job = None
        if self._background_source is None or self._closing:
            return
        width = max(1, self.root.winfo_width())
        height = max(1, self.root.winfo_height())
        rendered = prepare_app_background(self._background_source, width, height)
        self._background_photo = ImageTk.PhotoImage(rendered, master=self.root)
        self._background_label.configure(image=self._background_photo)

    def _build_menu(self) -> None:
        menu_options = {
            "tearoff": False,
            "background": "#FFFFFF",
            "foreground": "#454650",
            "activebackground": COLORS["primary_soft"],
            "activeforeground": COLORS["primary"],
            "disabledforeground": "#AAAAAF",
            "borderwidth": 1,
            "relief": "flat",
            "font": ("Microsoft YaHei UI", 9),
        }
        self.file_menu = tk.Menu(self.root, **menu_options)
        self.file_menu.add_command(label="打开图片...", accelerator="Ctrl+O", command=self.open_photo)
        self.recent_menu = tk.Menu(self.file_menu, **menu_options)
        self.file_menu.add_cascade(label="最近打开", menu=self.recent_menu)
        self._refresh_recent_menu()
        self.file_menu.add_separator()
        self.file_menu.add_command(label="保存成片...", accelerator="Ctrl+S", command=self.save_photo)
        self.file_menu.add_command(label="导出透明人物 PNG...", accelerator="Ctrl+Alt+S", command=self.export_cutout)
        self.file_menu.add_command(label="导出红白蓝三色...", accelerator="Ctrl+Shift+S", command=self.export_three_colors)
        self.file_menu.add_command(label="导出打印排版...", command=self.export_print_sheet)
        self.file_menu.add_command(label="批量处理文件夹...", command=self.batch_process)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="退出", command=self.close)

        self.edit_menu = tk.Menu(self.root, **menu_options)
        self.edit_menu.add_command(label="重置构图", command=self.reset_layout)
        self.edit_menu.add_command(label="重置全部参数", command=self.reset_settings)
        self.edit_menu.add_command(label="撤销蒙版修改", accelerator="Ctrl+Z", command=self.undo_matte)
        self.edit_menu.add_command(label="重做蒙版修改", accelerator="Ctrl+Y", command=self.redo_matte)

        self.view_menu = tk.Menu(self.root, **menu_options)
        self.view_menu.add_checkbutton(label="显示原图", variable=self.show_original, command=self.show_original_view, accelerator="Space")
        self.view_menu.add_command(label="检查人物抠图", command=self.show_cutout)
        self.view_menu.add_command(label="显示背景成片", command=self.show_result)

        self.help_menu = tk.Menu(self.root, **menu_options)
        self.help_menu.add_command(label="关于证件照换底色", command=self.show_about)

    @staticmethod
    def _popup_menu(menu: tk.Menu, button: ttk.Button) -> None:
        try:
            menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height() + 2)
        finally:
            menu.grab_release()

    def _refresh_recent_menu(self) -> None:
        if not hasattr(self, "recent_menu"):
            return
        self.recent_menu.delete(0, "end")
        available = [Path(item) for item in self.preferences.recent_files if Path(item).is_file()]
        if not available:
            self.recent_menu.add_command(label="暂无记录", state="disabled")
            return
        for path in available:
            self.recent_menu.add_command(
                label=path.name,
                command=lambda selected=path: self._open_recent_file(selected),
            )
        self.recent_menu.add_separator()
        self.recent_menu.add_command(label="清除记录", command=self._clear_recent_files)

    def _open_recent_file(self, path: Path) -> None:
        if self._confirm_replace_photo():
            self.load_photo(path, auto_generate=True)

    def _clear_recent_files(self) -> None:
        self.preferences.recent_files.clear()
        self._refresh_recent_menu()
        self._save_preferences_now()

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self.root, style="Toolbar.TFrame", padding=(16, 9))
        toolbar.grid(row=0, column=0, columnspan=3, sticky="ew")
        menu_strip = ttk.Frame(toolbar, style="ToolbarNav.TFrame")
        menu_strip.pack(side="left")
        for label, menu in (
            ("文件", self.file_menu),
            ("编辑", self.edit_menu),
            ("视图", self.view_menu),
            ("帮助", self.help_menu),
        ):
            button = self._make_button(menu_strip, label, None, style="ToolbarMenu.TButton")
            button.configure(command=lambda popup=menu, anchor=button: self._popup_menu(popup, anchor))
            button.pack(side="left", padx=(0, 2))

        ttk.Frame(toolbar, style="ToolbarDivider.TFrame", width=1, height=22).pack(side="left", fill="y", padx=(10, 14), pady=6)

        self.workflow_steps = ttk.Frame(toolbar, style="ToolbarNav.TFrame")
        self.workflow_steps.pack(side="left")
        self.import_step = ttk.Label(self.workflow_steps, text="01  导入", style="StepActive.TLabel")
        self.import_step.pack(side="left")
        ttk.Label(self.workflow_steps, text="›", style="StepArrow.TLabel").pack(side="left", padx=10)
        self.edit_step = ttk.Label(self.workflow_steps, text="02  编辑", style="Step.TLabel")
        self.edit_step.pack(side="left")
        ttk.Label(self.workflow_steps, text="›", style="StepArrow.TLabel").pack(side="left", padx=10)
        self.export_step = ttk.Label(self.workflow_steps, text="03  导出", style="Step.TLabel")
        self.export_step.pack(side="left")

        self.generate_button = self._make_button(toolbar, "一键生成", self.generate_photo, style="Primary.TButton", icon="magic", tone="white")
        self.generate_button.pack(side="right")
        self.save_button = self._make_button(toolbar, "保存成片", self.save_photo, style="Toolbar.TButton", icon="save", tone="light")
        self.save_button.pack(side="right", padx=(0, 8))
        self.quality_button = self._make_button(toolbar, "合规检查", self.show_quality, style="Toolbar.TButton", icon="check", tone="light")
        self.quality_button.pack(side="right", padx=(0, 8))
        self.open_button = self._make_button(toolbar, "打开照片", self.open_photo, style="Toolbar.TButton", icon="open", tone="light")
        self.open_button.pack(side="right", padx=(0, 8))
        self.compare_button = self._make_button(toolbar, "前后对比", self.toggle_original, style="Toolbar.TButton", icon="swap", tone="light")
        self.toolbar_auto_button = self._make_button(toolbar, "自动构图", self.auto_layout, style="Toolbar.TButton", icon="magic", tone="light")
        self.cutout_button = self._make_button(toolbar, "精修抠图", self.show_cutout, style="Toolbar.TButton", icon="cutout", tone="light")
        ttk.Frame(self.root, style="AccentLine.TFrame", height=1).grid(row=1, column=0, columnspan=3, sticky="ew")
        self.root.bind("<Configure>", self._handle_window_resize, add="+")

    def _build_workspace(self) -> None:
        self.root.grid_columnconfigure(0, minsize=236)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_columnconfigure(2, minsize=348)
        self.root.grid_rowconfigure(2, weight=1)

        reference = ttk.Frame(self.root, style="ReferenceShell.TFrame", width=236)
        reference.grid(row=2, column=0, sticky="nsew", padx=(12, 8), pady=10)
        reference.grid_propagate(False)
        ref_header = ttk.Frame(reference, style="Reference.TFrame", padding=(16, 15, 16, 10))
        ref_header.pack(fill="x")
        ttk.Label(ref_header, text="原片参考", style="SidebarTitle.TLabel").pack(anchor="w")
        ttk.Label(ref_header, textvariable=self.source_meta, style="SidebarMeta.TLabel", wraplength=210).pack(anchor="w", pady=(2, 0))
        self.source_view = PhotoViewport(reference, "原始照片", "点击或拖入一张照片", show_header=False)
        self.source_view.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._make_button(reference, "更换照片", self.open_photo, style="Utility.TButton", icon="open").pack(fill="x", padx=10, pady=(0, 10))

        editor = ttk.Frame(self.root, style="Editor.TFrame")
        editor.grid(row=2, column=1, sticky="nsew", padx=(0, 8), pady=10)
        editor_bar = ttk.Frame(editor, style="EditorBar.TFrame", padding=(18, 12))
        editor_bar.pack(fill="x")
        title_box = ttk.Frame(editor_bar, style="EditorBar.TFrame")
        title_box.pack(side="left")
        ttk.Label(title_box, text="成片画布", style="EditorTitle.TLabel").pack(anchor="w")
        ttk.Label(title_box, textvariable=self.progress_text, style="EditorMeta.TLabel").pack(anchor="w", pady=(2, 0))
        self.preview_modes = ttk.Frame(editor_bar, style="EditorBar.TFrame")
        self.preview_modes.pack(side="right")
        self.result_mode_button = self._make_button(self.preview_modes, "成片", self.show_result, style="ModeActive.TButton")
        self.result_mode_button.pack(side="left")
        self.cutout_mode_button = self._make_button(self.preview_modes, "抠图", self.show_cutout, style="Mode.TButton")
        self.cutout_mode_button.pack(side="left", padx=(4, 0))
        self.original_mode_button = self._make_button(self.preview_modes, "原图", self.toggle_original, style="Mode.TButton")
        self.original_mode_button.pack(side="left", padx=(4, 0))
        self.progress_bar = ttk.Progressbar(editor_bar, mode="indeterminate", length=90, style="Work.Horizontal.TProgressbar")
        self.batch_cancel_button = self._make_button(
            editor_bar,
            "取消批处理",
            self.cancel_batch,
            style="Compact.TButton",
            icon="cancel",
        )
        self.result_view = PhotoViewport(editor, "证件照成片", "导入照片后自动生成成片", accent=True, show_header=False, zoom_changed=self._zoom_changed)
        self.result_view.pack(fill="both", expand=True)
        canvas_tools = ttk.Frame(editor, style="CanvasTools.TFrame", padding=(14, 8))
        canvas_tools.pack(fill="x")
        self._make_button(canvas_tools, "-", lambda: self.result_view.change_view_zoom(-0.25), style="Compact.TButton", width=3).pack(side="right")
        self.zoom_text = tk.StringVar(value="100%")
        ttk.Label(canvas_tools, textvariable=self.zoom_text, style="Zoom.TLabel").pack(side="right", padx=4)
        self._make_button(canvas_tools, "+", lambda: self.result_view.change_view_zoom(0.25), style="Compact.TButton", width=3).pack(side="right")
        fit_button = self._make_button(canvas_tools, "适合窗口", self.result_view.fit_to_window, style="Compact.TButton", icon="reset")
        fit_button.pack(side="right", padx=(0, 8))
        self._tooltip(fit_button, "将成片完整显示在画布中")
        ttk.Checkbutton(
            canvas_tools,
            text="构图辅助线",
            variable=self.show_guides,
            command=self._refresh_guides,
        ).pack(side="left", padx=(2, 0))

        inspector_shell = ttk.Frame(self.root, style="InspectorShell.TFrame", width=348)
        inspector_shell.grid(row=2, column=2, sticky="nsew", padx=(0, 12), pady=10)
        inspector_shell.grid_propagate(False)
        self._build_inspector(inspector_shell)

    def _build_inspector(self, parent) -> None:
        intro = ttk.Frame(parent, style="InspectorHeader.TFrame", padding=(20, 16, 20, 13))
        intro.pack(fill="x")
        ttk.Label(intro, text="照片设置", style="InspectorTitle.TLabel").pack(anchor="w")

        notebook = ttk.Notebook(parent, style="Inspector.TNotebook")
        notebook.pack(fill="both", expand=True)
        self.inspector_notebook = notebook
        basic_tab = ttk.Frame(notebook, style="Inspector.TFrame")
        cutout_tab = ttk.Frame(notebook, style="Inspector.TFrame")
        export_tab = ttk.Frame(notebook, style="Inspector.TFrame")
        quality_tab = ttk.Frame(notebook, style="Inspector.TFrame")
        notebook.add(basic_tab, text="基础")
        notebook.add(cutout_tab, text="抠图")
        notebook.add(export_tab, text="输出")
        notebook.add(quality_tab, text="检查")
        self.inspector_notebook = notebook
        self.quality_tab = quality_tab

        output = InspectorSection(basic_tab, "成片规格")
        output.pack(fill="x")
        labels = [item.label for item in PHOTO_SIZES.values()]
        self.size_combo = ttk.Combobox(output.body, values=labels, textvariable=self.size_label, state="readonly")
        self.size_combo.pack(fill="x")
        self.size_combo.bind("<<ComboboxSelected>>", lambda _e: self._settings_changed())
        ttk.Separator(basic_tab).pack(fill="x")

        background = InspectorSection(basic_tab, "背景颜色")
        background.pack(fill="x")
        swatches = ttk.Frame(background.body, style="Inspector.TFrame")
        swatches.pack(fill="x")
        self._background_buttons = {}
        for label, color in BACKGROUND_PRESETS:
            button = tk.Button(
                swatches,
                background=color,
                activebackground=color,
                width=3,
                height=1,
                relief="flat",
                bd=2,
                highlightthickness=1,
                highlightbackground="#DDDDE3",
                highlightcolor=COLORS["primary"],
                cursor="hand2",
                command=lambda value=color: self.set_background(value),
            )
            button.pack(side="left", padx=(0, 9), ipady=4)
            self._background_buttons[color] = button
            self._tooltip(button, label)
        self.custom_color_button = self._make_button(background.body, "自定义颜色", self.choose_background, icon="palette")
        self.custom_color_button.pack(fill="x", pady=(12, 0))
        ttk.Separator(basic_tab).pack(fill="x")

        framing = InspectorSection(basic_tab, "人物构图")
        framing.pack(fill="x")
        self._add_scale(framing.body, "缩放", self.zoom, 80, 160, "%", matte=False)
        self._add_scale(framing.body, "水平位置", self.offset_x, -20, 20, matte=False)
        self._add_scale(framing.body, "垂直位置", self.offset_y, -20, 20, matte=False)
        self._add_scale(framing.body, "旋转校正", self.rotation, -12, 12, "°", matte=False)
        actions = ttk.Frame(framing.body, style="Inspector.TFrame")
        actions.pack(fill="x")
        self.auto_button = self._make_button(actions, "自动构图", self.auto_layout, icon="magic")
        self.auto_button.pack(side="left", fill="x", expand=True)
        self.reset_button = self._make_button(actions, "重置构图", self.reset_layout, icon="reset")
        self.reset_button.pack(side="left", fill="x", expand=True, padx=(8, 0))

        detail = InspectorSection(cutout_tab, "边缘细节")
        detail.pack(fill="x")
        self._add_scale(detail.body, "背景容差", self.tolerance, 20, 90, matte=True)
        self._add_scale(detail.body, "边缘净化", self.edge_cleanup, 0, 3, matte=True)
        self._add_scale(detail.body, "边缘羽化", self.feather, 0, 3, matte=True)
        self._add_scale(detail.body, "亮度", self.brightness, -30, 30, matte=False)
        ttk.Separator(cutout_tab).pack(fill="x")

        repair = InspectorSection(cutout_tab, "局部修复")
        repair.pack(fill="x")
        modes = ttk.Frame(repair.body, style="Inspector.TFrame")
        modes.pack(fill="x", pady=(0, 10))
        ttk.Radiobutton(modes, text="保留", variable=self.edit_mode, value="keep").pack(side="left")
        ttk.Radiobutton(modes, text="删除", variable=self.edit_mode, value="erase").pack(side="left", padx=(12, 0))
        ttk.Radiobutton(modes, text="柔化", variable=self.edit_mode, value="soften").pack(side="left", padx=(12, 0))
        self._add_scale(repair.body, "画笔大小", self.brush_size, 4, 80, " px", matte=False)
        history = ttk.Frame(repair.body, style="Inspector.TFrame")
        history.pack(fill="x")
        self.undo_button = self._make_button(history, "撤销", self.undo_matte, icon="undo")
        self.undo_button.pack(side="left", fill="x", expand=True)
        self.redo_button = self._make_button(history, "重做", self.redo_matte, icon="redo")
        self.redo_button.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.reset_matte_button = self._make_button(repair.body, "恢复 AI 蒙版", self.reset_matte_edits, icon="reset")
        self.reset_matte_button.pack(fill="x", pady=(8, 0))

        export = InspectorSection(export_tab, "输出设置")
        export.pack(fill="x")
        summary = ttk.Frame(export.body, style="Summary.TFrame", padding=(14, 12))
        summary.pack(fill="x", pady=(0, 14))
        ttk.Label(summary, text="当前方案", style="SummaryLabel.TLabel").pack(anchor="w")
        ttk.Label(summary, textvariable=self.output_summary, style="SummaryValue.TLabel", wraplength=270).pack(anchor="w", pady=(3, 0))
        ttk.Label(export.body, text="DPI", style="Field.TLabel").pack(anchor="w")
        dpi_box = ttk.Spinbox(export.body, from_=72, to=600, textvariable=self.dpi, width=8, command=self._settings_changed)
        dpi_box.pack(fill="x", pady=(5, 12))
        dpi_box.bind("<FocusOut>", lambda _e: self._settings_changed())
        ttk.Label(export.body, text="JPEG 最大体积（KB，0 为不限制）", style="Field.TLabel", wraplength=240).pack(anchor="w")
        byte_box = ttk.Spinbox(export.body, from_=0, to=2048, textvariable=self.max_bytes, width=8, command=self._settings_changed)
        byte_box.pack(fill="x", pady=(5, 0))
        byte_box.bind("<FocusOut>", lambda _e: self._settings_changed())
        ttk.Separator(export_tab).pack(fill="x")

        export_actions = InspectorSection(export_tab, "导出方式")
        export_actions.pack(fill="x")
        self.panel_save_button = self._make_button(export_actions.body, "保存当前成片", self.save_photo, style="Primary.TButton", icon="save", tone="white")
        self.panel_save_button.pack(fill="x")
        self.transparent_button = self._make_button(export_actions.body, "导出透明人物 PNG", self.export_cutout, style="Export.TButton", icon="cutout")
        self.transparent_button.pack(fill="x", pady=(8, 0))
        self.batch_button = self._make_button(export_actions.body, "导出红白蓝三色", self.export_three_colors, style="Export.TButton", icon="layers")
        self.batch_button.pack(fill="x", pady=(8, 0))
        self.print_button = self._make_button(export_actions.body, "导出打印排版", self.export_print_sheet, style="Export.TButton", icon="print")
        self.print_button.pack(fill="x", pady=(8, 0))
        self.folder_button = self._make_button(export_actions.body, "批量处理文件夹", self.batch_process, style="Export.TButton", icon="folder")
        self.folder_button.pack(fill="x", pady=(8, 0))

        quality_canvas = tk.Canvas(
            quality_tab,
            background="#FFFFFF",
            highlightthickness=0,
            bd=0,
        )
        quality_scrollbar = ttk.Scrollbar(quality_tab, orient="vertical", command=quality_canvas.yview)
        quality_canvas.configure(yscrollcommand=quality_scrollbar.set)
        quality_scrollbar.pack(side="right", fill="y")
        quality_canvas.pack(side="left", fill="both", expand=True)
        quality_content = ttk.Frame(quality_canvas, style="Inspector.TFrame")
        quality_window = quality_canvas.create_window((0, 0), window=quality_content, anchor="nw")
        quality_content.bind(
            "<Configure>",
            lambda _event: quality_canvas.configure(scrollregion=quality_canvas.bbox("all")),
        )
        quality_canvas.bind(
            "<Configure>",
            lambda event: quality_canvas.itemconfigure(quality_window, width=event.width),
        )

        def scroll_quality(event):
            quality_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        quality_canvas.bind("<Enter>", lambda _event: quality_canvas.bind_all("<MouseWheel>", scroll_quality))
        quality_canvas.bind("<Leave>", lambda _event: quality_canvas.unbind_all("<MouseWheel>"))

        quality = InspectorSection(quality_content, "成片质量")
        quality.pack(fill="x")
        hero = ttk.Frame(quality.body, style="QualityHero.TFrame", padding=(14, 12))
        hero.pack(fill="x")
        score_line = ttk.Frame(hero, style="QualityHero.TFrame")
        score_line.pack(fill="x")
        ttk.Label(score_line, textvariable=self.quality_score, style="QualityScore.TLabel").pack(side="left")
        ttk.Label(score_line, text="/ 100", style="QualityUnit.TLabel").pack(side="left", padx=(5, 0), pady=(12, 0))
        ttk.Label(hero, textvariable=self.quality_status, style="QualityStatus.TLabel", wraplength=275).pack(anchor="w", pady=(2, 0))
        self.quality_items = ttk.Frame(quality.body, style="Inspector.TFrame")
        self.quality_items.pack(fill="x", pady=(12, 0))
        self._render_quality_items(None)
        self.quality_detail_button = self._make_button(
            quality.body,
            "查看完整检查结果",
            self.show_quality,
            style="Secondary.TButton",
            icon="check",
        )
        self.quality_detail_button.pack(fill="x", pady=(12, 0))

        guide_info = InspectorSection(quality_content, "构图参考")
        guide_info.pack(fill="x")
        ttk.Label(
            guide_info.body,
            text="辅助线只用于预览，不会写入导出照片。中心线用于判断左右平衡；眼线区、头顶安全区与肩部线用于快速复核人物比例。",
            style="Value.TLabel",
            wraplength=285,
            justify="left",
        ).pack(anchor="w")

        self._refresh_background_selection()
        self._refresh_output_summary()

    def _handle_window_resize(self, event) -> None:
        if event.widget is not self.root or not hasattr(self, "workflow_steps"):
            return
        if event.width < 1240 and self.workflow_steps.winfo_manager():
            self.workflow_steps.pack_forget()
        elif event.width >= 1240 and not self.workflow_steps.winfo_manager():
            self.workflow_steps.pack(side="left")

    def _set_workflow_stage(self, stage: str) -> None:
        if not hasattr(self, "import_step"):
            return
        steps = {
            "import": self.import_step,
            "edit": self.edit_step,
            "export": self.export_step,
        }
        for name, label in steps.items():
            label.configure(style="StepActive.TLabel" if name == stage else "Step.TLabel")

    def _refresh_output_summary(self) -> None:
        size = next((item for item in PHOTO_SIZES.values() if item.label == self.size_label.get()), PHOTO_SIZES["one"])
        limit = f"≤ {self.max_bytes.get()} KB" if self.max_bytes.get() else "不限体积"
        self.output_summary.set(
            f"{size.label.split('  ')[0]} · {size.width} × {size.height} px\n"
            f"{size.width_mm} × {size.height_mm} mm · {self.dpi.get()} DPI\n"
            f"{self.background.get().upper()} · JPEG {limit}"
        )

    def _schedule_preferences_save(self) -> None:
        if self._preferences_job:
            self.root.after_cancel(self._preferences_job)
        self._preferences_job = self.root.after(350, self._save_preferences_now)

    def _save_preferences_now(self) -> None:
        self._preferences_job = None
        self._sync_settings()
        self.preferences.background = self.settings.background
        self.preferences.size_key = self.settings.size_key
        self.preferences.dpi = self.settings.dpi
        self.preferences.max_bytes_kb = self.settings.max_bytes // 1024
        self.preferences.last_export_dir = str(self._last_export_dir) if self._last_export_dir else ""
        try:
            save_preferences(self.preferences)
        except OSError:
            pass

    def _refresh_guides(self) -> None:
        visible = self.show_guides.get() and self.preview_mode.get() != "cutout"
        self.result_view.set_guides_visible(visible)

    def _quality_signature(self):
        return (
            id(self.state.source),
            id(self.state.matte),
            self.settings.size_key,
            self.settings.background.upper(),
            self.settings.brightness,
            self.settings.zoom,
            self.settings.offset_x,
            self.settings.offset_y,
            round(self.settings.rotation, 2),
        )

    def _schedule_quality_refresh(self) -> None:
        if self._quality_job:
            self.root.after_cancel(self._quality_job)
            self._quality_job = None
        if self.state.source is None or self.state.matte is None or self.state.processing:
            return
        if self.state.face_report is not None and self._last_quality_signature == self._quality_signature():
            return
        self.quality_status.set("正在复核成片...")
        self._quality_job = self.root.after(220, self._refresh_quality_panel)

    def _refresh_quality_panel(self) -> None:
        self._quality_job = None
        if self.state.source is None or self.state.matte is None or self.state.processing:
            return
        try:
            target = PHOTO_SIZES[self.settings.size_key]
            result = self._final_result()
            report = inspect_photo(result, self.state.matte, (target.width, target.height))
        except Exception as exc:
            self.quality_score.set("--")
            self.quality_status.set(f"检查失败：{exc}")
            self._render_quality_items(None)
            return
        self.state.face_report = report
        self._last_quality_signature = self._quality_signature()
        self.quality_score.set(str(report.score))
        failed = sum(not item.passed for item in report.items)
        self.quality_status.set("全部关键项目通过" if not failed else f"发现 {failed} 项需要调整")
        self._render_quality_items(report)

    def _render_quality_items(self, report) -> None:
        if not hasattr(self, "quality_items"):
            return
        for child in self.quality_items.winfo_children():
            child.destroy()
        if report is None:
            ttk.Label(
                self.quality_items,
                text="完成抠图后，这里会显示人脸比例、居中、眼线、留白、清晰度和曝光检查。",
                style="Value.TLabel",
                wraplength=285,
                justify="left",
            ).pack(anchor="w")
            return
        for item in report.items:
            row = ttk.Frame(self.quality_items, style="QualityRow.TFrame", padding=(0, 5))
            row.pack(fill="x")
            indicator = tk.Canvas(row, width=14, height=14, background="#FFFFFF", highlightthickness=0)
            color = COLORS["success"] if item.passed else "#E05A68"
            indicator.create_oval(3, 3, 11, 11, fill=color, outline="")
            indicator.pack(side="left", padx=(0, 7))
            copy = ttk.Frame(row, style="QualityRow.TFrame")
            copy.pack(side="left", fill="x", expand=True)
            ttk.Label(copy, text=item.name, style="QualityName.TLabel").pack(anchor="w")
            ttk.Label(copy, text=item.value, style="QualityValue.TLabel").pack(anchor="w")
            ttk.Label(
                row,
                text="通过" if item.passed else "调整",
                foreground=color,
                background="#FFFFFF",
                font=("Microsoft YaHei UI", 8, "bold"),
            ).pack(side="right")

    def _add_scale(self, parent, label, variable, start, end, suffix="", matte=False) -> None:
        scale = ValueScale(parent, label, variable, start, end, lambda: self._settings_changed(matte=matte), suffix)
        scale.pack(fill="x", pady=(0, 12))
        self._scales.append(scale)

    def _build_statusbar(self) -> None:
        ttk.Separator(self.root, orient="horizontal").grid(row=3, column=0, columnspan=3, sticky="ew")
        status = ttk.Frame(self.root, style="Status.TFrame", padding=(18, 9))
        status.grid(row=4, column=0, columnspan=3, sticky="ew")
        ttk.Label(status, textvariable=self.status_text, style="Status.TLabel").pack(side="left")
        self.open_location_button = self._make_button(status, "打开位置", self.open_export_location, style="Compact.TButton", icon="folder")
        self.open_location_button.pack(side="right")
        ttk.Label(status, text="滚轮缩放   中键/右键拖动   双击适合窗口", style="Status.TLabel").pack(side="right", padx=(0, 14))

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-o>", lambda _e: self.open_photo())
        self.root.bind_all("<Control-s>", lambda _e: self.save_photo())
        self.root.bind_all("<Control-Alt-s>", lambda _e: self.export_cutout())
        self.root.bind_all("<Control-Shift-S>", lambda _e: self.export_three_colors())
        self.root.bind_all("<space>", lambda _e: self.toggle_original())
        self.root.bind_all("<Control-z>", lambda _e: self.undo_matte())
        self.root.bind_all("<Control-y>", lambda _e: self.redo_matte())
        self.result_view.canvas.bind("<Button-1>", self._paint_start)
        self.result_view.canvas.bind("<B1-Motion>", self._paint_move)
        self.result_view.canvas.bind("<ButtonRelease-1>", self._paint_end)
        self.result_view.canvas.bind("<MouseWheel>", self._zoom_preview)
        self.result_view.canvas.bind("<Double-Button-1>", lambda _e: self.result_view.fit_to_window())
        self.result_view.canvas.bind("<Button-2>", self.result_view.begin_pan)
        self.result_view.canvas.bind("<B2-Motion>", self.result_view.pan_to)
        self.result_view.canvas.bind("<ButtonRelease-2>", self.result_view.end_pan)
        self.result_view.canvas.bind("<Button-3>", self.result_view.begin_pan)
        self.result_view.canvas.bind("<B3-Motion>", self.result_view.pan_to)
        self.result_view.canvas.bind("<ButtonRelease-3>", self.result_view.end_pan)
        self.source_view.canvas.bind("<Button-1>", lambda _e: self.open_photo())

    def _zoom_changed(self, value: float) -> None:
        if hasattr(self, "zoom_text"):
            self.zoom_text.set(f"{round(value * 100)}%")

    def _set_processing_ui(self, active: bool, text: str = "") -> None:
        if not hasattr(self, "progress_bar"):
            return
        if active:
            if not self.progress_bar.winfo_manager():
                self.progress_bar.pack(side="right", padx=(0, 12), before=self.preview_modes)
            self.progress_bar.start(12)
            self.result_view.set_busy(text)
            self.generate_button.configure(text="正在生成...")
            self.quality_status.set("等待成片生成后自动复核")
        else:
            self.progress_bar.stop()
            self.progress_bar.pack_forget()
            self.batch_cancel_button.pack_forget()
            self.result_view.set_busy("")
            self.generate_button.configure(text="一键生成")

    def _set_batch_progress(self, completed: int, total: int) -> None:
        self.progress_text.set(f"批量处理 {completed}/{total}")
        self.progress_bar.configure(mode="determinate", maximum=max(1, total), value=completed)

    def cancel_batch(self) -> None:
        if not self._batch_active:
            return
        self._batch_cancel.set()
        self.batch_cancel_button.configure(state="disabled", text="正在停止...")
        self.progress_text.set("正在完成当前图片并停止批处理...")

    def _enable_file_drop(self) -> None:
        if sys.platform != "win32" or self._closing:
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            shell32.DragAcceptFiles.argtypes = (wintypes.HWND, wintypes.BOOL)
            shell32.DragQueryFileW.argtypes = (
                wintypes.HANDLE,
                wintypes.UINT,
                wintypes.LPWSTR,
                wintypes.UINT,
            )
            shell32.DragQueryFileW.restype = wintypes.UINT
            shell32.DragFinish.argtypes = (wintypes.HANDLE,)
            hwnd = user32.GetAncestor(self.root.winfo_id(), 2) or self.root.winfo_id()
            callback_type = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            set_wndproc = user32.SetWindowLongPtrW
            set_wndproc.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_void_p)
            set_wndproc.restype = ctypes.c_void_p
            call_wndproc = user32.CallWindowProcW
            call_wndproc.argtypes = (
                ctypes.c_void_p,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            call_wndproc.restype = ctypes.c_ssize_t
            previous = None

            def window_proc(window, message, wparam, lparam):
                if message == 0x0233:
                    count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                    dropped = []
                    for index in range(count):
                        length = shell32.DragQueryFileW(wparam, index, None, 0)
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        shell32.DragQueryFileW(wparam, index, buffer, length + 1)
                        dropped.append(Path(buffer.value))
                    shell32.DragFinish(wparam)
                    self.root.after(0, lambda paths=dropped: self._open_dropped_files(paths))
                    return 0
                return call_wndproc(previous, window, message, wparam, lparam)

            self._drop_proc = callback_type(window_proc)
            previous = set_wndproc(hwnd, -4, ctypes.cast(self._drop_proc, ctypes.c_void_p))
            if not previous:
                raise ctypes.WinError()
            shell32.DragAcceptFiles(hwnd, True)
            self._previous_wndproc = previous
            self._drop_hwnd = hwnd
        except Exception:
            self._drop_proc = None
            self._previous_wndproc = None
            self._drop_hwnd = None

    def _disable_file_drop(self) -> None:
        if sys.platform != "win32" or not self._drop_hwnd or not self._previous_wndproc:
            return
        try:
            import ctypes
            from ctypes import wintypes

            shell32 = ctypes.windll.shell32
            user32 = ctypes.windll.user32
            shell32.DragAcceptFiles.argtypes = (wintypes.HWND, wintypes.BOOL)
            set_wndproc = user32.SetWindowLongPtrW
            set_wndproc.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_void_p)
            set_wndproc.restype = ctypes.c_void_p
            shell32.DragAcceptFiles(self._drop_hwnd, False)
            set_wndproc(self._drop_hwnd, -4, self._previous_wndproc)
        except Exception:
            pass
        self._drop_proc = None
        self._previous_wndproc = None
        self._drop_hwnd = None

    def _open_dropped_files(self, paths) -> None:
        supported = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        path = next((item for item in paths if item.is_file() and item.suffix.lower() in supported), None)
        if path is None:
            messagebox.showwarning(APP_NAME, "请拖入 JPG、PNG、WEBP 或 BMP 图片。")
            return
        if self._confirm_replace_photo():
            self.load_photo(path, auto_generate=True)

    def _tooltip(self, widget, text: str) -> None:
        tip = None

        def show(_event):
            nonlocal tip
            tip = tk.Toplevel(widget)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            tip.geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 4}")
            tk.Label(tip, text=text, background="#20242A", foreground="#FFFFFF", padx=7, pady=3).pack()

        def hide(_event):
            nonlocal tip
            if tip:
                tip.destroy()
                tip = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    def open_photo(self) -> None:
        if self.state.processing:
            messagebox.showinfo(APP_NAME, "当前照片仍在处理中，请完成后再打开另一张照片。")
            return
        path = filedialog.askopenfilename(title="打开人像照片", filetypes=IMAGE_TYPES)
        if path and self._confirm_replace_photo():
            self.load_photo(Path(path), auto_generate=True)

    def _confirm_replace_photo(self) -> bool:
        if self.state.processing:
            messagebox.showinfo(APP_NAME, "当前照片仍在处理中，请完成后再打开另一张照片。")
            return False
        if self.state.source is None or not self.state.dirty:
            return True
        return messagebox.askyesno(APP_NAME, "当前成片尚未保存，仍要打开另一张照片吗？")

    def load_photo(self, path: Path, auto_generate: bool = True) -> None:
        try:
            with Image.open(path) as image:
                source = image.convert("RGB").copy()
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"无法打开图片：\n{exc}")
            return
        self.state.source = source
        self.state.path = Path(path)
        add_recent_file(self.preferences, self.state.path)
        self._refresh_recent_menu()
        self._schedule_preferences_save()
        self.state.matte = None
        self.state.matte_history.clear()
        self.state.matte_future.clear()
        self.state.result = None
        self.state.face_report = None
        self._last_quality_signature = None
        self.state.dirty = False
        self.show_original.set(False)
        self.preview_mode.set("result")
        self.source_view.set_image(source)
        self.source_view.fit_to_window()
        self.result_view.fit_to_window()
        self.source_meta.set(f"{path.name}\n{source.width} × {source.height} px")
        self.quality_score.set("--")
        self.quality_status.set("正在生成并检查成片...")
        self._render_quality_items(None)
        self._set_workflow_stage("edit")
        self.status_text.set(f"已打开：{path.name}")
        self._rebuild_matte(auto_layout=auto_generate)
        self._update_actions()

    def _sync_settings(self) -> None:
        size = next((item for item in PHOTO_SIZES.values() if item.label == self.size_label.get()), PHOTO_SIZES["one"])
        self.settings.size_key = size.key
        self.settings.background = self.background.get()
        self.settings.tolerance = round(self.tolerance.get())
        self.settings.edge_cleanup = round(self.edge_cleanup.get())
        self.settings.feather = float(self.feather.get())
        self.settings.brightness = round(self.brightness.get())
        self.settings.zoom = round(self.zoom.get())
        self.settings.offset_x = round(self.offset_x.get())
        self.settings.offset_y = round(self.offset_y.get())
        self.settings.rotation = float(self.rotation.get())
        self.settings.dpi = max(72, min(600, round(self.dpi.get())))
        self.settings.max_bytes = max(0, round(self.max_bytes.get())) * 1024

    def _settings_changed(self, matte=False) -> None:
        self._sync_settings()
        self._schedule_preferences_save()
        self._set_workflow_stage("edit")
        self._refresh_output_summary()
        for scale in self._scales:
            scale.refresh()
        if self.state.source is None:
            return
        self.state.dirty = True
        self.state.face_report = None
        self._last_quality_signature = None
        if self._render_job:
            self.root.after_cancel(self._render_job)
        self._render_job = self.root.after(100, self._rebuild_matte if matte else self._render_now)

    def generate_photo(self) -> None:
        if self.state.source is None or self.state.processing:
            return
        self.show_original.set(False)
        self.preview_mode.set("result")
        self._rebuild_matte(auto_layout=True)

    def _rebuild_matte(self, auto_layout: bool = False) -> None:
        if self.state.source is None:
            return
        self._sync_settings()
        self.state.revision += 1
        revision = self.state.revision
        source = self.state.source.copy()
        settings = ProcessingSettings(**vars(self.settings))
        target = PHOTO_SIZES[settings.size_key]
        self.state.processing = True
        self.progress_text.set("正在智能抠图与构图..." if auto_layout else "正在生成人物抠图...")
        self._set_processing_ui(True, "正在智能生成证件照" if auto_layout else "正在更新人物抠图")
        self._update_actions()

        def worker():
            try:
                matte = build_matte(source, settings)
                suggestion = None
                brightness_adjustment = None
                if auto_layout:
                    rgb = np.asarray(source, dtype=np.uint8)
                    suggestion = suggest_layout(rgb, target.width / target.height, matte)
                    brightness = float(rgb.mean())
                    if brightness < 75:
                        brightness_adjustment = min(18, round((90 - brightness) * 0.35))
                    elif brightness > 205:
                        brightness_adjustment = max(-12, round((190 - brightness) * 0.3))
                self._worker_results.put((revision, matte, suggestion, brightness_adjustment, None))
            except Exception as exc:
                self._worker_results.put((revision, None, None, None, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_worker_results(self) -> None:
        while True:
            try:
                revision, matte, suggestion, brightness_adjustment, error = self._worker_results.get_nowait()
            except queue.Empty:
                break
            self._matte_ready(revision, matte, suggestion, brightness_adjustment, error)
        while True:
            try:
                event, payload = self._batch_results.get_nowait()
            except queue.Empty:
                break
            if event == "progress":
                self._set_batch_progress(*payload)
            elif event == "finished":
                self._batch_finished(*payload)
        if not self._closing:
            self.root.after(50, self._poll_worker_results)

    def _matte_ready(self, revision: int, matte, suggestion, brightness_adjustment, error) -> None:
        if revision != self.state.revision:
            return
        self.state.processing = False
        self._set_processing_ui(False)
        if error:
            self.progress_text.set("处理失败")
            self._update_actions()
            messagebox.showerror(APP_NAME, f"处理图片时发生错误：\n{error}")
            return
        self.state.matte = matte
        self.state.matte_history.clear()
        self.state.matte_future.clear()
        if suggestion:
            self.zoom.set(suggestion["zoom"])
            self.offset_x.set(suggestion["offset_x"])
            self.offset_y.set(suggestion["offset_y"])
            self.rotation.set(suggestion["rotation"])
        if brightness_adjustment is not None:
            self.brightness.set(brightness_adjustment)
        self._sync_settings()
        self.state.dirty = True
        self.progress_text.set("智能生成完成" if suggestion else "人物抠图完成")
        self._render_now()
        self.result_view.fit_to_window()
        self.status_text.set("已完成智能抠图与自动构图" if suggestion else "抠图完成，可继续微调构图")
        self._update_actions()

    def _render_now(self) -> None:
        self._render_job = None
        if self.state.source is None:
            return
        self._sync_settings()
        try:
            if self.preview_mode.get() == "cutout" and self.state.matte is not None:
                result = render_matte_preview(render_cutout(self.state.source, self.settings, self.state.matte))
            else:
                result = render_photo(
                    self.state.source,
                    self.settings,
                    matte=self.state.matte,
                    original=self.show_original.get(),
                )
        except Exception as exc:
            self.status_text.set(f"预览失败：{exc}")
            return
        self.state.result = result
        if self.preview_mode.get() == "cutout":
            title = "人物抠图检查（棋盘格为透明区域）"
        else:
            title = "原图构图预览" if self.show_original.get() else "证件照成片"
        self.result_view.set_title(title)
        self.result_view.set_image(result)
        self._refresh_preview_modes()
        self._refresh_guides()
        if not self.show_original.get():
            self.status_text.set(f"成片尺寸：{result.width} x {result.height} px")
        if (
            self.state.matte is not None
            and self.preview_mode.get() == "result"
            and not self.show_original.get()
        ):
            self._schedule_quality_refresh()

    def set_background(self, color: str) -> None:
        self.background.set(color)
        self.show_original.set(False)
        self.preview_mode.set("result")
        self._refresh_background_selection()
        self._refresh_output_summary()
        self._settings_changed()

    def choose_background(self) -> None:
        color = colorchooser.askcolor(self.background.get(), title="选择证件照背景色")[1]
        if color:
            self.set_background(color.upper())

    def toggle_original(self) -> None:
        if self.state.source is None:
            return
        self.show_original.set(not self.show_original.get())
        self.preview_mode.set("result")
        self._render_now()

    def show_original_view(self) -> None:
        if self.state.source is None:
            return
        self.show_original.set(True)
        self.preview_mode.set("result")
        self._render_now()

    def show_cutout(self) -> None:
        if self.state.matte is None:
            return
        self.show_original.set(False)
        self.preview_mode.set("cutout")
        self._render_now()

    def show_result(self) -> None:
        if self.state.source is None:
            return
        self.show_original.set(False)
        self.preview_mode.set("result")
        self._render_now()

    def _refresh_preview_modes(self) -> None:
        if not hasattr(self, "result_mode_button"):
            return
        selected = "original" if self.show_original.get() else self.preview_mode.get()
        buttons = {
            "result": self.result_mode_button,
            "cutout": self.cutout_mode_button,
            "original": self.original_mode_button,
        }
        for mode, button in buttons.items():
            button.configure(style="ModeActive.TButton" if mode == selected else "Mode.TButton")

    def _refresh_background_selection(self) -> None:
        selected = self.background.get().upper()
        for color, button in getattr(self, "_background_buttons", {}).items():
            active = color.upper() == selected
            button.configure(
                relief="solid" if active else "flat",
                bd=2 if active else 0,
                highlightthickness=2 if active else 1,
                highlightbackground=COLORS["primary"] if active else "#DDDDE3",
            )

    def reset_layout(self) -> None:
        self.zoom.set(100)
        self.offset_x.set(0)
        self.offset_y.set(0)
        self.rotation.set(0)
        self._settings_changed()

    def auto_layout(self) -> None:
        if self.state.source is None:
            return
        self._sync_settings()
        target = PHOTO_SIZES[self.settings.size_key]
        suggestion = suggest_layout(
            np.asarray(self.state.source, dtype=np.uint8),
            target.width / target.height,
            self.state.matte,
        )
        if not suggestion:
            messagebox.showwarning(APP_NAME, "未检测到清晰的人脸，暂时无法自动构图。")
            return
        self.zoom.set(suggestion["zoom"])
        self.offset_x.set(suggestion["offset_x"])
        self.offset_y.set(suggestion["offset_y"])
        self.rotation.set(suggestion["rotation"])
        self._settings_changed()
        self.status_text.set(f"已自动构图：眼线校正 {suggestion['rotation']:+.1f}°")

    def show_quality(self) -> None:
        if self.state.source is None:
            return
        self._sync_settings()
        target = PHOTO_SIZES[self.settings.size_key]
        report = inspect_photo(self._final_result(), self.state.matte, (target.width, target.height))
        self.state.face_report = report
        self._last_quality_signature = self._quality_signature()
        self.quality_score.set(str(report.score))
        failed = sum(not item.passed for item in report.items)
        self.quality_status.set("全部关键项目通过" if not failed else f"发现 {failed} 项需要调整")
        self._render_quality_items(report)
        if hasattr(self, "inspector_notebook") and hasattr(self, "quality_tab"):
            self.inspector_notebook.select(self.quality_tab)
        lines = [f"总体评分：{report.score}/100", report.summary(), ""]
        lines.extend(f"{'通过' if item.passed else '注意'}  {item.name}：{item.value}  {item.detail}" for item in report.items)
        messagebox.showinfo("证件照合规检查", "\n".join(lines))

    def _paint_point(self, event):
        if self.state.matte is None or self.preview_mode.get() != "cutout":
            return None
        transform = self.result_view.image_transform()
        if transform is None:
            return None
        left, top, scale = transform
        target = PHOTO_SIZES[self.settings.size_key]
        display_x = (event.x - left) / scale
        display_y = (event.y - top) / scale
        source_box = composition_crop_box(
            self.state.matte.size,
            (target.width, target.height),
            self.settings.zoom,
            self.settings.offset_x,
            self.settings.offset_y,
        )
        x = int(source_box[0] + display_x / max(1, target.width) * (source_box[2] - source_box[0]))
        y = int(source_box[1] + display_y / max(1, target.height) * (source_box[3] - source_box[1]))
        image = self._editable_matte.copy()
        if not (0 <= x < image.width and 0 <= y < image.height):
            return None
        radius = max(2, int(self.brush_size.get() / 2))
        mask = image.getchannel("A")
        from PIL import ImageDraw
        draw = ImageDraw.Draw(mask)
        mode = self.edit_mode.get()
        if mode == "soften":
            blurred = mask.filter(ImageFilter.GaussianBlur(max(1, radius // 2)))
            region = Image.new("L", mask.size, 0)
            ImageDraw.Draw(region).ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
            mask = Image.composite(blurred, mask, region)
        else:
            fill = 255 if mode == "keep" else 0
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
        image.putalpha(mask)
        self._editable_matte = image
        self.state.matte = image
        self._render_now()

    def _paint_start(self, event):
        if self.state.matte is None or self.preview_mode.get() != "cutout":
            return
        self._editable_matte = self.state.matte.copy()
        self.state.matte_history.append(self.state.matte.copy())
        self.state.matte_future.clear()
        self._paint_point(event)

    def _paint_move(self, event):
        self._paint_point(event)

    def _paint_end(self, _event):
        if self.state.matte is not None:
            self.state.dirty = True
            self.status_text.set("已修改抠图蒙版")
            self._update_actions()

    def _zoom_preview(self, event):
        if self.state.result is None:
            return
        self.result_view.change_view_zoom(0.25 if event.delta > 0 else -0.25)

    def reset_matte_edits(self) -> None:
        if self.state.source is None:
            return
        self._rebuild_matte()

    def undo_matte(self) -> None:
        if not self.state.matte_history or self.state.matte is None:
            return
        self.state.matte_future.append(self.state.matte.copy())
        self.state.matte = self.state.matte_history.pop()
        self._render_now()
        self._update_actions()

    def redo_matte(self) -> None:
        if not self.state.matte_future or self.state.matte is None:
            return
        self.state.matte_history.append(self.state.matte.copy())
        self.state.matte = self.state.matte_future.pop()
        self._render_now()
        self._update_actions()

    def reset_settings(self) -> None:
        defaults = ProcessingSettings()
        self.background.set(defaults.background)
        self.size_label.set(PHOTO_SIZES[defaults.size_key].label)
        self.tolerance.set(defaults.tolerance)
        self.edge_cleanup.set(defaults.edge_cleanup)
        self.feather.set(defaults.feather)
        self.brightness.set(defaults.brightness)
        self.zoom.set(defaults.zoom)
        self.offset_x.set(defaults.offset_x)
        self.offset_y.set(defaults.offset_y)
        self.rotation.set(defaults.rotation)
        self.dpi.set(defaults.dpi)
        self.max_bytes.set(defaults.max_bytes // 1024)
        self.show_original.set(False)
        self.show_guides.set(False)
        self.preview_mode.set("result")
        self._refresh_background_selection()
        self._refresh_guides()
        self._settings_changed(matte=True)

    def _final_result(self, color=None):
        self._sync_settings()
        settings = ProcessingSettings(**vars(self.settings))
        if color:
            settings.background = color
        return render_photo(self.state.source, settings, matte=self.state.matte)

    def _export_initial_dir(self):
        if self._last_export_dir and self._last_export_dir.is_dir():
            return str(self._last_export_dir)
        if self.state.path and self.state.path.parent.is_dir():
            return str(self.state.path.parent)
        return None

    def _remember_export(self, path) -> None:
        exported = Path(path)
        self._last_export_path = exported
        self._last_export_dir = exported if exported.is_dir() else exported.parent
        self.open_location_button.configure(state="normal")
        self._schedule_preferences_save()

    @staticmethod
    def _export_error(validation) -> str:
        return "\n".join(validation.issues) if validation.issues else "导出文件未通过复核"

    def open_export_location(self) -> None:
        target = self._last_export_dir
        if target is None or not target.is_dir():
            return
        try:
            os.startfile(str(target))
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"无法打开文件位置：\n{exc}")

    def save_photo(self) -> None:
        if self.state.source is None or self.state.processing:
            return
        self._sync_settings()
        target = PHOTO_SIZES[self.settings.size_key]
        report = inspect_photo(self._final_result(), self.state.matte, (target.width, target.height))
        if not report.passed and not messagebox.askyesno(APP_NAME, f"合规检查提示：{report.summary()}\n仍要继续保存吗？"):
            return
        default = f"{self.state.path.stem if self.state.path else '证件照'}_成片.png"
        path = filedialog.asksaveasfilename(
            title="保存证件照",
            defaultextension=".png",
            initialdir=self._export_initial_dir(),
            initialfile=default,
            filetypes=[("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg *.jpeg")],
        )
        if not path:
            return
        path = Path(path)
        try:
            size = save_image(self._final_result(), path, dpi=self.settings.dpi, max_bytes=self.settings.max_bytes)
            validation = validate_export(
                path,
                expected_size=(target.width, target.height),
                expected_dpi=self.settings.dpi,
                max_bytes=self.settings.max_bytes if path.suffix.lower() in (".jpg", ".jpeg") else 0,
            )
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"保存失败：\n{exc}")
            return
        if not validation.valid:
            messagebox.showerror(APP_NAME, f"文件已经写入，但成品复核未通过：\n{self._export_error(validation)}")
            return
        self.state.dirty = False
        self._remember_export(path)
        self._set_workflow_stage("export")
        self.status_text.set(f"已保存并复核：{path.name}（{max(1, size // 1024)} KB，{self.settings.dpi} DPI）")

    def export_cutout(self) -> None:
        if self.state.source is None or self.state.matte is None or self.state.processing:
            return
        default = f"{self.state.path.stem if self.state.path else '证件照'}_透明人物.png"
        path = filedialog.asksaveasfilename(
            title="导出透明人物 PNG",
            defaultextension=".png",
            initialdir=self._export_initial_dir(),
            initialfile=default,
            filetypes=[("透明 PNG", "*.png")],
        )
        if not path:
            return
        path = Path(path)
        target = PHOTO_SIZES[self.settings.size_key]
        try:
            save_image(render_cutout(self.state.source, self.settings, self.state.matte), path, dpi=self.settings.dpi)
            validation = validate_export(
                path,
                expected_size=(target.width, target.height),
                expected_dpi=self.settings.dpi,
                require_alpha=True,
            )
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"透明人物导出失败：\n{exc}")
            return
        if not validation.valid:
            messagebox.showerror(APP_NAME, f"透明人物成品复核未通过：\n{self._export_error(validation)}")
            return
        self._remember_export(path)
        self._set_workflow_stage("export")
        self.status_text.set(f"已导出并复核透明人物：{path.name}")

    def export_three_colors(self) -> None:
        if self.state.source is None or self.state.processing:
            return
        folder = filedialog.askdirectory(
            title="选择三色证件照保存文件夹",
            initialdir=self._export_initial_dir(),
        )
        if not folder:
            return
        stem = self.state.path.stem if self.state.path else "证件照"
        names = (("蓝底", "#438EDB"), ("红底", "#E94B4B"), ("白底", "#FFFFFF"))
        target = PHOTO_SIZES[self.settings.size_key]
        exported = []
        try:
            for label, color in names:
                path = collision_safe_path(Path(folder) / f"{stem}_{label}.png")
                save_image(self._final_result(color), path, dpi=self.settings.dpi)
                validation = validate_export(path, (target.width, target.height), self.settings.dpi)
                if not validation.valid:
                    raise ValueError(self._export_error(validation))
                exported.append(path)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"批量导出失败：\n{exc}")
            return
        self.status_text.set(f"已安全导出并复核 {len(exported)} 张三色证件照")
        self._remember_export(folder)
        self._set_workflow_stage("export")

    def export_print_sheet(self) -> None:
        if self.state.source is None or self.state.processing:
            return
        path = filedialog.asksaveasfilename(
            title="导出打印排版",
            defaultextension=".jpg",
            initialdir=self._export_initial_dir(),
            initialfile=f"{self.state.path.stem if self.state.path else '证件照'}_打印排版.jpg",
            filetypes=[("JPEG 图片", "*.jpg *.jpeg"), ("PNG 图片", "*.png")],
        )
        if not path:
            return
        image = make_print_sheet([self._final_result()], dpi=self.settings.dpi)
        path = Path(path)
        try:
            save_image(image, path, dpi=self.settings.dpi)
            validation = validate_export(path, image.size, self.settings.dpi)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"打印排版导出失败：\n{exc}")
            return
        if not validation.valid:
            messagebox.showerror(APP_NAME, f"打印排版成品复核未通过：\n{self._export_error(validation)}")
            return
        self._remember_export(path)
        self._set_workflow_stage("export")
        self.status_text.set(f"已导出并复核打印排版：{path.name}")

    def batch_process(self) -> None:
        if self.state.processing:
            return
        folder = filedialog.askdirectory(title="选择待处理照片文件夹")
        if not folder:
            return
        output_folder = filedialog.askdirectory(title="选择批量输出文件夹")
        if not output_folder:
            return
        files = [path for path in sorted(Path(folder).iterdir()) if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}]
        if not files:
            messagebox.showwarning(APP_NAME, "所选文件夹中没有可处理的图片。")
            return
        self._sync_settings()
        settings = ProcessingSettings(**vars(self.settings))
        background = settings.background
        target = PHOTO_SIZES[settings.size_key]
        self.progress_text.set(f"批量处理 0/{len(files)}")
        self.state.processing = True
        self._batch_active = True
        self._batch_cancel.clear()
        self._set_processing_ui(True, "正在批量生成证件照")
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate", maximum=len(files), value=0)
        self.batch_cancel_button.configure(state="normal", text="取消批处理")
        self.batch_cancel_button.pack(side="right", padx=(0, 8), before=self.progress_bar)
        self._update_actions()

        def worker():
            completed = 0
            errors = []
            records = []
            cancelled = False
            for path in files:
                if self._batch_cancel.is_set():
                    cancelled = True
                    break
                try:
                    with Image.open(path) as image:
                        source = image.convert("RGB").copy()
                    matte = build_matte(source, settings)
                    suggestion = suggest_layout(np.asarray(source, dtype=np.uint8), target.width / target.height, matte)
                    if suggestion:
                        batch_settings = ProcessingSettings(**vars(settings))
                        batch_settings.zoom = suggestion["zoom"]
                        batch_settings.offset_x = suggestion["offset_x"]
                        batch_settings.offset_y = suggestion["offset_y"]
                        batch_settings.rotation = suggestion["rotation"]
                    else:
                        batch_settings = settings
                    result = render_photo(source, batch_settings, matte=matte)
                    output_path = collision_safe_path(Path(output_folder) / f"{path.stem}_{background.lstrip('#')}.jpg")
                    save_image(result, output_path, dpi=settings.dpi, max_bytes=settings.max_bytes)
                    validation = validate_export(
                        output_path,
                        (target.width, target.height),
                        settings.dpi,
                        settings.max_bytes,
                    )
                    if not validation.valid:
                        raise ValueError(self._export_error(validation))
                    quality = inspect_photo(result, matte, (target.width, target.height))
                    records.append(
                        BatchExportRecord(
                            path.name,
                            output_path.name,
                            "通过" if quality.passed else "需复核",
                            quality.score,
                            quality.summary(),
                        )
                    )
                    completed += 1
                except Exception as exc:
                    errors.append(f"{path.name}: {exc}")
                    records.append(BatchExportRecord(path.name, "", "失败", None, str(exc)))
                self._batch_results.put(("progress", (completed, len(files))))
            report_path = None
            if records:
                try:
                    report_path = write_batch_report(records, Path(output_folder) / "批量处理报告.csv")
                except OSError as exc:
                    errors.append(f"批量处理报告.csv: {exc}")
            self._batch_results.put(
                (
                    "finished",
                    (
                    completed,
                    len(files),
                    errors,
                    target,
                    Path(output_folder),
                    cancelled,
                    report_path,
                    ),
                )
            )

        threading.Thread(target=worker, daemon=True).start()

    def _batch_finished(self, completed, total, errors, target, output_folder: Path, cancelled=False, report_path=None) -> None:
        self.state.processing = False
        self._batch_active = False
        self._set_processing_ui(False)
        self.progress_bar.configure(mode="indeterminate", value=0)
        self._update_actions()
        self.progress_text.set(f"批量处理已停止 {completed}/{total}" if cancelled else f"批量处理完成 {completed}/{total}")
        if completed:
            self._remember_export(output_folder)
        report_note = f"\n质量报告：{Path(report_path).name}" if report_path else ""
        if errors:
            messagebox.showwarning(APP_NAME, f"完成 {completed}/{total} 张，以下文件失败：\n" + "\n".join(errors[:8]) + report_note)
        elif cancelled:
            messagebox.showinfo(APP_NAME, f"批处理已停止，已完成并复核 {completed}/{total} 张。{report_note}")
        else:
            messagebox.showinfo(APP_NAME, f"批量处理完成，共 {completed} 张。\n输出规格：{target.width} x {target.height}{report_note}")

    @staticmethod
    def _save_image(image: Image.Image, path: Path) -> None:
        save_image(image, path)

    def _update_actions(self) -> None:
        enabled = self.state.source is not None and not self.state.processing
        state = "normal" if enabled else "disabled"
        for button in (
            self.save_button,
            self.panel_save_button,
            self.transparent_button,
            self.cutout_button,
            self.batch_button,
            self.print_button,
            self.compare_button,
            self.reset_button,
            self.auto_button,
            self.toolbar_auto_button,
            self.quality_button,
            self.quality_detail_button,
            self.reset_matte_button,
            self.generate_button,
        ):
            button.configure(state=state)
        self.undo_button.configure(state="normal" if enabled and self.state.matte_history else "disabled")
        self.redo_button.configure(state="normal" if enabled and self.state.matte_future else "disabled")
        self.folder_button.configure(state="disabled" if self.state.processing else "normal")
        self.open_location_button.configure(
            state="normal" if self._last_export_dir and self._last_export_dir.is_dir() else "disabled"
        )

    def show_about(self) -> None:
        messagebox.showinfo(APP_NAME, "证件照换底色\n\n原生 Python 桌面工具\n图片处理全程在本机完成。")

    def close(self) -> None:
        discard_processing = self.state.processing
        if discard_processing and not messagebox.askyesno(APP_NAME, "照片仍在处理中，退出将放弃本次处理，确定退出吗？"):
            return
        if self.state.dirty and not discard_processing:
            choice = messagebox.askyesnocancel(APP_NAME, "当前成片尚未保存，关闭前是否保存？")
            if choice is None:
                return
            if choice:
                self.save_photo()
                if self.state.dirty:
                    return
        self._closing = True
        if self._batch_active:
            self._batch_cancel.set()
        self.state.revision += 1
        if self._render_job:
            self.root.after_cancel(self._render_job)
            self._render_job = None
        if self._quality_job:
            self.root.after_cancel(self._quality_job)
            self._quality_job = None
        if self._preferences_job:
            self.root.after_cancel(self._preferences_job)
            self._preferences_job = None
        if self._background_job:
            self.root.after_cancel(self._background_job)
            self._background_job = None
        self._save_preferences_now()
        self._disable_file_drop()
        self.root.destroy()


def launch() -> None:
    root = tk.Tk()
    app = PicToneApplication(root)
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if path.is_file():
            root.after(120, lambda: app.load_photo(path))
    root.mainloop()
