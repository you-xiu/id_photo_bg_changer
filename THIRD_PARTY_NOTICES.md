# Third-party notices

PicTone includes the MODNet photographic portrait-matting model distributed by
the `yakhyo/modnet` project. The weights were ported from the official MODNet
project and are licensed under the Apache License 2.0.

- Project: https://github.com/yakhyo/modnet
- Original project: https://github.com/ZHKKKe/MODNet
- Model: `modnet_photographic.onnx`
- Model SHA-256: `5069a5e306b9f5e9f4f2b0360264c9f8ea13b257c7c39943c7cf6a2ec3a102ae`
- License: https://www.apache.org/licenses/LICENSE-2.0

PicTone also uses OpenCV and Pillow for local image processing. Their own
licenses apply to those components.

The application icon is adapted from Microsoft's Fluent UI Emoji `Camera with
flash` artwork.

- Project: https://github.com/microsoft/fluentui-emoji
- Asset: `Camera with flash`
- License: MIT (see the upstream project for the complete license text)

PicTone also includes the OpenCV Zoo YuNet face detection model for offline
face landmarks and composition checks.

- Model: `face_detection_yunet_2023mar.onnx`
- Project: https://github.com/opencv/opencv_zoo
- License: MIT (see the upstream project for the complete license text)
