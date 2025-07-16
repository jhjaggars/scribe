@echo off
REM Simple batch file to build Scribe for Windows
REM Usage: build-windows.bat [cli|gui|both]

setlocal enabledelayedexpansion

echo Scribe Windows Build Script
echo ===========================

REM Set build type (default: both)
set BUILD_TYPE=%1
if "%BUILD_TYPE%"=="" set BUILD_TYPE=both

echo Build type: %BUILD_TYPE%
echo.

REM Check for Python
echo Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)
echo Python found.

REM Check for uv
echo Checking uv installation...
uv --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: uv not found. Installing...
    pip install uv
    if errorlevel 1 (
        echo ERROR: Failed to install uv.
        pause
        exit /b 1
    )
)
echo uv found.

REM Install dependencies
echo Installing dependencies...
uv sync
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

REM Install PyInstaller
echo Installing PyInstaller...
uv add --dev pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install PyInstaller.
    pause
    exit /b 1
)

REM Clean previous builds
echo Cleaning previous builds...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

REM Build CLI if requested
if "%BUILD_TYPE%"=="cli" goto build_cli
if "%BUILD_TYPE%"=="both" goto build_cli
goto check_gui

:build_cli
echo Building CLI version...
uv run pyinstaller scribe-cli.spec --clean
if errorlevel 1 (
    echo ERROR: Failed to build CLI version.
    pause
    exit /b 1
)
echo CLI build complete.

:check_gui
if "%BUILD_TYPE%"=="gui" goto build_gui
if "%BUILD_TYPE%"=="both" goto build_gui
goto package

:build_gui
echo Building Windows GUI version...
uv run pyinstaller scribe-gui-windows.spec --clean
if errorlevel 1 (
    echo ERROR: Failed to build GUI version.
    pause
    exit /b 1
)
echo GUI build complete.

:package
echo Creating distribution package...
mkdir dist\scribe-windows-package 2>nul

REM Copy executables
if "%BUILD_TYPE%"=="cli" xcopy /e /i dist\scribe-cli dist\scribe-windows-package\scribe-cli
if "%BUILD_TYPE%"=="gui" xcopy /e /i dist\scribe-gui-windows dist\scribe-windows-package\scribe-gui-windows
if "%BUILD_TYPE%"=="both" (
    xcopy /e /i dist\scribe-cli dist\scribe-windows-package\scribe-cli
    xcopy /e /i dist\scribe-gui-windows dist\scribe-windows-package\scribe-gui-windows
)

REM Create runner batch files
if "%BUILD_TYPE%"=="cli" goto create_cli_runner
if "%BUILD_TYPE%"=="both" goto create_cli_runner
goto check_gui_runner

:create_cli_runner
echo @echo off > dist\scribe-windows-package\run-scribe-cli.bat
echo echo Starting Scribe CLI... >> dist\scribe-windows-package\run-scribe-cli.bat
echo cd /d "%%~dp0scribe-cli" >> dist\scribe-windows-package\run-scribe-cli.bat
echo scribe-cli.exe %%* >> dist\scribe-windows-package\run-scribe-cli.bat
echo pause >> dist\scribe-windows-package\run-scribe-cli.bat

:check_gui_runner
if "%BUILD_TYPE%"=="gui" goto create_gui_runner
if "%BUILD_TYPE%"=="both" goto create_gui_runner
goto finish

:create_gui_runner
echo @echo off > dist\scribe-windows-package\run-scribe-gui.bat
echo echo Starting Scribe Windows GUI... >> dist\scribe-windows-package\run-scribe-gui.bat
echo cd /d "%%~dp0scribe-gui-windows" >> dist\scribe-windows-package\run-scribe-gui.bat
echo start scribe-gui-windows.exe >> dist\scribe-windows-package\run-scribe-gui.bat

:finish
echo.
echo Build completed successfully!
echo Package location: dist\scribe-windows-package
echo.
echo To test:
if "%BUILD_TYPE%"=="cli" echo   CLI: dist\scribe-windows-package\run-scribe-cli.bat
if "%BUILD_TYPE%"=="gui" echo   GUI: dist\scribe-windows-package\run-scribe-gui.bat
if "%BUILD_TYPE%"=="both" (
    echo   CLI: dist\scribe-windows-package\run-scribe-cli.bat
    echo   GUI: dist\scribe-windows-package\run-scribe-gui.bat
)
echo.
pause