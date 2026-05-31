@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==================================================
echo   个人文件仓库管理系统 v1.0
echo ==================================================
echo.
echo 正在检查依赖...
pip show flask >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装 Flask...
    pip install flask
    echo.
)
pip show pywebview >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装 pywebview...
    pip install pywebview
    echo.
)
pip show pypinyin >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装 pypinyin...
    pip install pypinyin
    echo.
)
pip show natsort >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装 natsort...
    pip install natsort
    echo.
)
echo 正在启动...
python app.py
pause
