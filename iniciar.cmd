@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows\iniciar.ps1" %*
exit /b %ERRORLEVEL%
