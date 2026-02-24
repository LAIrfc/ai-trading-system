# Windows 用户必读 🪟

## 🎉 完全支持Windows！

好消息！本系统**完全支持Windows**，而且有些功能在Windows上更好用！

---

## ⚡ 超快速开始（3分钟）

### 第1步：双击启动

1. 下载项目到本地（如 `C:\ai-trading-system`）
2. **双击** `start_windows.bat`
3. 选择 `6` 安装依赖
4. 选择 `1` 测试系统

### 第2步：测试功能

在菜单中选择：
- `2` - 获取K线数据（输入 600519 测试）
- `3` - 测试策略（选择策略和股票）
- `4` - 模拟交易（无风险练习）

### 第3步：查看文档

选择 `7` 查看所有文档列表。

---

## 📚 Windows 专属文档

**必读**：[WINDOWS_GUIDE.md](WINDOWS_GUIDE.md)

包含：
- ✅ 详细安装步骤
- ✅ 同花顺配置方法
- ✅ Windows特定问题解决
- ✅ 完整使用示例
- ✅ 批处理脚本说明

---

## 🔥 Windows 优势

### 1. 同花顺更成熟

Windows版同花顺：
- ✅ 功能更完整
- ✅ 更新更及时  
- ✅ 快捷键更稳定
- ✅ 用户基数大，问题少

### 2. 安装更简单

```powershell
# 只需要pip，不需要apt
pip install pandas numpy akshare loguru
```

### 3. 图形界面更友好

- 双击 `.bat` 文件即可运行
- 不需要记命令
- 菜单式操作

---

## 🎯 推荐使用流程

### 新手流程（Windows）

```
1. 双击 start_windows.bat
   ↓
2. 选择 6 - 安装依赖
   ↓
3. 选择 2 - 测试获取数据
   ↓
4. 选择 3 - 测试策略
   ↓
5. 选择 4 - 模拟交易练习
   ↓
6. 阅读 WINDOWS_GUIDE.md
   ↓
7. 配置同花顺路径
   ↓
8. 选择 5 - 同花顺模拟交易
   ↓
9. 持续优化策略
```

---

## 💻 命令行使用（可选）

如果你喜欢命令行：

```powershell
# 打开 PowerShell 或 CMD
cd C:\ai-trading-system

# 获取K线数据
python tools\kline_fetcher.py 600519

# 测试策略
python tools\strategy_tester.py --interactive

# 模拟交易
python examples\paper_trading_demo.py

# 同花顺自动化
python examples\tonghuashun_simulator.py
```

---

## 📖 文档导航

| 文档 | 用途 | 必读程度 |
|------|------|----------|
| **[WINDOWS_GUIDE.md](WINDOWS_GUIDE.md)** | Windows完整指南 | ⭐⭐⭐⭐⭐ |
| [README.md](README.md) | 项目总览 | ⭐⭐⭐⭐ |
| [STRATEGY_QUICKSTART.md](STRATEGY_QUICKSTART.md) | 策略开发 | ⭐⭐⭐⭐ |
| [KLINE_DATA_GUIDE.md](KLINE_DATA_GUIDE.md) | K线数据 | ⭐⭐⭐ |
| [PAPER_TRADING_GUIDE.md](PAPER_TRADING_GUIDE.md) | 模拟交易 | ⭐⭐⭐ |
| [QUICK_REFERENCE.md](QUICK_REFERENCE.md) | 快速参考 | ⭐⭐⭐ |

---

## 🔧 常见问题

### Q: Python在哪下载？

A: https://www.python.org/downloads/
   安装时**勾选** "Add Python to PATH"

### Q: 同花顺在哪找？

A: 
1. 桌面快捷方式右键 → 属性 → 查看目标路径
2. 通常在 `C:\Program Files (x86)\同花顺\hexin.exe`

### Q: 中文显示乱码？

A: 
1. PowerShell：`chcp 65001`
2. 或使用 Windows Terminal

### Q: pip找不到？

A: 重新安装Python，确保勾选"Add to PATH"

---

## 🎓 学习路径

### 第1天
- 双击 `start_windows.bat`
- 安装依赖
- 测试数据获取
- 阅读 WINDOWS_GUIDE.md

### 第2-3天
- 测试3个内置策略
- 理解策略逻辑
- 阅读 STRATEGY_QUICKSTART.md

### 第4-7天
- 使用内置模拟交易
- 手动买卖练习
- 阅读 PAPER_TRADING_GUIDE.md

### 第2周
- 创建自己的策略
- 策略自动测试

### 第3周
- 配置同花顺
- 同花顺模拟交易
- 阅读 TONGHUASHUN_SIMULATOR_GUIDE.md

### 第4周+
- 策略优化
- 持续回测
- 准备实盘

---

## 🚀 立即开始

### 方式1：图形界面（推荐）

1. **双击** `start_windows.bat`
2. 跟随菜单提示
3. 搞定！

### 方式2：命令行

```powershell
# PowerShell
cd C:\你的路径\ai-trading-system

# 安装
pip install pandas numpy akshare loguru

# 测试
python tools\kline_fetcher.py 600519
```

---

## 💡 Windows 专属提示

1. **使用 Windows Terminal** - 比CMD更好用
2. **创建桌面快捷方式** - 右键拖动 start_windows.bat
3. **设置计划任务** - 定时运行策略（类似Linux cron）
4. **使用VSCode** - 最好的Python编辑器
5. **启用虚拟环境** - `python -m venv venv`

---

## 📞 获取帮助

遇到问题？

1. **查看文档** - WINDOWS_GUIDE.md
2. **测试系统** - 菜单选项1
3. **查看平台信息** - `python src\config\platform_config.py`
4. **查看错误** - 仔细阅读错误信息

---

## 🎉 总结

### Windows 完全支持！

✅ **所有功能** 都能用  
✅ **同花顺** 更稳定  
✅ **安装** 更简单  
✅ **文档** 更详细  

### 第一步

**双击** `start_windows.bat` 开始！

---

**Windows用户，开始您的量化交易之旅！** 📈🪟

详细说明请看：[WINDOWS_GUIDE.md](WINDOWS_GUIDE.md)
