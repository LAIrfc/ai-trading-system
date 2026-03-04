# Windows 使用指南 🪟

## ✅ 兼容性说明

好消息！**系统的核心功能都支持Windows**，而且Windows版同花顺更成熟稳定！

### 完全支持的功能

| 功能 | Windows支持 | 说明 |
|------|------------|------|
| **策略开发** | ✅ 完全支持 | Python跨平台 |
| **实时数据获取** | ✅ 完全支持 | AKShare支持Windows |
| **K线数据** | ✅ 完全支持 | 数据获取无差异 |
| **策略测试** | ✅ 完全支持 | 测试工具跨平台 |
| **模拟交易（内置）** | ✅ 完全支持 | 纯Python实现 |
| **同花顺桌面自动化** | ✅ 完全支持 | PyAutoGUI支持Windows |
| **同花顺模拟交易** | ✅ 完全支持 | Windows版同花顺更好 |

### 需要调整的部分

- 🔧 **安装方式** - 使用pip而非apt
- 🔧 **路径格式** - Windows使用反斜杠
- 🔧 **同花顺路径** - 需要修改为Windows路径

---

## 🚀 Windows 快速开始

### 第1步：安装Python

#### 检查Python

打开 `PowerShell` 或 `命令提示符`：

```powershell
python --version
```

如果显示 `Python 3.8` 或更高版本，可以跳过安装。

#### 安装Python（如果需要）

1. 访问 https://www.python.org/downloads/
2. 下载 Python 3.10 或 3.11（推荐）
3. 安装时**勾选** "Add Python to PATH"
4. 验证安装：`python --version`

---

### 第2步：下载项目

#### 方式1：使用Git

```powershell
# 克隆项目
git clone <项目地址>
cd ai-trading-system
```

#### 方式2：直接下载

1. 下载项目ZIP文件
2. 解压到目录（如 `C:\Users\你的用户名\ai-trading-system`）
3. 在该目录打开PowerShell

---

### 第3步：安装依赖

```powershell
# 进入项目目录
cd C:\Users\你的用户名\ai-trading-system

# 安装核心依赖
pip install pandas numpy akshare loguru

# 安装桌面自动化依赖
pip install pyautogui psutil pillow

# 或者一键安装全部
pip install -r requirements.txt
```

---

### 第4步：测试系统

#### 测试1：数据获取

```powershell
python tools/data/kline_fetcher.py 600519
```

应该能看到贵州茅台的K线数据。

#### 测试2：策略测试

```powershell
python tools\validation\strategy_tester.py --strategy MA --stocks 600519
```

应该能看到策略生成的交易信号。

#### 测试3：模拟交易

```powershell
python examples/paper_trading_demo.py
```

选择手动模式测试虚拟交易。

---

## 🤖 同花顺自动化（Windows）

### 优势

Windows版同花顺**更成熟稳定**：
- ✅ 功能更完整
- ✅ 更新更及时
- ✅ 用户更多，问题更少
- ✅ 快捷键更稳定

### 配置同花顺路径

#### 找到同花顺安装路径

通常在：
- `C:\Program Files (x86)\同花顺\hexin.exe`
- `C:\同花顺\hexin.exe`
- 或桌面快捷方式右键查看

#### 修改配置

创建 `windows_config.py`：

```python
# Windows 配置
TONGHUASHUN_PATH = r"C:\Program Files (x86)\同花顺\hexin.exe"

# 或者使用你的实际路径
# TONGHUASHUN_PATH = r"C:\同花顺\hexin.exe"
```

#### 修改自动化脚本

编辑 `examples/desktop_trading_demo.py` 或相关示例，找到同花顺路径配置：

```python
# 原来（Linux）
app_path = '/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp'

# 改为（Windows）
app_path = r'C:\Program Files (x86)\同花顺\hexin.exe'
```

或者在脚本中：

```python
import platform

if platform.system() == 'Windows':
    app_path = r'C:\Program Files (x86)\同花顺\hexin.exe'
else:
    app_path = '/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp'
```

---

## 📝 Windows 使用示例

