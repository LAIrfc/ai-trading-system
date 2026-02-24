# Git 上传指南 📤

## ✅ 可以上传！

**好消息**：这个项目**完全可以上传到云端代码仓库**！

已经为您准备好了所有必要的文件：
- ✅ `.gitignore` - 排除敏感文件
- ✅ `LICENSE` - MIT开源协议
- ✅ `README.md` - 完整项目说明
- ✅ 完整文档 - 使用指南

---

## 🚀 快速上传（5分钟）

### 方式1：上传到GitHub（推荐）

#### 第1步：创建GitHub仓库

1. 访问 https://github.com/new
2. 填写信息：
   - **Repository name**: `ai-trading-system`
   - **Description**: `AI量化交易系统 - A股策略开发与自动化交易`
   - **Public/Private**: 建议选择 **Private**（私有）
   - **不要勾选** "Initialize this repository with a README"
3. 点击 "Create repository"

#### 第2步：本地初始化Git

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 初始化Git仓库
git init

# 添加所有文件
git add .

# 首次提交
git commit -m "Initial commit: AI量化交易系统

- 完整的策略开发框架
- 实时数据获取（AKShare）
- 3个内置策略（MA/MACD/RSI）
- 模拟交易系统
- 同花顺自动化
- 跨平台支持（Windows/Linux）
- 完整文档"

# 设置主分支
git branch -M main
```

#### 第3步：关联远程仓库

```bash
# 替换成你的GitHub用户名
git remote add origin https://github.com/你的用户名/ai-trading-system.git

# 推送到GitHub
git push -u origin main
```

#### 第4步：验证

访问你的GitHub仓库页面，应该能看到所有文件！

---

### 方式2：上传到Gitee（国内）

#### 第1步：创建Gitee仓库

1. 访问 https://gitee.com/repo/create
2. 填写信息：
   - **仓库名称**: `ai-trading-system`
   - **仓库介绍**: `AI量化交易系统`
   - **是否开源**: 建议选择 **私有**
3. 点击 "创建"

#### 第2步：本地初始化并推送

```bash
cd /home/wangxinghan/codetree/ai-trading-system

# 初始化（如果还没做）
git init
git add .
git commit -m "初始提交：AI量化交易系统"

# 关联Gitee
git remote add origin https://gitee.com/你的用户名/ai-trading-system.git

