@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
    echo 未找到 Python，请先安装 Python 3.10 或更高版本。
    pause
    exit /b 1
)
pythonw id_photo_bg_changer.py %*
