import subprocess, sys, os

# 切换到脚本所在目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 静默安装依赖（已安装则跳过）
subprocess.run(
    [sys.executable, '-m', 'pip', 'install', 'flask', 'pywebview', 'pypinyin', 'natsort', '-q'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)

# 启动应用
import runpy
runpy.run_path('app.py', run_name='__main__')