### 1. 获取K线数据

```powershell
# 打开PowerShell
cd C:\Users\你的用户名\ai-trading-system

# 获取数据
python tools\data\kline_fetcher.py 600519
```

### 2. 测试策略

```powershell
# 测试均线策略
python tools\strategy_tester.py --strategy MA --stocks 600519

# 交互式测试
python tools\strategy_tester.py --interactive
```

### 3. 模拟交易

```powershell
# 启动内置模拟交易
python examples\paper_trading_demo.py

# 选择模式：
# 1 - 手动交易
# 2 - 策略自动
```

### 4. 同花顺自动化

```powershell
# 1. 先打开同花顺，登录模拟账户

# 2. 运行自动化脚本
python examples\desktop_trading_demo.py

# 3. 按提示操作
```

---

## 🔧 Windows 特定调整

### 1. 路径处理

**Linux 路径**：
```python
path = '/home/user/data/file.csv'
```

**Windows 路径**（推荐）：
```python
from pathlib import Path

# 跨平台路径
path = Path('data') / 'file.csv'

# 或使用原始字符串
path = r'C:\Users\user\data\file.csv'
```

### 2. 同花顺自动化

修改 `src/api/broker/tonghuashun_desktop.py`：

```python
import platform

class TonghuashunDesktop:
    def __init__(self, config):
        # 自动检测系统
        if platform.system() == 'Windows':
            self.app_path = config.get('app_path', 
                r'C:\Program Files (x86)\同花顺\hexin.exe')
        else:
            self.app_path = config.get('app_path',
                '/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp')
```

### 3. 进程检测

Windows进程检测：

```python
import psutil

def _is_app_running(self):
    """检测同花顺是否运行"""
    if platform.system() == 'Windows':
        process_name = 'hexin.exe'
    else:
        process_name = 'HevoNext.B2CApp'
    
    for proc in psutil.process_iter(['name']):
        try:
            if process_name.lower() in proc.info['name'].lower():
                return True
        except:
            pass
    return False
```

---

## 🎯 Windows 完整示例

### 创建Windows启动脚本

创建 `scripts/scripts/start_windows.bat`：

```batch
@echo off
echo ========================================
echo   AI量化交易系统 - Windows版
echo ========================================
echo.

REM 检查Python
python --version
if errorlevel 1 (
    echo 错误：未找到Python，请先安装
    pause
    exit /b 1
)

echo.
echo 选择功能：
echo 1. 测试数据获取
echo 2. 测试策略
echo 3. 模拟交易
echo 4. 同花顺自动化
echo.

set /p choice=请选择 (1-4): 

if "%choice%"=="1" (
    python tools\data\kline_fetcher.py 600519
) else if "%choice%"=="2" (
    python tools\strategy_tester.py --interactive
) else if "%choice%"=="3" (
    python examples\paper_trading_demo.py
) else if "%choice%"=="4" (
    python examples\desktop_trading_demo.py
) else (
    echo 无效选择
)

pause
```

双击运行 `scripts/scripts/start_windows.bat`！

---

## 📊 Windows vs Linux 对比

| 项目 | Windows | Linux | 说明 |
|------|---------|-------|------|
| **Python** | ✅ | ✅ | 完全一致 |
| **数据获取** | ✅ | ✅ | 完全一致 |
| **策略开发** | ✅ | ✅ | 完全一致 |
| **同花顺** | ✅ 更好 | ✅ | Windows版更稳定 |
| **安装** | pip | apt+pip | Windows更简单 |
| **性能** | 相同 | 相同 | 无差异 |

---

## 💡 Windows 使用建议

### 开发环境推荐

1. **编辑器**：VSCode 或 PyCharm
2. **终端**：Windows Terminal（推荐）或PowerShell
3. **Python版本**：3.10 或 3.11
4. **虚拟环境**：建议使用 `venv`

### 创建虚拟环境（可选）

```powershell
# 创建虚拟环境
python -m venv venv

# 激活（PowerShell）
.\venv\Scripts\Activate.ps1

# 激活（CMD）
venv\Scripts\activate.bat

# 安装依赖
pip install -r requirements.txt
```

