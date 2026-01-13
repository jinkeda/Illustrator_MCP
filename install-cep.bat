@echo off
REM ============================================
REM Illustrator MCP CEP Extension Installer
REM ============================================
REM This script installs the CEP extension for Adobe Illustrator
REM by creating a symbolic link in the CEP extensions folder.
REM Run as Administrator!

setlocal

REM Configuration
set EXTENSION_ID=com.illustrator.mcp.panel
set SOURCE_DIR=%~dp0cep-extension
set TARGET_DIR=%APPDATA%\Adobe\CEP\extensions\%EXTENSION_ID%

echo.
echo =============================================
echo  Illustrator MCP CEP Extension Installer
echo =============================================
echo.

REM Check if running as admin
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: This script requires Administrator privileges.
    echo Please right-click and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

REM Check if source directory exists
if not exist "%SOURCE_DIR%" (
    echo ERROR: Source directory not found: %SOURCE_DIR%
    echo Make sure you're running this from the project root folder.
    pause
    exit /b 1
)

REM Create CEP extensions directory if it doesn't exist
if not exist "%APPDATA%\Adobe\CEP\extensions" (
    echo Creating CEP extensions directory...
    mkdir "%APPDATA%\Adobe\CEP\extensions"
)

REM Remove existing installation if present
if exist "%TARGET_DIR%" (
    echo Removing existing installation...
    rmdir /s /q "%TARGET_DIR%" 2>nul
    rd "%TARGET_DIR%" 2>nul
)

REM Create symbolic link
echo Creating symbolic link...
echo   From: %SOURCE_DIR%
echo   To:   %TARGET_DIR%
mklink /D "%TARGET_DIR%" "%SOURCE_DIR%"

if %errorLevel% neq 0 (
    echo.
    echo ERROR: Failed to create symbolic link.
    echo Trying to copy files instead...
    xcopy /E /I /Y "%SOURCE_DIR%" "%TARGET_DIR%"
)

REM Enable debug mode in registry for both CSXS.11 and CSXS.12
echo.
echo Enabling CEP debug mode...
reg add "HKEY_CURRENT_USER\Software\Adobe\CSXS.11" /v PlayerDebugMode /t REG_SZ /d 1 /f
reg add "HKEY_CURRENT_USER\Software\Adobe\CSXS.12" /v PlayerDebugMode /t REG_SZ /d 1 /f

echo.
echo =============================================
echo  Installation Complete!
echo =============================================
echo.
echo Next steps:
echo 1. Start the proxy-server: cd proxy-server ^&^& npm install ^&^& node index.js
echo 2. Open Adobe Illustrator
echo 3. Go to Window ^> Extensions ^> MCP Control
echo 4. Click "Connect" in the panel
echo.
echo To debug the panel, open Chrome and navigate to:
echo   http://localhost:8088
echo.

pause
