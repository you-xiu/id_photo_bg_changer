# 系统架构

## 1. 总体结构

```text
桌面入口 id_photo_bg_changer.py ─┐
                                 ├─ pictone/engine.py
命令行入口 cli.py ───────────────┘       ├─ pictone/matting.py
                                         ├─ pictone/face.py
                                         ├─ pictone/quality.py
                                         ├─ pictone/model.py
                                         └─ pictone/output.py
```

桌面版和 CLI 共用 `pictone/` 图像处理核心，算法不会因入口不同而复制维护。

## 2. 目录职责

```text
pictone/
├─ app.py       # Tkinter 界面和交互状态
├─ engine.py    # 抠图、蒙版、裁切和背景合成
├─ face.py      # YuNet 人脸检测与自动构图
├─ matting.py   # MODNet ONNX 推理
├─ model.py     # 照片规格和处理设置
├─ output.py    # 图片编码、DPI 和打印排版
├─ quality.py   # 输出质量检查
├─ widgets.py   # 桌面版通用控件
├─ assets/      # 应用图标
└─ models/      # MODNet 和 YuNet 模型
```

根目录的 `id_photo_bg_changer.py` 是桌面入口，`cli.py` 是命令行入口，`IdPhotoBgChanger.spec` 是单文件 EXE 构建配置。

## 3. 处理流水线

1. Pillow 读取图片、修正 EXIF 方向并转换为 RGB。
2. MODNet 生成 alpha 蒙版，并执行边缘净化；模型不可用时使用传统算法回退。
3. YuNet 检测人脸和眼部关键点，计算自动构图建议。
4. 按照片规格裁切、缩放、旋转和调整亮度。
5. 将人物合成到背景色，执行质量检查并导出 PNG 或 JPEG。

## 4. 设计边界

- 工具面向本机使用，不是多用户生产服务。
- 质量检查是辅助提示，不等同于任何机构的官方审核。
- 复杂背景、遮挡、发丝混杂或严重模糊的图片应使用透明预览和局部蒙版修复进行人工复核。
