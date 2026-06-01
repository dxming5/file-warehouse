@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==================================================
echo   个人文件仓库 - 打包为 EXE
echo ==================================================
echo.

:: 检查是否需要重新打包：exe 存在且比源码新则跳过
set NEED_BUILD=0
if not exist "file-warehouse.exe" set NEED_BUILD=1
if %NEED_BUILD%==0 for %%F in ("app.py") do for %%E in ("file-warehouse.exe") do if "%%~tF" GTR "%%~tE" set NEED_BUILD=1
if %NEED_BUILD%==0 for %%F in ("templates\index.html") do for %%E in ("file-warehouse.exe") do if "%%~tF" GTR "%%~tE" set NEED_BUILD=1
if %NEED_BUILD%==0 for %%F in ("icon.ico") do for %%E in ("file-warehouse.exe") do if "%%~tF" GTR "%%~tE" set NEED_BUILD=1

if %NEED_BUILD%==0 (
    echo exe 已是最新，无需重新打包。
    echo.
    pause
    exit /b 0
)

echo 检测到源码更新，开始打包...

echo [1/3] 检查并安装依赖...
pip install flask pywebview pyinstaller pypinyin natsort -q

echo [2/4] 开始打包（可能需要几分钟）...
pyinstaller --onefile --windowed --distpath "." --add-data "templates;templates" --add-data "icon.ico;." --icon="icon.ico" --name "file-warehouse" app.py

echo.
echo [3/4] 清理中间文件...
if exist "build" rmdir /s /q "build"
if exist "file-warehouse.spec" del /q "file-warehouse.spec"

echo.
echo [4/4] 打包完成！
echo.
echo EXE 文件位置：file-warehouse.exe
echo.
pause
