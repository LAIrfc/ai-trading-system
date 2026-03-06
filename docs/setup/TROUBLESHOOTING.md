# 故障排除指南 🔧

## 问题：tkinter警告导致程序退出

### 症状

运行程序时看到：
```
NOTE: You must install tkinter on Linux to use MouseInfo. 
Run the following: sudo apt-get install python3-tk python3-dev
```

然后程序退出。

### 原因

`pyautogui` 在Linux上依赖 `tkinter`。虽然显示的是NOTE（提示），但实际会导致程序无法继续运行。

### ✅ 解决方案

#### 方法1: 一键安装（推荐）

```bash
cd /home/wangxinghan/codetree/ai-trading-system
./scripts/install_tkinter.sh
```

#### 方法2: 手动安装

```bash
sudo apt-get install python3-tk python3-dev -y
```

### 验证修复

安装完成后，运行测试：

```bash
python3 tests/simple_test.py
```

应该看到：
```
✅ pyautogui imported
✅ 屏幕大小: (1920, 1080)
✅ psutil imported
✅ loguru imported
✅ pyyaml imported
✅ 同花顺已安装
✅ TonghuashunDesktop imported
✅ Broker实例创建成功
✅ 所有测试通过！
```

## 完整安装流程

如果遇到任何问题，按顺序执行：

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 1. 安装系统依赖
sudo apt-get install python3-tk python3-dev python3-pip -y

# 2. 安装Python包
pip3 install --user pyautogui psutil pillow loguru pyyaml

# 3. 测试
python3 tests/simple_test.py

# 4. 运行程序
python3 examples/desktop_trading_demo.py
```

## 其他常见问题

### Q1: 找不到模块

**错误**: `ModuleNotFoundError: No module named 'xxx'`

**解决**:
```bash
pip3 install --user xxx
```

### Q2: 同花顺启动失败

**检查路径**:
```bash
ls -l /opt/apps/cn.com.10jqka/files/HevoNext.B2CApp
```

**手动启动测试**:
```bash
/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp
```

### Q3: 权限问题

**给脚本添加执行权限**:
```bash
chmod +x scripts/*.sh
chmod +x *.sh
```

### Q4: pip命令不存在

**安装pip**:
```bash
sudo apt-get install python3-pip -y
```

## 系统要求

- **操作系统**: Ubuntu 18.04+ / Linux
- **Python**: 3.8+
- **同花顺**: 已安装在 `/opt/apps/cn.com.10jqka/files/`
- **系统包**: python3-tk, python3-dev, python3-pip

## 测试清单

安装完成后，检查以下项目：

- [ ] tkinter已安装: `python3 -c "import tkinter; print('OK')"`
- [ ] pyautogui已安装: `python3 -c "import pyautogui; print('OK')"`
- [ ] 同花顺已安装: `ls /opt/apps/cn.com.10jqka/files/HevoNext.B2CApp`
- [ ] 简单测试通过: `python3 tests/simple_test.py`
- [ ] 演示程序运行: `python3 examples/desktop_trading_demo.py`

## 获取帮助

如果问题仍未解决：

1. 查看日志文件: `logs/`
2. 运行诊断: `python3 tests/simple_test.py`
3. 查看详细错误: 添加 `2>&1` 到命令
4. 检查Python版本: `python3 --version`

## 快速修复命令

```bash
# 一键修复所有问题
cd /home/wangxinghan/codetree/ai-trading-system

sudo apt-get install python3-tk python3-dev python3-pip -y
pip3 install --user pyautogui psutil pillow loguru pyyaml
python3 tests/simple_test.py
```

如果看到 "✅ 所有测试通过"，就可以使用了！

---

**需要更多帮助？** 查看其他文档：
- [SIMPLE_START.md](SIMPLE_START.md) - 最简单的开始方式
- [DESKTOP_TRADING_GUIDE.md](DESKTOP_TRADING_GUIDE.md) - 桌面交易指南
- [docs/DESKTOP_TRADING_GUIDE.md](docs/DESKTOP_TRADING_GUIDE.md) - 详细指南

---

## Tkinter 相关问题

# Tkinter 故障排除指南 🔧

> 如果您遇到 `pyautogui` 需要 `tkinter` 的错误，请按照本指南解决。

## 问题诊断

**错误信息**：`ModuleNotFoundError: No module named '_tkinter'` 或 `pyautogui需要tkinter才能在Linux上运行`

**原因**：`pyautogui` 依赖 `tkinter`，但 Linux 系统默认可能未安装。

## ✅ 三步解决

### 第1步：安装tkinter（需要sudo）

```bash
sudo apt-get install python3-tk python3-dev -y
```

**说明**: 这会要求输入您的密码，这是正常的系统包安装过程。

### 第2步：验证安装

```bash
cd /home/wangxinghan/codetree/ai-trading-system
python3 tests/simple_test.py
```

**期望输出**:
```
测试开始...
✅ pyautogui imported, version: 0.9.54
✅ 屏幕大小: (1920, 1080)
✅ psutil imported
✅ loguru imported
✅ pyyaml imported
✅ 同花顺已安装
✅ TonghuashunDesktop imported
✅ Broker实例创建成功
同花顺状态: ⚪ 未运行

============================================================
✅ 所有测试通过！系统可以正常使用
============================================================
```

### 第3步：运行演示程序

```bash
python3 examples/desktop_trading_demo.py
```

## 演示程序功能

该程序会：

1. **启动同花顺** - 自动启动 `/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp`
2. **自动登录** - 使用您保存的账号密码
3. **演示交易** - 展示买入/卖出操作（模拟）
4. **查询持仓** - 显示账户信息

## 使用提示

### 确保同花顺已配置

- ✅ 同花顺已安装在 `/opt/apps/cn.com.10jqka/files/`
- ✅ 账号已保存（勾选"记住密码"）
- ✅ 可以手动启动并直接登录

### 交互方式

程序会在关键步骤暂停，等待您确认：

```
[INFO] 正在启动同花顺...
[INFO] 请确保同花顺已启动并登录
按Enter继续...
```

按 `Enter` 键继续。

## 一键命令（复制粘贴）

```bash
# 安装依赖
sudo apt-get install python3-tk python3-dev -y

# 测试系统
cd /home/wangxinghan/codetree/ai-trading-system
python3 tests/simple_test.py

# 运行演示
python3 examples/desktop_trading_demo.py
```

## 故障排除

遇到问题？查看 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

**准备好了吗？**

现在在终端运行：

```bash
sudo apt-get install python3-tk python3-dev -y
```

然后继续第2步！
