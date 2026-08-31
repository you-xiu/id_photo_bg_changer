import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk


COLORS = {
    "surface": "#FFFFFF",
    "canvas": "#E9EDF2",
    "line": "#D7DCE3",
    "muted": "#68707C",
    "text": "#20242A",
}


class PhotoViewport(ttk.Frame):
    def __init__(self, master, title: str, empty_text: str):
        super().__init__(master, style="Viewport.TFrame")
        self._image = None
        self._photo = None
        self._view_zoom = 1.0
        self._title = tk.StringVar(value=title)
        self._empty_text = empty_text

        bar = ttk.Frame(self, style="ViewportHeader.TFrame", padding=(12, 8))
        bar.pack(fill="x")
        ttk.Label(bar, textvariable=self._title, style="ViewportTitle.TLabel").pack(side="left")
        self.info = ttk.Label(bar, text="", style="ViewportInfo.TLabel")
        self.info.pack(side="right")

        self.canvas = tk.Canvas(self, background=COLORS["canvas"], highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._redraw)
        self._redraw()

    def image_transform(self):
        if self._image is None:
            return None
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        margin = 28
        scale = min((width - margin * 2) / self._image.width, (height - margin * 2) / self._image.height)
        scale *= self._view_zoom
        display_size = (max(1, round(self._image.width * scale)), max(1, round(self._image.height * scale)))
        return (width / 2 - display_size[0] / 2, height / 2 - display_size[1] / 2, scale)

    def set_view_zoom(self, value: float) -> None:
        self._view_zoom = max(0.5, min(4.0, float(value)))
        self._redraw()

    def change_view_zoom(self, delta: float) -> None:
        self.set_view_zoom(self._view_zoom + delta)

    def set_title(self, title: str) -> None:
        self._title.set(title)

    def set_image(self, image: Image.Image = None) -> None:
        self._image = image.copy() if image is not None else None
        self.info.configure(text=f"{image.width} x {image.height}" if image else "")
        self._redraw()

    def _redraw(self, _event=None) -> None:
        self.canvas.delete("all")
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        if self._image is None:
            self.canvas.create_text(
                width / 2,
                height / 2,
                text=self._empty_text,
                fill=COLORS["muted"],
                font=("Microsoft YaHei UI", 10),
                justify="center",
            )
            return

        margin = 28
        scale = min((width - margin * 2) / self._image.width, (height - margin * 2) / self._image.height)
        scale *= self._view_zoom
        scale = max(0.02, scale)
        display_size = (max(1, round(self._image.width * scale)), max(1, round(self._image.height * scale)))
        shown = self._image.resize(display_size, Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(shown)
        x = width / 2
        y = height / 2
        left = x - display_size[0] / 2
        top = y - display_size[1] / 2
        self.canvas.create_rectangle(left + 5, top + 6, left + display_size[0] + 5, top + display_size[1] + 6, fill="#C7CDD4", outline="")
        self.canvas.create_image(x, y, image=self._photo)
        self.canvas.create_rectangle(left, top, left + display_size[0], top + display_size[1], outline="#B8BEC6")


class InspectorSection(ttk.Frame):
    def __init__(self, master, title: str):
        super().__init__(master, style="Inspector.TFrame")
        ttk.Label(self, text=title, style="SectionTitle.TLabel").pack(fill="x", padx=16, pady=(14, 8))
        self.body = ttk.Frame(self, style="Inspector.TFrame", padding=(16, 0, 16, 14))
        self.body.pack(fill="x")


class ValueScale(ttk.Frame):
    def __init__(self, master, label: str, variable, start: float, end: float, command=None, suffix: str = ""):
        super().__init__(master, style="Inspector.TFrame")
        self.variable = variable
        self.suffix = suffix
        self.value = ttk.Label(self, style="Value.TLabel", width=7, anchor="e")
        ttk.Label(self, text=label, style="Field.TLabel").grid(row=0, column=0, sticky="w")
        self.value.grid(row=0, column=1, sticky="e")
        self.scale = ttk.Scale(self, from_=start, to=end, variable=variable, command=self._changed)
        self.scale.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
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
