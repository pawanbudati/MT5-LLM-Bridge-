@echo off
title Telegram Multi-Channel MT5 Unified Bot
color 0A
cd /d "%~dp0"

echo ===============================================================================
echo        TELEGRAM MULTI-CHANNEL -> MULTI-MT5 TERMINAL UNIFIED BOT
echo ===============================================================================
echo.
echo Starting unified bot runner...
echo.

python main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] The bot exited with error code %ERRORLEVEL%.
    pause
)
