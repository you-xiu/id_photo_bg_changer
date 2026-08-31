# 用户使用指南

## 1. 安装

建议使用 Windows 10 或更高版本、Python 3.10 或更高版本。模型已经放在 `pictone/models/`，源码运行默认不需要另外下载。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -c "import tkinter; print(tkinter.TkVersion)"
```

## 2. 启动桌面版

```powershell
python id_photo_bg_changer.py
```

也可以双击项目根目录的 `run_gui.bat`。如果已经构建成品，可直接运行 `dist\证件照换底色.exe`。

## 3. 处理流程

1. 打开 JPG、JPEG、PNG、WEBP 或 BMP 图片。
2. 等待人物抠图完成，查看透明抠图预览。
3. 选择蓝、红、白、浅灰、深蓝或自定义背景色。
4. 选择一寸、二寸、小一寸或小二寸规格。
5. 按需要调整缩放、位置、旋转、亮度和边缘参数。
6. 使用质量检测和透明预览复核头发、耳朵、肩线及背景边缘。
7. 保存证件照，或导出透明人物 PNG。

## 4. 输出规格

| 规格 | 输出像素 |
| --- | ---: |
| 一寸 | 295 × 413 |
| 二寸 | 413 × 579 |
| 小一寸 | 260 × 378 |
| 小二寸 | 390 × 567 |

桌面版还支持批量处理、红白蓝三色导出、6 寸打印排版、DPI 设置和局部蒙版修复。不同使用单位的尺寸、背景色和头部比例要求可能不同，提交前请以对方规范为准。

## 5. 命令行

```powershell
python cli.py input.jpg output.png --color "#438EDB" --size one
```

支持的规格为 `one`、`two`、`small_one` 和 `small_two`；常用参数还包括 `--tolerance` 与 `--feather`。

## 6. 隐私

图片默认只在本机处理，不主动调用在线图片处理接口。不要将包含身份证号、住址或其他敏感信息的原图提交到公开 Issue、Pull Request 或仓库。
