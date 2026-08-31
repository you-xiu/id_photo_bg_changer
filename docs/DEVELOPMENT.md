# 开发指南

## 1. 开发环境

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

桌面版和 EXE 构建需要 Tkinter；CLI 仍依赖同一套图像处理库和模型。

## 2. 修改范围

| 需求 | 主要文件 |
| --- | --- |
| 抠图和背景合成 | `pictone/engine.py`、`pictone/matting.py` |
| 人脸检测和构图 | `pictone/face.py` |
| 质量检查 | `pictone/quality.py` |
| 输出和打印 | `pictone/output.py` |
| 桌面界面 | `pictone/app.py`、`pictone/widgets.py` |
| 命令行 | `cli.py` |
| EXE 构建 | `IdPhotoBgChanger.spec` |

## 3. 检查命令

```powershell
python -m compileall -q pictone cli.py id_photo_bg_changer.py
git diff --check
```

修改核心算法后，应同时验证桌面版和 CLI。不要复制模型、图像处理逻辑或用户图片到仓库。