### 计划任务（类似cron）

使用Windows任务计划程序：

1. 打开"任务计划程序"
2. 创建基本任务
3. 触发器：选择时间（如每天9:30）
4. 操作：启动程序
   - 程序：`python.exe`
   - 参数：`C:\...\examples\desktop_trading_demo.py`
   - 起始于：`C:\...\ai-trading-system`

---

## 🆘 Windows 常见问题

### Q1: pip不是内部命令

**原因**：Python未添加到PATH

**解决**：
1. 重新安装Python，勾选"Add to PATH"
2. 或手动添加到环境变量

### Q2: 中文路径乱码

**解决**：
```python
# 在脚本开头添加
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
```

### Q3: 同花顺无法启动

**检查**：
- [ ] 路径是否正确？
- [ ] 是否有空格？使用 `r''` 原始字符串
- [ ] 是否有管理员权限？

**测试**：
```python
import os
path = r'C:\Program Files (x86)\同花顺\hexin.exe'
print(os.path.exists(path))  # 应该输出 True
```

### Q4: PyAutoGUI在Windows上的注意事项

**安全暂停**：
- 移动鼠标到屏幕左上角可以中断脚本
- 或按 `Ctrl+C`

**延迟**：
```python
import pyautogui

# Windows上建议增加延迟
pyautogui.PAUSE = 1.0  # 每个操作后等待1秒
```

---

## 📚 推荐工作流程

### Windows 开发流程

1. **VSCode打开项目**
2. **安装Python插件**
3. **创建虚拟环境**
4. **安装依赖**
5. **运行测试**
6. **开发策略**
7. **模拟测试**
8. **实盘交易**

### 推荐目录结构

```
C:\Users\你的用户名\
└── ai-trading-system\
    ├── data\              # 数据目录
    ├── logs\              # 日志目录
    ├── config\            # 配置文件
    ├── examples\          # 示例脚本
    ├── src\               # 源代码
    ├── tools\             # 工具脚本
    ├── venv\              # 虚拟环境（可选）
    └── scripts/start_windows.bat  # Windows启动脚本
```

---

## 🎓 下一步

### 立即开始（Windows）

```powershell
# 1. 安装依赖
pip install pandas numpy akshare loguru pyautogui

# 2. 测试数据
python tools\data\kline_fetcher.py 600519

# 3. 测试策略
python tools\strategy_tester.py --interactive

# 4. 模拟交易
python examples\paper_trading_demo.py
```

### 推荐学习路径

1. **第1天**：安装环境，测试数据获取
2. **第2-3天**：学习策略开发，测试内置策略
3. **第4-7天**：使用内置模拟交易练习
4. **第2周**：开发自己的策略
5. **第3周**：同花顺模拟交易测试
6. **第4周+**：优化策略，准备实盘

---

## 📖 相关文档

- [策略开发快速开始](STRATEGY_QUICKSTART.md)
- [K线数据获取指南](KLINE_DATA_GUIDE.md)
- [模拟交易指南](PAPER_TRADING_GUIDE.md)
- [同花顺模拟交易指南](TONGHUASHUN_SIMULATOR_GUIDE.md)

---

## 💬 总结

### ✅ Windows 完全支持

- **所有核心功能** 都支持Windows
- **同花顺自动化** 在Windows上更稳定
- **安装更简单** 只需要pip
- **性能相同** 无差异

### 🎯 立即开始

**Windows用户推荐流程**：

```
1. 安装Python和依赖
   ↓
2. 测试数据获取和策略
   ↓
3. 使用内置模拟交易练习
   ↓
4. 配置同花顺路径
   ↓
5. 同花顺模拟交易测试
   ↓
6. 策略优化
   ↓
7. 小资金实盘
```

**第一步**：
```powershell
pip install pandas numpy akshare loguru
python tools\data\kline_fetcher.py 600519
```

---

**Windows用户，开始您的量化交易之旅！** 📈🪟

有任何问题，查看文档或根据错误信息调试。祝交易顺利！🚀
