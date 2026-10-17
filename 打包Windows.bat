@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" build.py
if errorlevel 1 goto failed
echo 打包完成，程序和压缩包位于 dist 文件夹。
pause
exit /b 0
:failed
echo 打包失败，请查看上方提示。
pause
exit /b 1
