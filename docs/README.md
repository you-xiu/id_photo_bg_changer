# 项目文档

“证件照换底色”是一个本地 Windows 证件照处理工具，提供桌面版和命令行入口，共用 `pictone/` 图像处理核心。

## 文档导航

- [用户使用指南](USER_GUIDE.md)
- [系统架构](ARCHITECTURE.md)
- [Windows 打包与发布](BUILD.md)
- [开发指南](DEVELOPMENT.md)
- [测试与验收](TESTING.md)
- [常见问题](FAQ.md)

## 快速入口

桌面版：

```powershell
python id_photo_bg_changer.py
```

命令行：

```powershell
python cli.py input.jpg output.png --color "#438EDB" --size one
```
