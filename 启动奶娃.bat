@echo off
setlocal
chcp 65001 >nul
set "pet_executable=%~dp0dist\奶娃桌宠\奶娃桌宠.exe"
if exist "%pet_executable%" (
    if /i "%~1"=="--check" (
        echo "%pet_executable%"
        exit /b 0
    )
    start "" "%pet_executable%" --panel
    if errorlevel 1 goto failed
    exit /b 0
)
set "pet_python=%~dp0.venv\Scripts\pythonw.exe"
if exist "%pet_python%" (
    if /i "%~1"=="--check" (
        echo "%pet_python%"
        exit /b 0
    )
    start "" "%pet_python%" "%~dp0main.py" --panel
    if errorlevel 1 goto failed
    exit /b 0
)
if /i "%~1"=="--check" exit /b 1
echo 请先运行「安装开发环境.bat」，或解压便携包并双击其中的「奶娃桌宠.exe」。
pause
exit /b 1
:failed
echo 奶娃启动失败，请直接双击 dist 文件夹中的「奶娃桌宠.exe」。
pause
exit /b 1
