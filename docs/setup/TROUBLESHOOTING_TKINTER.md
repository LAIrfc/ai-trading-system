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
