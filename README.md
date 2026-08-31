# 证件照换底色

原生 Windows 桌面证件照处理工具，使用 Python、Tkinter、OpenCV、Pillow 和本地 AI 模型完成人物抠图、背景换色、尺寸裁切与打印排版。

程序不启动本地网站，不依赖浏览器或 WebView。图片始终在本机处理，适合需要离线处理证件照的场景。

完整项目文档见 [docs/README.md](docs/README.md)，包括用户指南、系统架构、EXE 打包、开发、测试和常见问题。

## 功能亮点

- MODNet 人像抠图，先生成透明人物蒙版，再进行背景合成
- OpenCV 轮廓精修、发丝边缘去白边与局部蒙版修复
- YuNet 人脸检测、自动构图、眼线校正和导出前合规检查
- 蓝、红、白、浅灰、深蓝及自定义背景色
- 一寸、二寸、小一寸、小二寸规格
- 缩放、水平位置、垂直位置、旋转与亮度调整
- 抠图预览、原图/成片对比、透明人物 PNG 导出
- 撤销/重做蒙版修改，支持保留、删除和柔化三种修复方式
- DPI 元数据、JPEG 体积控制、6 寸照片打印排版
- 文件夹批量处理、红白蓝三色批量导出

## 下载成品

Windows 用户可以从 [Releases](../../releases/latest) 下载单文件版：

```text
证件照换底色.exe
```

成品已包含 Python 运行库、Tk 运行库、AI 模型和软件图标，不需要额外安装 Python，也不需要旁边放置模型文件或资源文件。

> 说明：由于单文件成品接近 100 MB，仓库通过 GitHub Release 分发 EXE，不把它提交到 Git 历史中。

## 从源码运行

建议使用 Python 3.10 或更高版本。

```powershell
git clone https://github.com/<your-account>/id-photo-bg-changer.git
cd id-photo-bg-changer

python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python id_photo_bg_changer.py
```

也可以双击 `run_gui.bat`，或在启动时传入图片路径：

```powershell
python id_photo_bg_changer.py D:\Pictures\portrait.jpg
```

## 命令行处理

```powershell
python cli.py input.jpg output.png --color "#438EDB" --size one
```

可用规格：`one`、`two`、`small_one`、`small_two`。

常用参数：

```text
--color       背景色，支持 #RRGGBB
--size        输出规格
--tolerance   传统背景识别容差，默认 48
--feather     边缘羽化强度，默认 0.6
```

## 构建 Windows 单文件 EXE

在 Windows 环境执行。请使用已经安装 Tkinter 的 Python 解释器：

```powershell
python -c "import tkinter; print(tkinter.TkVersion)"
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean IdPhotoBgChanger.spec
```

如果系统中安装了多个 Python，请确保上面两条命令使用的是同一个解释器；在 Windows 上可以用 `py -3.13` 替换 `python`。

生成文件：

```text
dist\证件照换底色.exe
```

`IdPhotoBgChanger.spec` 会根据当前构建所用 Python 自动查找 Tcl/Tk 文件，不依赖某台电脑上的固定安装路径。

## 项目结构

```text
.
├── pictone/
│   ├── app.py                 # Tkinter 界面与交互
│   ├── engine.py              # 抠图、蒙版和成片渲染
│   ├── face.py                # YuNet 人脸检测与构图建议
│   ├── matting.py             # MODNet 推理
│   ├── model.py               # 数据模型和照片规格
│   ├── output.py              # 图片编码和打印排版
│   ├── quality.py             # 输出质量检查
│   ├── widgets.py             # 通用界面组件
│   ├── assets/app_icon.ico    # Windows 应用图标
│   └── models/                # 离线 AI 模型
├── cli.py                     # 命令行入口
├── id_photo_bg_changer.py     # 桌面应用入口
├── IdPhotoBgChanger.spec      # PyInstaller 单文件构建配置
├── requirements.txt           # Python 依赖
├── docs/                       # 项目文档
└── run_gui.bat                # Windows 源码启动脚本
```

## 文档导航

- [项目文档总览](docs/README.md)
- [用户使用指南](docs/USER_GUIDE.md)
- [系统架构](docs/ARCHITECTURE.md)
- [Windows 打包与发布](docs/BUILD.md)
- [开发指南](docs/DEVELOPMENT.md)
- [测试与验收](docs/TESTING.md)
- [常见问题](docs/FAQ.md)

## 技术栈

- Python 3.10+
- Tkinter
- Pillow
- NumPy
- OpenCV
- MODNet portrait matting
- OpenCV Zoo YuNet face detector
- PyInstaller

## 隐私与安全

- 默认不上传图片，不调用在线图片处理接口
- 输入图片、透明蒙版和导出结果都在本机处理
- 建议不要把包含身份证号、住址或其他敏感信息的原图提交到公开仓库
- 仓库中的模型文件用于离线推理，具体许可和来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## 许可

本项目使用 MIT License，详见 [LICENSE](LICENSE)。第三方模型、库和图标按照各自上游许可使用，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 参与贡献

欢迎提交 Issue 和 Pull Request。提交代码前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。
