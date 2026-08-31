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
from PIL import Image, ImageFilter

from .engine import build_matte, render_cutout, render_matte_preview, render_photo
from .face import suggest_layout
from .model import DocumentState, PHOTO_SIZES, ProcessingSettings
from .output import make_print_sheet, save_image
from .quality import inspect_photo
from .widgets import COLORS, InspectorSection, PhotoViewport, ValueScale


APP_NAME = "证件照换底色"
APP_ICON_NAME = "app_icon.ico"
IMAGE_TYPES = [("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp"), ("所有文件", "*.*")]
BACKGROUND_PRESETS = (
    ("蓝色", "#438EDB"),
    ("红色", "#E94B4B"),
    ("白色", "#FFFFFF"),
    ("浅灰", "#E8EBEF"),
    ("深蓝", "#1B365D"),
)


class PicToneApplication:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.state = DocumentState()
        self.settings = ProcessingSettings()
        self._render_job = None
        self._scales = []
        self._worker_results = queue.SimpleQueue()
        self._closing = False

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
        self.preview_mode = tk.StringVar(value="result")
        self.edit_mode = tk.StringVar(value="keep")
        self.brush_size = tk.IntVar(value=24)
        self.rotation = tk.DoubleVar(value=self.settings.rotation)
        self.dpi = tk.IntVar(value=self.settings.dpi)
        self.max_bytes = tk.IntVar(value=self.settings.max_bytes // 1024)
        self.status_text = tk.StringVar(value="就绪")
        self.progress_text = tk.StringVar(value="未打开图片")

        self._configure_window()
        self._configure_styles()
        self._build_menu()
        self._build_toolbar()
        self._build_workspace()
        self._build_statusbar()
        self._bind_shortcuts()
        self._update_actions()
        self.root.after(50, self._poll_worker_results)

    def _configure_window(self) -> None:
        self.root.title(APP_NAME)
        icon_path = self._resource_path(APP_ICON_NAME, "assets")
        if icon_path.is_file():
            try:
                self.root.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass
        self.root.geometry("1280x780")
        self.root.minsize(980, 620)
        self.root.configure(background="#F4F6F8")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("App.TFrame", background="#F4F6F8")
        style.configure("Toolbar.TFrame", background="#FFFFFF")
        style.configure("Viewport.TFrame", background="#FFFFFF")
        style.configure("ViewportHeader.TFrame", background="#FFFFFF")
        style.configure("ViewportTitle.TLabel", background="#FFFFFF", foreground=COLORS["text"], font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("ViewportInfo.TLabel", background="#FFFFFF", foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("Inspector.TFrame", background="#FFFFFF")
        style.configure("InspectorCanvas.TFrame", background="#FFFFFF")
        style.configure("SectionTitle.TLabel", background="#FFFFFF", foreground=COLORS["text"], font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Field.TLabel", background="#FFFFFF", foreground="#424850", font=("Microsoft YaHei UI", 9))
        style.configure("Value.TLabel", background="#FFFFFF", foreground=COLORS["muted"], font=("Microsoft YaHei UI", 9))
        style.configure("Status.TFrame", background="#F0F2F5")
        style.configure("Status.TLabel", background="#F0F2F5", foreground="#505761", font=("Microsoft YaHei UI", 9))
        style.configure("Toolbar.TButton", padding=(12, 6), font=("Microsoft YaHei UI", 9))
        style.configure("Primary.TButton", padding=(14, 7), font=("Microsoft YaHei UI", 9, "bold"))

    @staticmethod
    def _resource_path(name: str, directory: str = "") -> Path:
        """Resolve bundled resources in both source and PyInstaller modes."""
        if getattr(sys, "frozen", False):
            root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        else:
            root = Path(__file__).resolve().parent.parent
        return root / directory / name

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="打开图片...", accelerator="Ctrl+O", command=self.open_photo)
        file_menu.add_separator()
        file_menu.add_command(label="保存成片...", accelerator="Ctrl+S", command=self.save_photo)
        file_menu.add_command(label="导出透明人物 PNG...", accelerator="Ctrl+Alt+S", command=self.export_cutout)
        file_menu.add_command(label="导出红白蓝三色...", accelerator="Ctrl+Shift+S", command=self.export_three_colors)
        file_menu.add_command(label="导出打印排版...", command=self.export_print_sheet)
        file_menu.add_command(label="批量处理文件夹...", command=self.batch_process)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.close)
        menu.add_cascade(label="文件", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="重置构图", command=self.reset_layout)
        edit_menu.add_command(label="重置全部参数", command=self.reset_settings)
        edit_menu.add_command(label="撤销蒙版修改", accelerator="Ctrl+Z", command=self.undo_matte)
        edit_menu.add_command(label="重做蒙版修改", accelerator="Ctrl+Y", command=self.redo_matte)
        menu.add_cascade(label="编辑", menu=edit_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_checkbutton(label="显示原图", variable=self.show_original, command=self.show_original_view, accelerator="Space")
        view_menu.add_command(label="检查人物抠图", command=self.show_cutout)
        view_menu.add_command(label="显示背景成片", command=self.show_result)
        menu.add_cascade(label="视图", menu=view_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="关于证件照换底色", command=self.show_about)
        menu.add_cascade(label="帮助", menu=help_menu)
        self.root.configure(menu=menu)

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self.root, style="Toolbar.TFrame", padding=(10, 8))
        toolbar.pack(fill="x")
        self.open_button = ttk.Button(toolbar, text="打开图片", style="Toolbar.TButton", command=self.open_photo)
        self.open_button.pack(side="left")
        self.save_button = ttk.Button(toolbar, text="保存成片", style="Primary.TButton", command=self.save_photo)
        self.save_button.pack(side="left", padx=(8, 0))
        self.cutout_button = ttk.Button(toolbar, text="检查抠图", style="Toolbar.TButton", command=self.show_cutout)
        self.cutout_button.pack(side="left", padx=(8, 0))
        self.batch_button = ttk.Button(toolbar, text="红白蓝三色", style="Toolbar.TButton", command=self.export_three_colors)
        self.batch_button.pack(side="left", padx=(8, 0))
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=12)
        self.compare_button = ttk.Button(toolbar, text="前后对比", style="Toolbar.TButton", command=self.toggle_original)
        self.compare_button.pack(side="left")
        self.reset_button = ttk.Button(toolbar, text="重置构图", style="Toolbar.TButton", command=self.reset_layout)
        self.reset_button.pack(side="left", padx=(8, 0))
        self.auto_button = ttk.Button(toolbar, text="自动构图", style="Toolbar.TButton", command=self.auto_layout)
        self.auto_button.pack(side="left", padx=(8, 0))
        self.quality_button = ttk.Button(toolbar, text="合规检查", style="Toolbar.TButton", command=self.show_quality)
        self.quality_button.pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, textvariable=self.progress_text, background="#FFFFFF", foreground=COLORS["muted"]).pack(side="right", padx=8)
        ttk.Separator(self.root, orient="horizontal").pack(fill="x")

    def _build_workspace(self) -> None:
        workspace = ttk.Frame(self.root, style="App.TFrame", padding=(10, 10))
        workspace.pack(fill="both", expand=True)
        paned = ttk.Panedwindow(workspace, orient="horizontal")
        paned.pack(fill="both", expand=True)

        preview_pane = ttk.Panedwindow(paned, orient="horizontal")
        self.source_view = PhotoViewport(preview_pane, "原始照片", "打开一张正面人像照片")
        self.result_view = PhotoViewport(preview_pane, "证件照成片", "处理结果将在这里显示")
        preview_pane.add(self.source_view, weight=1)
        preview_pane.add(self.result_view, weight=1)
        paned.add(preview_pane, weight=4)

        inspector_shell = ttk.Frame(paned, style="Inspector.TFrame", width=300)
        inspector_shell.pack_propagate(False)
        paned.add(inspector_shell, weight=0)
        self._build_inspector(inspector_shell)

    def _build_inspector(self, parent) -> None:
        canvas = tk.Canvas(parent, background="#FFFFFF", highlightthickness=0, width=300)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = ttk.Frame(canvas, style="Inspector.TFrame")
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))

        output = InspectorSection(body, "成片规格")
        output.pack(fill="x")
        labels = [item.label for item in PHOTO_SIZES.values()]
        self.size_combo = ttk.Combobox(output.body, values=labels, textvariable=self.size_label, state="readonly")
        self.size_combo.pack(fill="x")
        self.size_combo.bind("<<ComboboxSelected>>", lambda _e: self._settings_changed())
        ttk.Separator(body).pack(fill="x")

        background = InspectorSection(body, "背景颜色")
        background.pack(fill="x")
        swatches = ttk.Frame(background.body, style="Inspector.TFrame")
        swatches.pack(fill="x")
        for label, color in BACKGROUND_PRESETS:
            button = tk.Button(
                swatches,
                background=color,
                activebackground=color,
                width=3,
                height=1,
                relief="solid",
                bd=1,
                cursor="hand2",
                command=lambda value=color: self.set_background(value),
            )
            button.pack(side="left", padx=(0, 8))
            self._tooltip(button, label)
        ttk.Button(background.body, text="自定义颜色...", command=self.choose_background).pack(fill="x", pady=(10, 0))
        ttk.Separator(body).pack(fill="x")

        framing = InspectorSection(body, "构图")
        framing.pack(fill="x")
        self._add_scale(framing.body, "缩放", self.zoom, 80, 160, "%", matte=False)
        self._add_scale(framing.body, "水平位置", self.offset_x, -20, 20, matte=False)
        self._add_scale(framing.body, "垂直位置", self.offset_y, -20, 20, matte=False)
        self._add_scale(framing.body, "旋转校正", self.rotation, -12, 12, "°", matte=False)
        ttk.Separator(body).pack(fill="x")

        detail = InspectorSection(body, "抠图细节")
        detail.pack(fill="x")
        self._add_scale(detail.body, "背景容差", self.tolerance, 20, 90, matte=True)
        self._add_scale(detail.body, "边缘净化", self.edge_cleanup, 0, 3, matte=True)
        self._add_scale(detail.body, "边缘羽化", self.feather, 0, 3, matte=True)
        self._add_scale(detail.body, "亮度", self.brightness, -30, 30, matte=False)
        ttk.Separator(body).pack(fill="x")

        repair = InspectorSection(body, "局部抠图修复")
        repair.pack(fill="x")
        ttk.Label(repair.body, text="在右侧棋盘格预览上涂抹", style="Value.TLabel", wraplength=240).pack(anchor="w")
        modes = ttk.Frame(repair.body, style="Inspector.TFrame")
        modes.pack(fill="x", pady=(8, 8))
        ttk.Radiobutton(modes, text="保留", variable=self.edit_mode, value="keep").pack(side="left")
        ttk.Radiobutton(modes, text="删除", variable=self.edit_mode, value="erase").pack(side="left", padx=(12, 0))
        ttk.Radiobutton(modes, text="柔化", variable=self.edit_mode, value="soften").pack(side="left", padx=(12, 0))
        ttk.Button(repair.body, text="恢复 AI 蒙版", command=self.reset_matte_edits).pack(fill="x")
        self._add_scale(repair.body, "画笔大小", self.brush_size, 4, 80, " px", matte=False)
        ttk.Separator(body).pack(fill="x")

        export = InspectorSection(body, "输出设置")
        export.pack(fill="x")
        ttk.Label(export.body, text="DPI", style="Field.TLabel").pack(anchor="w")
        dpi_box = ttk.Spinbox(export.body, from_=72, to=600, textvariable=self.dpi, width=8, command=self._settings_changed)
        dpi_box.pack(anchor="w", pady=(3, 8))
        dpi_box.bind("<FocusOut>", lambda _e: self._settings_changed())
        ttk.Label(export.body, text="JPEG 最大体积（KB，0 为不限制）", style="Field.TLabel", wraplength=240).pack(anchor="w")
        byte_box = ttk.Spinbox(export.body, from_=0, to=2048, textvariable=self.max_bytes, width=8, command=self._settings_changed)
        byte_box.pack(anchor="w", pady=(3, 0))
        byte_box.bind("<FocusOut>", lambda _e: self._settings_changed())

    def _add_scale(self, parent, label, variable, start, end, suffix="", matte=False) -> None:
        scale = ValueScale(parent, label, variable, start, end, lambda: self._settings_changed(matte=matte), suffix)
        scale.pack(fill="x", pady=(0, 12))
        self._scales.append(scale)

    def _build_statusbar(self) -> None:
        ttk.Separator(self.root, orient="horizontal").pack(fill="x")
        status = ttk.Frame(self.root, style="Status.TFrame", padding=(10, 5))
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.status_text, style="Status.TLabel").pack(side="left")
        ttk.Label(status, text="Ctrl+O 打开   Ctrl+S 保存   空格 前后对比", style="Status.TLabel").pack(side="right")

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
        path = filedialog.askopenfilename(title="打开人像照片", filetypes=IMAGE_TYPES)
        if path:
            self.load_photo(Path(path))

    def load_photo(self, path: Path) -> None:
        try:
            with Image.open(path) as image:
                source = image.convert("RGB").copy()
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"无法打开图片：\n{exc}")
            return
        self.state.source = source
        self.state.path = Path(path)
        self.state.matte = None
        self.state.matte_history.clear()
        self.state.matte_future.clear()
        self.state.result = None
        self.state.dirty = False
        self.show_original.set(False)
        self.preview_mode.set("result")
        self.source_view.set_image(source)
        self.status_text.set(f"已打开：{path.name}")
        self._rebuild_matte()
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
        for scale in self._scales:
            scale.refresh()
        if self.state.source is None:
            return
        self.state.dirty = True
        if self._render_job:
            self.root.after_cancel(self._render_job)
        self._render_job = self.root.after(100, self._rebuild_matte if matte else self._render_now)

    def _rebuild_matte(self) -> None:
        if self.state.source is None:
            return
        self._sync_settings()
        self.state.revision += 1
        revision = self.state.revision
        source = self.state.source.copy()
        settings = ProcessingSettings(**vars(self.settings))
        self.state.processing = True
        self.progress_text.set("正在生成人物抠图...")
        self._update_actions()

        def worker():
            try:
                matte = build_matte(source, settings)
                self._worker_results.put((revision, matte, None))
            except Exception as exc:
                self._worker_results.put((revision, None, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_worker_results(self) -> None:
        while True:
            try:
                revision, matte, error = self._worker_results.get_nowait()
            except queue.Empty:
                break
            self._matte_ready(revision, matte, error)
        if not self._closing:
            self.root.after(50, self._poll_worker_results)

    def _matte_ready(self, revision: int, matte, error) -> None:
        if revision != self.state.revision:
            return
        self.state.processing = False
        if error:
            self.progress_text.set("处理失败")
            self._update_actions()
            messagebox.showerror(APP_NAME, f"处理图片时发生错误：\n{error}")
            return
        self.state.matte = matte
        self.state.matte_history.clear()
        self.state.matte_future.clear()
        self.progress_text.set("人物抠图完成")
        self._render_now()
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
        if not self.show_original.get():
            self.status_text.set(f"成片尺寸：{result.width} x {result.height} px")

    def set_background(self, color: str) -> None:
        self.background.set(color)
        self.show_original.set(False)
        self.preview_mode.set("result")
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
        suggestion = suggest_layout(np.asarray(self.state.source, dtype=np.uint8), target.width / target.height)
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
        target = PHOTO_SIZES[self.settings.size_key]
        report = inspect_photo(self.state.source, self.state.matte, (target.width, target.height))
        self.state.face_report = report
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
        aspect = target.width / target.height
        source_width, source_height = self.state.matte.size
        crop_h = min(source_height, round(source_height / (self.settings.zoom / 100.0)))
        crop_w = min(source_width, round(crop_h * aspect))
        if crop_w > source_width:
            crop_w = source_width
            crop_h = min(source_height, round(crop_w / aspect))
        source_box = self._crop_box_for_matte(crop_w, crop_h)
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

    def _crop_box_for_matte(self, crop_w: int, crop_h: int):
        if self.state.matte is None:
            return (0, 0, 1, 1)
        width, height = self.state.matte.size
        crop_w = min(width, crop_w)
        crop_h = min(height, crop_h)
        center_x = width / 2 + (self.settings.offset_x / 100) * width
        center_y = height / 2 + (self.settings.offset_y / 100) * height
        left = int(round(center_x - crop_w / 2))
        top = int(round(center_y - crop_h / 2))
        left = max(0, min(width - crop_w, left))
        top = max(0, min(height - crop_h, top))
        return left, top, left + crop_w, top + crop_h

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

    def _zoom_preview(self, event):
        if self.preview_mode.get() != "cutout":
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

    def redo_matte(self) -> None:
        if not self.state.matte_future or self.state.matte is None:
            return
        self.state.matte_history.append(self.state.matte.copy())
        self.state.matte = self.state.matte_future.pop()
        self._render_now()

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
        self.show_original.set(False)
        self.preview_mode.set("result")
        self._settings_changed(matte=True)

    def _final_result(self, color=None):
        self._sync_settings()
        settings = ProcessingSettings(**vars(self.settings))
        if color:
            settings.background = color
        return render_photo(self.state.source, settings, matte=self.state.matte)

    def save_photo(self) -> None:
        if self.state.source is None or self.state.processing:
            return
        self._sync_settings()
        report = inspect_photo(self.state.source, self.state.matte, (PHOTO_SIZES[self.settings.size_key].width, PHOTO_SIZES[self.settings.size_key].height))
        if not report.passed and not messagebox.askyesno(APP_NAME, f"合规检查提示：{report.summary()}\n仍要继续保存吗？"):
            return
        default = f"{self.state.path.stem if self.state.path else '证件照'}_成片.png"
        path = filedialog.asksaveasfilename(
            title="保存证件照",
            defaultextension=".png",
            initialfile=default,
            filetypes=[("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg *.jpeg")],
        )
        if not path:
            return
        size = save_image(self._final_result(), Path(path), dpi=self.settings.dpi, max_bytes=self.settings.max_bytes)
        self.state.dirty = False
        self.status_text.set(f"已保存：{Path(path).name}（{size // 1024} KB，{self.settings.dpi} DPI）")

    def export_cutout(self) -> None:
        if self.state.source is None or self.state.matte is None or self.state.processing:
            return
        default = f"{self.state.path.stem if self.state.path else '证件照'}_透明人物.png"
        path = filedialog.asksaveasfilename(
            title="导出透明人物 PNG",
            defaultextension=".png",
            initialfile=default,
            filetypes=[("透明 PNG", "*.png")],
        )
        if not path:
            return
        render_cutout(self.state.source, self.settings, self.state.matte).save(path, dpi=(self.settings.dpi, self.settings.dpi))
        self.status_text.set(f"已导出透明人物：{Path(path).name}")

    def export_three_colors(self) -> None:
        if self.state.source is None or self.state.processing:
            return
        folder = filedialog.askdirectory(title="选择三色证件照保存文件夹")
        if not folder:
            return
        stem = self.state.path.stem if self.state.path else "证件照"
        names = (("蓝底", "#438EDB"), ("红底", "#E94B4B"), ("白底", "#FFFFFF"))
        try:
            for label, color in names:
                save_image(self._final_result(color), Path(folder) / f"{stem}_{label}.png", dpi=self.settings.dpi)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"批量导出失败：\n{exc}")
            return
        self.status_text.set(f"已导出红、白、蓝三色证件照：{folder}")
        messagebox.showinfo(APP_NAME, "红、白、蓝三色证件照已导出完成。")

    def export_print_sheet(self) -> None:
        if self.state.source is None or self.state.processing:
            return
        path = filedialog.asksaveasfilename(
            title="导出打印排版",
            defaultextension=".jpg",
            initialfile=f"{self.state.path.stem if self.state.path else '证件照'}_打印排版.jpg",
            filetypes=[("JPEG 图片", "*.jpg *.jpeg"), ("PNG 图片", "*.png")],
        )
        if not path:
            return
        image = make_print_sheet([self._final_result()], dpi=self.settings.dpi)
        save_image(image, Path(path), dpi=self.settings.dpi)
        self.status_text.set(f"已导出打印排版：{Path(path).name}")

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
        self._update_actions()

        def worker():
            completed = 0
            errors = []
            for path in files:
                try:
                    with Image.open(path) as image:
                        source = image.convert("RGB").copy()
                    matte = build_matte(source, settings)
                    suggestion = suggest_layout(np.asarray(source, dtype=np.uint8), target.width / target.height)
                    if suggestion:
                        batch_settings = ProcessingSettings(**vars(settings))
                        batch_settings.zoom = suggestion["zoom"]
                        batch_settings.offset_x = suggestion["offset_x"]
                        batch_settings.offset_y = suggestion["offset_y"]
                        batch_settings.rotation = suggestion["rotation"]
                    else:
                        batch_settings = settings
                    result = render_photo(source, batch_settings, matte=matte)
                    save_image(result, Path(output_folder) / f"{path.stem}_{background.lstrip('#')}.jpg", dpi=settings.dpi, max_bytes=settings.max_bytes)
                    completed += 1
                except Exception as exc:
                    errors.append(f"{path.name}: {exc}")
                self.root.after(0, lambda done=completed: self.progress_text.set(f"批量处理 {done}/{len(files)}"))
            self.root.after(0, lambda: self._batch_finished(completed, len(files), errors, target))

        threading.Thread(target=worker, daemon=True).start()

    def _batch_finished(self, completed, total, errors, target) -> None:
        self.state.processing = False
        self._update_actions()
        self.progress_text.set(f"批量处理完成 {completed}/{total}")
        if errors:
            messagebox.showwarning(APP_NAME, f"完成 {completed}/{total} 张，以下文件失败：\n" + "\n".join(errors[:8]))
        else:
            messagebox.showinfo(APP_NAME, f"批量处理完成，共 {completed} 张。\n输出规格：{target.width} x {target.height}")

    @staticmethod
    def _save_image(image: Image.Image, path: Path) -> None:
        save_image(image, path)

    def _update_actions(self) -> None:
        enabled = self.state.source is not None and not self.state.processing
        state = "normal" if enabled else "disabled"
        for button in (
            self.save_button,
            self.cutout_button,
            self.batch_button,
            self.compare_button,
            self.reset_button,
            self.auto_button,
            self.quality_button,
        ):
            button.configure(state=state)

    def show_about(self) -> None:
        messagebox.showinfo(APP_NAME, "证件照换底色\n\n原生 Python 桌面工具\n图片处理全程在本机完成。")

    def close(self) -> None:
        self._closing = True
        self.state.revision += 1
        self.root.destroy()


def launch() -> None:
    root = tk.Tk()
    app = PicToneApplication(root)
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if path.is_file():
            root.after(120, lambda: app.load_photo(path))
    root.mainloop()