# 推送
git push -u origin master
```

---

### 方式3：上传到GitLab

```bash
# 类似GitHub，替换为GitLab地址
git remote add origin https://gitlab.com/你的用户名/ai-trading-system.git
git push -u origin main
```

---

## 🔒 安全检查清单

上传前请确认：

### ✅ 已排除的文件（不会上传）

- ✅ 配置文件（`config/*.yaml`）
- ✅ 数据文件（`data/`）
- ✅ 日志文件（`logs/`）
- ✅ 虚拟环境（`venv/`）
- ✅ 个人交易记录（`*.json`）
- ✅ IDE配置（`.vscode/`, `.idea/`）

### ❌ 不要上传的内容

- ❌ 券商账号密码
- ❌ API密钥
- ❌ 个人交易记录
- ❌ 实盘交易数据
- ❌ 个人隐私信息

### ✅ 应该上传的内容

- ✅ 源代码（`src/`）
- ✅ 示例脚本（`examples/`）
- ✅ 工具脚本（`tools/`）
- ✅ 文档（`*.md`）
- ✅ 配置示例（`*.example`）
- ✅ 依赖列表（`requirements.txt`）
- ✅ License（`LICENSE`）

---

## 📋 上传后的操作

### 1. 添加仓库说明

在GitHub/Gitee仓库页面添加：

**简介**：
```
AI量化交易系统 - 支持策略开发、回测、模拟交易和实盘自动化
```

**标签**：
```
quantitative-trading
stock-trading
python
trading-bot
algorithmic-trading
a-shares
```

### 2. 设置仓库可见性

建议设置为 **Private（私有）**，原因：
- 包含交易策略
- 可能有个人配置信息
- 需要时可以邀请协作者

### 3. 启用Issue和Wiki（可选）

- **Issues** - 记录待办事项和问题
- **Wiki** - 额外的文档
- **Projects** - 项目管理

---

## 🔄 日常使用

### 提交更改

```bash
# 查看修改
git status

# 添加修改的文件
git add .

# 提交
git commit -m "描述你的修改"

# 推送到远程
git push
```

### 更新代码

```bash
# 拉取最新代码
git pull
```

### 创建分支

```bash
# 创建新分支（如开发新功能）
git checkout -b feature/new-strategy

# 开发完成后合并
git checkout main
git merge feature/new-strategy
```

---

## 📚 .gitignore 说明

已配置的忽略规则：

```gitignore
# Python缓存
__pycache__/
*.pyc

# 虚拟环境
venv/
env/

# 配置文件（敏感）
config/*.yaml
*.secret

# 数据文件
data/
logs/

# 个人交易记录
*.json
paper_trading_*.json
account_*.json

# IDE
.vscode/
.idea/
```

**作用**：确保敏感信息不会被上传。

---

## 🌟 推荐的README结构

您的README.md已经很完善了，包含：

- ✅ 项目简介
- ✅ 功能特性
- ✅ 快速开始
- ✅ 安装说明
- ✅ 使用指南
- ✅ 文档链接
- ✅ 风险警告
- ✅ 跨平台支持

可以考虑添加：
- 📸 截图或演示GIF
- 🎯 路线图（Roadmap）
- 🤝 贡献指南
- 📊 性能数据

---

## 💡 最佳实践

### 1. 提交信息规范

```bash
# 好的提交信息
git commit -m "feat: 添加RSI策略"
git commit -m "fix: 修复数据获取bug"
git commit -m "docs: 更新Windows使用指南"

# 类型前缀
# feat: 新功能
# fix: 修复
# docs: 文档
# style: 格式
# refactor: 重构
# test: 测试
# chore: 构建/工具
```

### 2. 分支策略

```
main        # 稳定版本
develop     # 开发分支
feature/*   # 功能分支
hotfix/*    # 紧急修复
```

### 3. 版本标签

```bash
# 发布版本
git tag -a v1.0.0 -m "版本1.0.0 - 首个稳定版本"
git push origin v1.0.0
```

---

## 🆘 常见问题

### Q: 不小心上传了敏感文件怎么办？

A: 从Git历史中删除：
```bash
# 删除文件
git rm --cached config/broker_config.yaml

# 提交
git commit -m "remove sensitive file"

# 推送
git push
```

### Q: 如何防止上传大文件？

A: 已在`.gitignore`中配置，数据文件不会上传。

### Q: 公开还是私有？

A: **建议私有**，因为：
- 包含交易策略
- 可能有个人配置
- 需要时可以改为公开

### Q: 多人协作怎么办？

A: 
1. 在GitHub/Gitee添加协作者
2. 使用分支进行开发
3. 通过Pull Request合并代码

### Q: 如何备份？

A: 
1. 推送到多个远程仓库
2. 定期导出代码
3. 使用GitHub自动备份

---

## 🎯 推荐平台对比

| 平台 | 优势 | 适用场景 |
|------|------|----------|
| **GitHub** | 全球最大、生态好 | 开源项目、国际协作 |
| **Gitee** | 国内速度快、支持中文 | 国内团队、私有项目 |
| **GitLab** | 功能强大、可自建 | 企业内部、CI/CD |

---

## 🎓 学习资源

### Git基础

- [Git官方教程](https://git-scm.com/book/zh/v2)
- [GitHub入门](https://docs.github.com/cn/get-started)
- [Gitee帮助](https://gitee.com/help)

### Git可视化工具

- **GitKraken** - 跨平台
- **SourceTree** - Windows/Mac
- **GitHub Desktop** - 简单易用
- **VSCode Git** - 集成在编辑器

---

## ✅ 检查清单

上传前确认：

- [ ] 已运行 `git status` 检查文件
- [ ] 配置文件不在提交列表中
- [ ] 没有个人敏感信息
- [ ] README.md 准备好
- [ ] LICENSE 文件存在
- [ ] .gitignore 配置正确
- [ ] 测试代码能正常运行
- [ ] 文档完整且准确

---

## 🎉 上传完成后

### 1. 添加徽章（可选）

在README.md顶部添加：

```markdown
[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey.svg)]()
```

### 2. 设置GitHub Pages（可选）

用于展示文档。

### 3. 启用Actions（可选）

自动测试和部署。

---

## 📞 获取帮助

- **Git问题** - https://git-scm.com/docs
- **GitHub问题** - https://docs.github.com/
- **Gitee问题** - https://gitee.com/help

---

## 🎊 总结

### ✅ 可以安全上传

- 已配置`.gitignore`排除敏感文件
- 已添加MIT开源协议
- 文档完整，可以分享

### 🚀 立即开始

```bash
# 3条命令搞定！
git init
git add .
git commit -m "Initial commit: AI量化交易系统"
git remote add origin https://github.com/你的用户名/ai-trading-system.git
git push -u origin main
```

### 💡 记住

1. **配置文件不上传** - 在`.gitignore`中
2. **选择私有仓库** - 保护策略和配置
3. **定期备份** - push到远程仓库
4. **写好commit信息** - 方便追溯

---

**开始上传你的量化交易系统吧！** 📤🚀

有问题随时查看Git文档或寻求帮助！
