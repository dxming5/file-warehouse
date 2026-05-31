@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==================================================
echo   个人文件仓库管理系统 v1.0
echo ==================================================
echo.
echo 正在检查依赖...
pip install flask pywebview pypinyin natsort -q
echo 正在启动...
python app.py
pause
