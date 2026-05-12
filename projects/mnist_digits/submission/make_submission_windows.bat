@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "OUTPUT=%SCRIPT_DIR%mnist_python_sample_submission.zip"
set "TMP_DIR=%SCRIPT_DIR%.tmp_mnist_submission"
if exist "%TMP_DIR%" rmdir /s /q "%TMP_DIR%"
mkdir "%TMP_DIR%"
copy /Y "%PROJECT_DIR%\sample_solution\main.py" "%TMP_DIR%\main.py" >nul
if exist "%OUTPUT%" del /q "%OUTPUT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%TMP_DIR%\main.py' -DestinationPath '%OUTPUT%' -Force"
rmdir /s /q "%TMP_DIR%"
echo Created: %OUTPUT%
endlocal
