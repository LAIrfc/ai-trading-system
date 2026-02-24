@echo off
chcp 65001 >nul
echo ========================================
echo   AI量化交易系统 - Windows版
echo ========================================
echo.

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 错误：未找到Python
    echo.
    echo 请先安装Python：
    echo 1. 访问 https://www.python.org/downloads/
    echo 2. 下载Python 3.10或更高版本
    echo 3. 安装时勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo ✅ Python已安装
python --version
echo.

:MENU
echo ========================================
echo   功能菜单
echo ========================================
echo.
echo 1. 测试系统（检查环境）
echo 2. 获取K线数据
echo 3. 测试策略
echo 4. 模拟交易（内置）
echo 5. 同花顺模拟交易
echo 6. 安装/更新依赖
echo 7. 查看文档
echo 0. 退出
echo.
echo ========================================

set /p choice=请选择 (0-7): 

if "%choice%"=="1" goto TEST
if "%choice%"=="2" goto KLINE
if "%choice%"=="3" goto STRATEGY
if "%choice%"=="4" goto PAPER
if "%choice%"=="5" goto TONGHUASHUN
if "%choice%"=="6" goto INSTALL
if "%choice%"=="7" goto DOCS
if "%choice%"=="0" goto END

echo.
echo ❌ 无效选择
echo.
pause
goto MENU

:TEST
echo.
echo ========================================
echo   系统测试
echo ========================================
echo.
python src\config\platform_config.py
echo.
pause
goto MENU

:KLINE
echo.
echo ========================================
echo   获取K线数据
echo ========================================
echo.
set /p stock=请输入股票代码（如600519）: 
echo.
python tools\kline_fetcher.py %stock%
echo.
pause
goto MENU

:STRATEGY
echo.
echo ========================================
echo   策略测试
echo ========================================
echo.
python tools\strategy_tester.py --interactive
echo.
pause
goto MENU

:PAPER
echo.
echo ========================================
echo   模拟交易（内置）
echo ========================================
echo.
python examples\paper_trading_demo.py
echo.
pause
goto MENU

:TONGHUASHUN
echo.
echo ========================================
echo   同花顺模拟交易
echo ========================================
echo.
echo ⚠️  提示：
echo 1. 请先打开同花顺
echo 2. 登录模拟交易账户
echo 3. 确保模拟交易界面可见
echo.
pause
python examples\tonghuashun_simulator.py
echo.
pause
goto MENU

:INSTALL
echo.
echo ========================================
echo   安装/更新依赖
echo ========================================
echo.
echo 正在安装核心依赖...
pip install pandas numpy akshare loguru
echo.
echo 正在安装桌面自动化依赖...
pip install pyautogui psutil pillow
echo.
echo ✅ 安装完成
echo.
pause
goto MENU

:DOCS
echo.
echo ========================================
echo   文档列表
echo ========================================
echo.
echo 主要文档：
echo.
echo 1. README.md                    - 项目总览
echo 2. WINDOWS_GUIDE.md            - Windows使用指南 ⭐
echo 3. STRATEGY_QUICKSTART.md      - 策略快速开始
echo 4. KLINE_DATA_GUIDE.md         - K线数据获取
echo 5. PAPER_TRADING_GUIDE.md      - 模拟交易指南
echo 6. TONGHUASHUN_SIMULATOR_GUIDE.md - 同花顺模拟交易
echo 7. QUICK_REFERENCE.md          - 快速参考
echo.
echo 查看文档：
echo   type WINDOWS_GUIDE.md
echo.
echo 或用记事本/浏览器打开 .md 文件
echo.
pause
goto MENU

:END
echo.
echo ========================================
echo   感谢使用！
echo ========================================
echo.
echo 💡 提示：
echo - 查看 WINDOWS_GUIDE.md 了解详细使用方法
echo - 有问题查看 TROUBLESHOOTING.md
echo - 祝交易顺利！📈
echo.
pause
exit /b 0
