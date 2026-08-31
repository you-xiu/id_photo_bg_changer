# Windows 打包与发布

## 1. 构建环境

必须在 Windows 环境中构建，并使用包含 Tkinter 的 Python：

```powershell
python --version
python -c "import tkinter; print(tkinter.TkVersion)"
python -m pip install -r requirements.txt
```

## 2. 构建单文件 EXE

```powershell
python -m PyInstaller --noconfirm --clean IdPhotoBgChanger.spec
```

生成文件：

```text
dist\证件照换底色.exe
```

主 spec 会根据当前 Python 查找 Tcl/Tk 运行文件，并打包应用图标、MODNet 模型、YuNet 模型和运行依赖。

## 3. 发布检查

在没有 Python 环境的干净 Windows 目录中启动 EXE，检查窗口、图标、图片打开、抠图、背景色、照片规格、透明 PNG、质量检测和保存功能。

```powershell
Test-Path dist\证件照换底色.exe
Get-FileHash dist\证件照换底色.exe -Algorithm SHA256
```

推荐把 EXE 放在 GitHub Release，不要提交 `build/`、`dist/`、用户原图或临时解包目录到 Git 历史。
