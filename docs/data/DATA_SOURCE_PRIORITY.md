# 数据源优先级与接口清单

## 📊 概述

本系统集成了**5层数据源**，实现自动切换和容错，确保每次更新都能成功获取有效数据。

## 🎯 设计目标

1. **高可用性**: 任何一个接口失败，自动切换到下一个
2. **数据质量**: 优先使用数据最全、更新最及时的接口
3. **性能优化**: 快速失败，避免长时间等待
4. **灵活扩展**: 易于添加新的数据源

## 📡 5层数据源架构

### 优先级策略

```
第1层: akshare        (最优 - 数据最全，更新及时)
   ↓ 失败
第2层: 东方财富       (次优 - 概念板块最全，但不稳定)
   ↓ 失败
第3层: 新浪财经       (稳定 - 接口可靠，传统行业覆盖好)
   ↓ 失败或数据不足
第4层: baostock      (本地 - 无网络限制，历史数据完整)
   ↓ 失败或数据不足
第5层: 本地数据+关键词 (兜底 - 100%可用)
```

## 📚 数据源详细说明

### 1. akshare (优先级: ⭐⭐⭐⭐⭐)

**安装状态**: ✅ 已安装

**优势**:
- 数据最全面，覆盖概念板块、行业板块、指数成分等
- 更新及时，通常当天就能获取最新数据
- API设计友好，返回DataFrame格式
- 支持市值、PE/PB等基本面数据

**劣势**:
- 依赖东方财富等外部接口，网络不稳定时会失败
- 部分接口有频率限制

**适用场景**:
- 获取概念板块成分股（光伏、机器人、半导体等）
- 获取最新的市场数据
- 获取基本面数据

**使用示例**:
```python
import akshare as ak

# 获取光伏概念板块成分股
df = ak.stock_board_concept_cons_em(symbol='光伏概念')
# 返回: 代码、名称、最新价、市值等
```

**配置**:
```python
'光伏': {
    'akshare': ['光伏概念'],  # 优先使用
    ...
}
```

---

### 2. 东方财富 (优先级: ⭐⭐⭐⭐)

**安装状态**: 无需安装（HTTP API）

**优势**:
- 概念板块分类最细，覆盖新兴赛道
- 支持按市值排序
- 数据更新及时

**劣势**:
- **接口极不稳定**，频繁出现 `Connection aborted` 错误
- 需要处理复杂的参数和返回格式
- 无官方文档，接口可能随时变化

**适用场景**:
- 获取新兴赛道概念板块（光伏、机器人、半导体等）
- 作为akshare的备用方案

**使用示例**:
```python
url = 'http://push2.eastmoney.com/api/qt/clist/get'
params = {
    'fs': 'b:BK1031',  # 光伏概念
    'fid': 'f20',      # 按市值排序
    ...
}
```

**配置**:
```python
'光伏': {
    'akshare': ['光伏概念'],
    'eastmoney': ['BK1031'],  # 备用
    ...
}
```

---

### 3. 新浪财经 (优先级: ⭐⭐⭐⭐⭐)

**安装状态**: 无需安装（HTTP API）

**优势**:
- **接口非常稳定**，很少失败
- 响应速度快
- 支持按市值排序
- 覆盖传统行业分类完整

**劣势**:
- 只有传统行业分类，缺少新兴赛道（光伏、机器人等）
- 不支持概念板块

**适用场景**:
- 获取传统行业板块（有色金属、证券、医药等）
- 作为稳定可靠的备用数据源

**使用示例**:
```python
url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
params = {
    'node': 'new_ysjs',  # 有色金属
    'sort': 'mktcap',    # 按市值排序
    ...
}
```

**配置**:
```python
'有色金属': {
    'sina': ['new_ysjs'],  # 直接使用（稳定）
    ...
}
```

**新浪行业代码清单**:
| 代码 | 名称 | 股票数 |
|------|------|--------|
| new_ysjs | 有色金属 | 72只 |
| new_jrhy | 金融行业 | 51只 |
| new_swzz | 生物制药 | 155只 |
| new_ylqx | 医疗器械 | 31只 |
| new_dzqj | 电子器件 | 152只 |
| new_dzxx | 电子信息 | 247只 |
| new_fjzz | 飞机制造 | 14只 |
| ... | ... | ... |

