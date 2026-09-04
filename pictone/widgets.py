import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk


COLORS = {
    "surface": "#FFFFFF",
    "canvas": "#EEF0F5",
    "canvas_grid": "#E6E8EE",
    "line": "#E5E6EC",
    "muted": "#7B7D88",
    "text": "#292932",
    "primary": "#FF5C7C",
    "primary_hover": "#EB496A",
    "primary_soft": "#FFF0F3",
    "soft": "#F7F7FA",
    "chrome": "#FFFFFF",
    "chrome_soft": "#FAFAFC",
    "success": "#28A879",
}


class PhotoViewport(ttk.Frame):
    def __init__(self, master, title: str, empty_text: str, accent: bool = False, show_header: bool = True, zoom_changed=None):
        super().__init__(master, style="Viewport.TFrame")
        self._image = None
        self._photo = None
        self._view_zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._pan_anchor = None
        self._busy_text = ""
        self._guides_visible = False
        self._zoom_changed = zoom_changed
        self._title = tk.StringVar(value=title)
        self._empty_text = empty_text
        self._accent = accent

        if show_header:
            bar = ttk.Frame(self, style="ViewportHeader.TFrame", padding=(18, 14))
            bar.pack(fill="x")
            marker = tk.Canvas(bar, width=8, height=8, bd=0, highlightthickness=0, background=COLORS["surface"])
            marker.create_oval(1, 1, 7, 7, fill=COLORS["primary"] if accent else "#A8A9B3", outline="")
            marker.pack(side="left", padx=(0, 9))
            ttk.Label(bar, textvariable=self._title, style="ViewportTitle.TLabel").pack(side="left")
            ttk.Label(bar, text="成片预览" if accent else "原始素材", style="AccentBadge.TLabel" if accent else "Badge.TLabel").pack(side="left", padx=(10, 0))
            self.info = ttk.Label(bar, text="", style="ViewportInfo.TLabel")
            self.info.pack(side="right")
        else:
            self.info = None

        self.canvas = tk.Canvas(
            self,
            background=COLORS["canvas"],
            highlightbackground=COLORS["line"],
            highlightcolor=COLORS["line"],
            highlightthickness=1,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._redraw)
        self._redraw()

    def image_transform(self):
        if self._image is None:
            return None
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        margin = 38
        scale = min((width - margin * 2) / self._image.width, (height - margin * 2) / self._image.height)
        scale *= self._view_zoom
        display_size = (max(1, round(self._image.width * scale)), max(1, round(self._image.height * scale)))
        return (
            width / 2 - display_size[0] / 2 + self._pan_x,
            height / 2 - display_size[1] / 2 + self._pan_y,
            scale,
        )

    def set_view_zoom(self, value: float) -> None:
        self._view_zoom = max(0.25, min(4.0, float(value)))
        if self._zoom_changed:
            self._zoom_changed(self._view_zoom)
        self._redraw()

    def change_view_zoom(self, delta: float) -> None:
        self.set_view_zoom(self._view_zoom + delta)

    def fit_to_window(self) -> None:
        self._view_zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        if self._zoom_changed:
            self._zoom_changed(self._view_zoom)
        self._redraw()

    def begin_pan(self, event) -> None:
        if self._image is None:
            return
        self._pan_anchor = (event.x, event.y, self._pan_x, self._pan_y)
        self.canvas.configure(cursor="fleur")

    def pan_to(self, event) -> None:
        if self._pan_anchor is None:
            return
        start_x, start_y, pan_x, pan_y = self._pan_anchor
        self._pan_x = pan_x + event.x - start_x
        self._pan_y = pan_y + event.y - start_y
        self._redraw()

    def end_pan(self, _event=None) -> None:
        self._pan_anchor = None
        self.canvas.configure(cursor="")

    def set_busy(self, text: str = "") -> None:
        self._busy_text = text
        self._redraw()

    def set_guides_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if visible == self._guides_visible:
            return
        self._guides_visible = visible
        self._redraw()

    def set_title(self, title: str) -> None:
        self._title.set(title)

    def set_image(self, image: Image.Image = None) -> None:
        self._image = image.copy() if image is not None else None
        if image is None:
            self.fit_to_window()
        if self.info is not None:
            self.info.configure(text=f"{image.width} x {image.height}" if image else "")
        self._redraw()

    def _redraw(self, _event=None) -> None:
        self.canvas.delete("all")
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        self._draw_canvas_grid(width, height)
        if self._image is None:
            cx, cy = width / 2, height / 2 - 10
            icon_line = COLORS["primary"] if self._accent else "#989AA5"
            self.canvas.create_rectangle(cx - 31, cy - 53, cx + 31, cy + 9, fill="#F8F8FB", outline="#D8D9E0")
            for x1, y1, x2, y2 in (
                (cx - 31, cy - 38, cx - 31, cy - 53), (cx - 31, cy - 53, cx - 16, cy - 53),
                (cx + 16, cy - 53, cx + 31, cy - 53), (cx + 31, cy - 53, cx + 31, cy - 38),
                (cx - 31, cy - 6, cx - 31, cy + 9), (cx - 31, cy + 9, cx - 16, cy + 9),
                (cx + 16, cy + 9, cx + 31, cy + 9), (cx + 31, cy + 9, cx + 31, cy - 6),
            ):
                self.canvas.create_line(x1, y1, x2, y2, fill=icon_line, width=2)
            self.canvas.create_line(cx, cy - 38, cx, cy - 6, fill=icon_line, width=2)
            self.canvas.create_line(cx - 7, cy - 31, cx, cy - 38, cx + 7, cy - 31, fill=icon_line, width=2)
            self.canvas.create_text(cx, cy + 42, text=self._empty_text, fill="#4B4C56", font=("Microsoft YaHei UI", 11, "bold"), justify="center")
            self.canvas.create_text(cx, cy + 70, text="支持 JPG、PNG、WEBP" if not self._accent else "处理完成后可直接导出", fill="#92949E", font=("Microsoft YaHei UI", 9), justify="center")
            self._draw_busy_banner(width)
            return

        margin = 38
        scale = min((width - margin * 2) / self._image.width, (height - margin * 2) / self._image.height)
        scale *= self._view_zoom
        scale = max(0.02, scale)
        display_size = (max(1, round(self._image.width * scale)), max(1, round(self._image.height * scale)))
        shown = self._image.resize(display_size, Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(shown)
        x = width / 2 + self._pan_x
        y = height / 2 + self._pan_y
        left = x - display_size[0] / 2
        top = y - display_size[1] / 2
        self.canvas.create_rectangle(left + 12, top + 14, left + display_size[0] + 12, top + display_size[1] + 14, fill="#D9DBE2", outline="")
        self.canvas.create_rectangle(left + 4, top + 5, left + display_size[0] + 4, top + display_size[1] + 5, fill="#E3E4E9", outline="")
        self.canvas.create_image(x, y, image=self._photo)
        self.canvas.create_rectangle(left - 1, top - 1, left + display_size[0] + 1, top + display_size[1] + 1, outline="#C9CBD3")
        if self._guides_visible:
            self._draw_composition_guides(left, top, display_size[0], display_size[1])
        self._draw_busy_banner(width)

    def _draw_canvas_grid(self, width: int, height: int) -> None:
        spacing = 40
        for x in range(spacing, width, spacing):
            self.canvas.create_line(x, 0, x, height, fill=COLORS["canvas_grid"], width=1)
        for y in range(spacing, height, spacing):
            self.canvas.create_line(0, y, width, y, fill=COLORS["canvas_grid"], width=1)
        self.canvas.create_line(width / 2, 0, width / 2, height, fill="#DDDDE5", width=1)
        self.canvas.create_line(0, height / 2, width, height / 2, fill="#DDDDE5", width=1)

    def _draw_composition_guides(self, left: float, top: float, width: int, height: int) -> None:
        right = left + width
        bottom = top + height
        center_x = left + width * 0.5
        eye_top = top + height * 0.34
        eye_bottom = top + height * 0.47
        crown_top = top + height * 0.04
        crown_bottom = top + height * 0.14
        shoulder_y = top + height * 0.78

        self.canvas.create_rectangle(
            left,
            crown_top,
            right,
            crown_bottom,
            fill="#FFFFFF",
            stipple="gray75",
            outline="",
        )
        self.canvas.create_rectangle(
            left,
            eye_top,
            right,
            eye_bottom,
            fill=COLORS["primary"],
            stipple="gray75",
            outline="",
        )
        line = COLORS["primary"]
        soft_line = "#FFFFFF"
        for x1, y1, x2, y2 in (
            (center_x, top, center_x, bottom),
            (left, eye_top, right, eye_top),
            (left, eye_bottom, right, eye_bottom),
            (left, shoulder_y, right, shoulder_y),
        ):
            self.canvas.create_line(x1, y1, x2, y2, fill=soft_line, width=3, dash=(5, 5))
            self.canvas.create_line(x1, y1, x2, y2, fill=line, width=1, dash=(5, 5))

        label_font = ("Microsoft YaHei UI", 8, "bold")
        self.canvas.create_text(left + 7, crown_top + 5, text="头顶安全区", anchor="nw", fill="#565761", font=label_font)
        self.canvas.create_text(left + 7, eye_top + 5, text="眼线参考区", anchor="nw", fill="#E64063", font=label_font)
        self.canvas.create_text(left + 7, shoulder_y - 6, text="肩部参考线", anchor="sw", fill="#E64063", font=label_font)

    def _draw_busy_banner(self, width: int) -> None:
        if not self._busy_text:
            return
        banner_width = min(300, max(180, len(self._busy_text) * 15 + 44))
        self.canvas.create_rectangle(
            width / 2 - banner_width / 2,
            20,
            width / 2 + banner_width / 2,
            58,
            fill="#FFFFFF",
            outline="#E2E3E9",
        )
        self.canvas.create_oval(width / 2 - banner_width / 2 + 15, 34, width / 2 - banner_width / 2 + 23, 42, fill=COLORS["primary"], outline="")
        self.canvas.create_text(width / 2 - banner_width / 2 + 32, 39, text=self._busy_text, anchor="w", fill="#3C3D46", font=("Microsoft YaHei UI", 9, "bold"))


class InspectorSection(ttk.Frame):
    def __init__(self, master, title: str):
        super().__init__(master, style="Inspector.TFrame")
        ttk.Label(self, text=title, style="SectionTitle.TLabel").pack(fill="x", padx=20, pady=(18, 10))
        self.body = ttk.Frame(self, style="Inspector.TFrame", padding=(20, 0, 20, 18))
        self.body.pack(fill="x")


class ValueScale(ttk.Frame):
    def __init__(self, master, label: str, variable, start: float, end: float, command=None, suffix: str = ""):
        super().__init__(master, style="Inspector.TFrame")
        self.variable = variable
        self.suffix = suffix
        self.value = ttk.Label(self, style="ValuePill.TLabel", width=7, anchor="center")
        ttk.Label(self, text=label, style="Field.TLabel").grid(row=0, column=0, sticky="w")
        self.value.grid(row=0, column=1, sticky="e")
        self.scale = ttk.Scale(self, from_=start, to=end, variable=variable, command=self._changed, style="Accent.Horizontal.TScale")
        self.scale.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(9, 0))
        self.columnconfigure(0, weight=1)
        self._command = command
        self._update_value()

    def _changed(self, _value=None) -> None:
        self._update_value()
        if self._command:
            self._command()

    def _update_value(self) -> None:
        value = self.variable.get()
        shown = f"{value:.1f}" if isinstance(value, float) and not value.is_integer() else str(round(value))
        self.value.configure(text=f"{shown}{self.suffix}")

    def refresh(self) -> None:
        self._update_value()
