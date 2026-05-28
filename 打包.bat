@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==================================================
echo   个人文件仓库 - 打包为 EXE
echo ==================================================
echo.

echo [1/3] 检查并安装依赖...
pip install flask pywebview pyinstaller -q

echo [2/3] 开始打包（可能需要几分钟）...
pyinstaller --onefile --windowed --add-data "templates;templates" --name "个人文件仓库" app.py

echo.
echo [3/3] 打包完成！
echo.
echo EXE 文件位置：dist\个人文件仓库.exe
echo.
pause
