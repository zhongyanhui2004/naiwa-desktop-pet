@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo 安装完成。双击「启动奶娃.bat」即可。
pause
exit /b 0
:failed
echo 安装失败。请确认已安装 Python 3.10 或更新版本，并检查网络连接。
pause
exit /b 1
