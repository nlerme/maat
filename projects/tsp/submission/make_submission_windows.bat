@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "OUTPUT=%SCRIPT_DIR%tsp_cpp_sample_submission.zip"
set "TMP_DIR=%SCRIPT_DIR%.tmp_tsp_submission"
if exist "%TMP_DIR%" rmdir /s /q "%TMP_DIR%"
mkdir "%TMP_DIR%\src"
copy /Y "%PROJECT_DIR%\sample_solution\src\main.cpp" "%TMP_DIR%\src\main.cpp" >nul
if exist "%OUTPUT%" del /q "%OUTPUT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%TMP_DIR%\src' -DestinationPath '%OUTPUT%' -Force"
rmdir /s /q "%TMP_DIR%"
echo Created: %OUTPUT%
endlocal
