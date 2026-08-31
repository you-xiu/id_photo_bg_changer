# 贡献指南

感谢你愿意改进这个项目。

项目文档入口： [docs/README.md](docs/README.md)。提交涉及桌面版、命令行、打包或测试的修改前，请先阅读对应专题文档。

## 开始开发

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 提交前检查

```powershell
python -m compileall -q pictone cli.py id_photo_bg_changer.py
```

如果修改了打包配置，请在 Windows 上执行一次 PyInstaller 构建，并确认 `python -c "import tkinter"` 通过，且 `dist\证件照换底色.exe` 可以启动。

## 提交规范

- 一个 Pull Request 聚焦一个问题
- 不要提交 `build/`、`dist/`、`qa_detail/`、`gc48.png` 或其他个人测试素材
- 不要把用户照片、身份证件或带有个人信息的图片加入仓库
- 新增第三方模型、图片或代码时，请在 `THIRD_PARTY_NOTICES.md` 补充来源和许可
- 界面文案和用户可见功能以中文为主，代码和文件名保持清晰、稳定