---

### 4. baostock (优先级: ⭐⭐⭐)

**安装状态**: ✅ 已安装

**优势**:
- **本地库，无网络限制**
- 历史数据完整，支持复权
- 免费开源，无需注册
- 支持指数成分股查询

**劣势**:
- 不提供实时市值数据
- 行业分类较粗糙
- 概念板块支持有限
- 需要登录/登出操作

**适用场景**:
- 获取指数成分股（沪深300、中证500等）
- 获取历史K线数据
- 作为网络接口失败时的备用方案

**使用示例**:
```python
import baostock as bs

bs.login()

# 获取沪深300成分股
rs = bs.query_hs300_stocks(date='2026-03-06')

# 获取行业成分股
rs = bs.query_stock_industry()

bs.logout()
```

**配置**:
```python
'有色金属': {
    'sina': ['new_ysjs'],
    'baostock': ['有色'],  # 备用
    ...
}
```

---

### 5. 本地数据 + 关键词匹配 (优先级: ⭐⭐⭐⭐⭐)

**安装状态**: 内置功能

**优势**:
- **100%可用**，无任何外部依赖
- 响应速度极快
- 支持灵活的关键词匹配

**劣势**:
- 数据可能不是最新
- 依赖本地股票池的质量
- 需要维护关键词列表

**适用场景**:
- 所有网络接口都失败时的兜底方案
- 新兴赛道（光伏、机器人）的补充数据源

**使用示例**:
```python
# 从 stock_pool_all.json 加载
# 按关键词匹配: ['光伏', '太阳能', '隆基', '通威', ...]
# 按市值排序（从 market_fundamental_cache.json）
```

**配置**:
```python
'光伏': {
    'keywords': ['光伏', '太阳能', '隆基', '通威', '阳光', ...],
    ...
}
```

---

## 🔄 自动切换流程示例

### 场景1: 光伏板块（网络接口都失败）

```
【光伏】获取中...
  [1/5] 尝试akshare 光伏概念...
    ⚠️ Connection aborted (失败)
  [2/5] 尝试东方财富 BK1031...
    ⚠️ Connection aborted (失败)
  [3/5] 新浪没有光伏板块 (跳过)
  [4/5] baostock没有光伏行业 (跳过)
  [5/5] 补充本地股票池数据...
    ✅ 本地匹配: 5只
  ✅ 光伏: 5只 (候选5只)
```

### 场景2: 有色金属（新浪稳定可用）

```
【有色金属】获取中...
  [1/5] akshare未配置 (跳过)
  [2/5] 东方财富未配置 (跳过)
  [3/5] 补充新浪数据...
    ✅ 新浪 new_ysjs: 30只
  ✅ 有色金属: 15只 (候选30只)
```

### 场景3: 半导体（多数据源组合）

```
【半导体】获取中...
  [1/5] 尝试akshare 半导体概念...
    ⚠️ Connection aborted (失败)
  [2/5] 尝试东方财富 BK0917...
    ⚠️ Connection aborted (失败)
  [3/5] 补充新浪数据...
    ✅ 新浪 new_dzqj: 30只
    ✅ 新浪 new_dzxx: 30只
  ✅ 半导体: 2只 (候选2只，经过关键词过滤)
```

---

## 📋 7大赛道完整配置

