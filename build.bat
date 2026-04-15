@echo off
setlocal

echo.
echo  ================================================
echo    SecureDelete — Windows EXE Build Script
echo  ================================================
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found in PATH. Please install Python 3.10+ and re-run.
    pause
    exit /b 1
)

:: Install / upgrade dependencies
echo  [1/3] Installing build dependencies...
pip install --upgrade pyinstaller customtkinter pillow >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] pip install failed. Check your internet connection.
    pause
    exit /b 1
)
echo        Done.

:: Convert the PNG icon to ICO (Pillow required)
echo  [2/3] Preparing icon...
python -c "from PIL import Image; img = Image.open('icon.png'); img.save('icon.ico', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])" 2>nul
if errorlevel 1 (
    echo         [WARN] Icon conversion failed — building without icon.
    :: Patch spec to remove icon reference so build still succeeds
    powershell -Command "(Get-Content build.spec) -replace \"icon='icon.ico',\", \"icon=None,\" | Set-Content build.spec"
)

:: Run PyInstaller (use python -m to avoid PATH issues with MS Store Python)
echo  [3/3] Building SecureDelete.exe (this may take 1-2 minutes)...
python -m PyInstaller build.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed. See output above for details.
    pause
    exit /b 1
)

echo.
echo  ================================================
echo    BUILD COMPLETE!
echo    Output: dist\SecureDelete.exe
echo  ================================================
echo.
echo  The EXE is fully self-contained — no Python needed.
echo  Copy dist\SecureDelete.exe to any Windows machine and run.
echo.
pause
