@echo off
REM ============================================================
REM 📊 每日更新：推荐 + 持仓
REM ============================================================
REM 用法:
REM   scripts\daily_update.bat         # 完整更新（含股票池，30-45分钟）
REM   scripts\daily_update.bat --quick # 快速模式（5-10分钟）
REM ============================================================

cd /d "%~dp0\.."
set PYTHON=.\.python\py311\python.exe
set PYTHONIOENCODING=utf-8

echo.
echo ============================================================
echo   📊 每日更新开始
echo ============================================================
echo.

REM 检查快速模式
if "%1"=="--quick" (
    echo [快速模式] 跳过股票池更新
    echo.
) else (
    echo [1/3] 更新股票池...
    %PYTHON% tools\data\quarterly_update.py --force
    if errorlevel 1 (
        echo ❌ 失败
        pause
        exit /b 1
    )
    echo ✅ 完成
    echo.
)

echo [2/3] 生成推荐...
%PYTHON% tools\analysis\recommend_today.py --pool mydate\stock_pool_all.json --strategy full_11 --top 10
if errorlevel 1 (
    echo ❌ 失败
    pause
    exit /b 1
)
echo ✅ 完成
echo.

echo [3/3] 更新文档...
%PYTHON% tools\portfolio\update_daily_tracking.py
echo ✅ 完成
echo.

echo ============================================================
echo   ✅ 更新完成！
echo ============================================================
echo.
echo 查看推荐: notepad docs\DAILY_TRACKING.md
echo.

pause
