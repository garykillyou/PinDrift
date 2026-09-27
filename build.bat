@echo off
cd /d "%~dp0"

echo [1/2] Installing pinned dependencies...
rem requirements-lock.txt holds the exact tested versions (see scripts\lock_requirements.py);
rem requirements.txt only has version ranges, so a fresh install could pick a newer release.
python -m pip install -r requirements-lock.txt || goto :error

echo [2/2] Building...
python -m PyInstaller --noconfirm --clean PinDrift.spec || goto :error

echo.
echo Build finished: dist\PinDrift\PinDrift.exe
pause
exit /b 0

:error
echo.
echo Build FAILED.
pause
exit /b 1