```python
SECTOR_BOARDS = {
    '光伏': {
        'akshare': ['光伏概念'],
        'eastmoney': ['BK1031'],
        'sina': [],
        'baostock': [],
        'keywords': ['光伏', '太阳能', '隆基', '通威', '阳光', ...],
        'target': 15
    },
    '机器人': {
        'akshare': ['机器人概念'],
        'eastmoney': ['BK1090'],
        'sina': [],
        'baostock': [],
        'keywords': ['机器人', '埃斯顿', '汇川', ...],
        'target': 15
    },
    '半导体': {
        'akshare': ['半导体概念', '芯片概念'],
        'eastmoney': ['BK0917'],
        'sina': ['new_dzqj', 'new_dzxx'],
        'baostock': [],
        'keywords': ['半导体', '芯片', '集成', ...],
        'target': 15
    },
    '有色金属': {
        'akshare': [],
        'eastmoney': [],
        'sina': ['new_ysjs'],  # 直接使用（稳定）
        'baostock': ['有色'],
        'keywords': [],
        'target': 15
    },
    '证券': {
        'akshare': ['券商概念'],
        'eastmoney': ['BK0711'],
        'sina': ['new_jrhy'],
        'baostock': ['证券'],
        'keywords': ['证券'],
        'target': 14
    },
    '创新药': {
        'akshare': ['创新药', 'CXO概念'],
        'eastmoney': ['BK1106'],
        'sina': ['new_swzz', 'new_ylqx'],
        'baostock': ['医药'],
        'keywords': ['恒瑞', '药明', '迈瑞', ...],
        'target': 14
    },
    '商业航天': {
        'akshare': ['航天概念'],
        'eastmoney': ['BK0963'],
        'sina': ['new_fjzz'],
        'baostock': ['航空航天'],
        'keywords': ['航天', '卫星', '航空', ...],
        'target': 13
    },
}
```

---

## 🛠️ 其他数据接口

### tushare

**安装状态**: ✅ 已安装

**说明**: 
- 需要注册并获取token
- 免费版有积分限制
- 数据质量高，适合专业用户

**当前使用情况**: 
- 已安装但未在赛道龙头获取中使用
- 可作为未来扩展的数据源

---

## 📊 数据源对比总结

| 数据源 | 稳定性 | 数据全面性 | 更新速度 | 网络依赖 | 推荐场景 |
|--------|--------|------------|----------|----------|----------|
| **akshare** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 是 | 概念板块、新兴赛道 |
| **东方财富** | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 是 | 概念板块备用 |
| **新浪财经** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | 是 | 传统行业、稳定数据源 |
| **baostock** | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | 否 | 指数成分、历史数据 |
| **本地数据** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | 否 | 兜底保障 |

---

## 🎯 使用建议

### 1. 日常更新
```bash
# 默认模式：自动5层数据源切换
python3 tools/data/refresh_stock_pool.py
```

### 2. 网络不稳定时
- 系统会自动切换到新浪、baostock和本地数据
- 无需人工干预

### 3. 添加新赛道
```python
'新赛道': {
    'akshare': ['新赛道概念'],      # 优先
    'eastmoney': ['BK9999'],        # 备用
    'sina': ['new_xxx'],            # 稳定
    'baostock': ['新赛道'],         # 本地
    'keywords': ['关键词1', ...],   # 兜底
    'target': 15
}
```

### 4. 监控数据源状态
观察运行日志，如果某个数据源长期失败：
- 调整优先级顺序
- 增加备用数据源
- 优化关键词配置

---

---

## 🛠️ 实现细节

### 各层获取函数

```python
def fetch_board_stocks_eastmoney(board_code, limit=30, max_retries=2):
    """从东方财富获取板块成分股（带2次重试，失败返回[]触发降级）"""

def fetch_board_stocks_sina(sector_code, limit=30):
    """从新浪财经获取板块成分股（稳定REST API，按市值排序）"""

def fetch_board_stocks_local(keywords, limit=30):
    """从本地股票池按关键词匹配（加载 stock_pool_all.json + market_fundamental_cache.json）"""
```

### 去重机制

```python
# 跨数据源去重（同一代码只保留第一次出现）
unique_stocks = {}
for s in all_stocks:
    if s['code'] not in unique_stocks:
        unique_stocks[s['code']] = s

# 跨赛道去重
seen = set()
for sector in sectors:
    for stock in sector_stocks:
        if stock['code'] not in seen:
            selected.append(stock)
            seen.add(stock['code'])
```

所有数据源统一返回 `market_cap_yi`（市值，单位：亿元）用于排序。

---

## 🔗 相关文件

- `tools/data/refresh_stock_pool.py` - 主脚本
- `mydate/stock_pool.json` - 赛道龙头池
- `mydate/stock_pool_all.json` - 综合股票池
- `mydate/market_fundamental_cache.json` - 市值缓存
