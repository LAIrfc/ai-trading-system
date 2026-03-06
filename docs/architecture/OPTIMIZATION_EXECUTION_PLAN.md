# 项目优化执行计划

> 生成时间：2026-03-06  
> 基于：PROJECT_OPTIMIZATION_REPORT.md  
> 执行策略：分阶段、低风险优先

---

## 🎯 执行策略

### 原则
1. **安全第一**: 先测试，后删除
2. **分阶段执行**: 每个阶段独立，可回滚
3. **保持兼容**: 更新导入路径，保持功能不变
4. **充分测试**: 每个阶段后运行测试

---

## 📋 Phase 1: 安全清理（立即执行）

### 1.1 删除占位文件 ✅

**文件**: `src/data/industry.py`

**原因**: 仅10行占位注释，无实际功能

**执行**:
```bash
rm src/data/industry.py
```

**风险**: ⭐ 无风险（无代码引用）

---

### 1.2 更新 .gitignore ✅

**添加规则**:
```bash
# 添加到 .gitignore
echo "" >> .gitignore
echo "# 缓存和临时文件" >> .gitignore
echo "mycache/**/*.csv" >> .gitignore
echo "mycache/**/*.parquet" >> .gitignore
echo "mydate/temp_*.json" >> .gitignore
echo "mylog/*.log" >> .gitignore
echo "*.pyc" >> .gitignore
echo "__pycache__/" >> .gitignore
```

**风险**: ⭐ 无风险

---

### 1.3 合并文档 ✅

#### 合并 TROUBLESHOOTING_TKINTER.md

```bash
# 1. 合并内容
cat docs/setup/TROUBLESHOOTING_TKINTER.md >> docs/setup/TROUBLESHOOTING.md

# 2. 在TROUBLESHOOTING.md中添加章节标题
# （手动编辑，添加 "## Tkinter 相关问题" 章节）

# 3. 删除原文件
rm docs/setup/TROUBLESHOOTING_TKINTER.md
```

#### 删除 GIT_GUIDE.md

```bash
# Git是通用知识，不需要项目专门文档
rm docs/setup/GIT_GUIDE.md
```

#### 合并 V33 文档

```bash
# 1. 合并内容
cat "docs/strategy/V33_落地与状态.md" >> docs/strategy/V33_DESIGN_SPEC.md

# 2. 在V33_DESIGN_SPEC.md中添加章节
# （手动编辑，添加 "## 落地状态" 章节）

# 3. 删除原文件
rm "docs/strategy/V33_落地与状态.md"
```

**风险**: ⭐ 无风险（仅文档整理）

---

## 📋 Phase 2: 更新导入路径（需要测试）

### 2.1 分析当前使用情况

**兼容层文件被以下文件使用**:

| 兼容层文件 | 被引用的文件 | 数量 |
|-----------|-------------|------|
| `src/data/realtime_data.py` | examples/, tests/, tools/ | 4个 |
| `src/data/market_data.py` | src/core/, run_daily.py | 3个 |
| `src/data/etf_data_fetcher.py` | tests/ | 1个 |
| `src/data/fundamental_fetcher.py` | 无直接引用 | 0个 |

### 2.2 更新导入路径

#### 更新 realtime_data 导入

**文件列表**:
1. `examples/get_kline_demo.py`
2. `examples/paper_trading_demo.py`
3. `examples/my_strategy_template.py`
4. `tests/test_cross_platform.py`
5. `tools/data/kline_fetcher.py`

**修改**:
```python
# 修改前
from src.data.realtime_data import RealtimeDataFetcher, MarketDataManager

# 修改后
from src.data import RealtimeDataFetcher, MarketDataManager
# 或者
from src.data.fetchers.realtime_data import RealtimeDataFetcher, MarketDataManager
```

#### 更新 market_data 导入

**文件列表**:
1. `src/core/trade_journal.py`
2. `src/core/signal_engine.py`
3. `run_daily.py`

**修改**:
```python
# 修改前
from src.data.market_data import MarketData, ETF_POOL

# 修改后
from src.data import MarketData, ETF_POOL
# 或者
from src.data.fetchers.market_data import MarketData, ETF_POOL
```

#### 更新 etf_data_fetcher 导入

**文件列表**:
1. `tests/test_dual_momentum_quick.py`

**修改**:
```python
# 修改前
from src.data.etf_data_fetcher import ETFDataFetcher

# 修改后
from src.data import ETFDataFetcher
# 或者
from src.data.fetchers.etf_data_fetcher import ETFDataFetcher
```

### 2.3 测试验证

```bash
# 运行所有测试
python -m pytest tests/

# 运行示例
python examples/get_kline_demo.py
python examples/paper_trading_demo.py

# 运行主程序
python run_daily.py --help
```

### 2.4 删除兼容层文件

**仅在所有测试通过后执行**:
```bash
rm src/data/etf_data_fetcher.py
rm src/data/fundamental_fetcher.py
rm src/data/realtime_data.py
rm src/data/market_data.py
```

**风险**: ⭐⭐ 中风险（需要更新多个文件）

---

## 📋 Phase 3: 代码重构（本周）

### 3.1 重构 refresh_stock_pool.py

**目标**: 使用统一的 `FundamentalFetcher` 而不是直接调用API

**修改**:
```python
# tools/data/refresh_stock_pool.py

# 修改前
def fetch_realtime_info(codes: list, session=None) -> dict:
    """直接调用东方财富API"""
    if session is None:
        session = _eastmoney_session()
    
    results = {}
    for code in codes:
        url = 'http://push2.eastmoney.com/api/qt/stock/get'
        params = {'secid': f'{market}.{code}', ...}
        resp = session.get(url, params=params, timeout=8)
        ...
    return results

# 修改后
from src.data.fetchers import FundamentalFetcher

def fetch_realtime_info(codes: list) -> dict:
    """使用统一的FundamentalFetcher"""
    fetcher = FundamentalFetcher()
    results = {}
    
    for code in codes:
        try:
            # 使用统一接口（自动fallback）
            data = fetcher.get_pe_pb_data(code)
            if data:
                results[code] = {
                    'name': data.get('name', ''),
                    'pe_ttm': data.get('pe_ttm'),
                    'market_cap_yi': data.get('market_cap_yi'),
                    'is_st': data.get('is_st', False),
                }
        except Exception as e:
            logger.debug(f"获取{code}失败: {e}")
            continue
    
    return results
```

**测试**:
```bash
python tools/data/refresh_stock_pool.py --test
```

**风险**: ⭐⭐⭐ 中高风险（修改核心工具）

---

### 3.2 迁移 validation 测试

```bash
# 创建测试目录
mkdir -p tests/validation

# 迁移文件
mv tools/validation/*.py tests/validation/

# 删除空目录
rmdir tools/validation/

# 更新导入路径（如果需要）
# 在tests/validation/中的文件可能需要更新sys.path
```

**风险**: ⭐⭐ 中风险（需要更新导入）

---

## 📋 Phase 4: 添加工具（本周）

### 4.1 添加缓存清理工具

**创建文件**: `tools/data/cleanup_cache.py`

```python
#!/usr/bin/env python3
"""
缓存清理工具

功能:
  1. 清理过期的缓存文件（默认7天）
  2. 清理临时文件
  3. 压缩旧日志

用法:
  python tools/data/cleanup_cache.py                # 清理7天前的缓存
  python tools/data/cleanup_cache.py --days 30      # 清理30天前的缓存
  python tools/data/cleanup_cache.py --dry-run      # 预览将要删除的文件
"""

import os
import sys
import time
import argparse
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# 缓存目录
CACHE_DIRS = [
    'mycache/fundamental',
    'mycache/etf_kline',
    'mycache/stock_kline',
    'mycache/market_data',
]

# 临时文件目录
TEMP_DIRS = [
    'mydate',
]

# 日志目录
LOG_DIR = 'mylog'


def cleanup_cache(cache_dir: str, days: int, dry_run: bool = False):
    """清理过期缓存"""
    cutoff = time.time() - (days * 86400)
    deleted_count = 0
    deleted_size = 0
    
    print(f"\n📁 清理目录: {cache_dir}")
    print(f"   保留时间: {days}天")
    
    for file in Path(cache_dir).rglob('*'):
        if not file.is_file():
            continue
        
        if file.stat().st_mtime < cutoff:
            size = file.stat().st_size
            if dry_run:
                print(f"   [预览] 将删除: {file} ({size/1024:.1f}KB)")
            else:
                file.unlink()
                print(f"   ✅ 已删除: {file} ({size/1024:.1f}KB)")
            
            deleted_count += 1
            deleted_size += size
    
    print(f"   总计: {deleted_count}个文件, {deleted_size/1024/1024:.2f}MB")
    return deleted_count, deleted_size


def cleanup_temp_files(temp_dir: str, dry_run: bool = False):
    """清理临时文件"""
    deleted_count = 0
    deleted_size = 0
    
    print(f"\n📁 清理临时文件: {temp_dir}")
    
    for file in Path(temp_dir).glob('temp_*.json'):
        size = file.stat().st_size
        if dry_run:
            print(f"   [预览] 将删除: {file} ({size/1024:.1f}KB)")
        else:
            file.unlink()
            print(f"   ✅ 已删除: {file} ({size/1024:.1f}KB)")
        
        deleted_count += 1
        deleted_size += size
    
    if deleted_count > 0:
        print(f"   总计: {deleted_count}个文件, {deleted_size/1024:.2f}KB")
    else:
        print(f"   无临时文件需要清理")
    
    return deleted_count, deleted_size


def compress_logs(log_dir: str, days: int, dry_run: bool = False):
    """压缩旧日志"""
    import gzip
    import shutil
    
    cutoff = time.time() - (days * 86400)
    compressed_count = 0
    
    print(f"\n📁 压缩日志: {log_dir}")
    print(f"   压缩时间: {days}天前的日志")
    
    for file in Path(log_dir).glob('*.log'):
        if file.stat().st_mtime < cutoff:
            gz_file = file.with_suffix('.log.gz')
            if gz_file.exists():
                continue
            
            if dry_run:
                print(f"   [预览] 将压缩: {file}")
            else:
                with open(file, 'rb') as f_in:
                    with gzip.open(gz_file, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                file.unlink()
                print(f"   ✅ 已压缩: {file} -> {gz_file}")
            
            compressed_count += 1
    
    if compressed_count > 0:
        print(f"   总计: {compressed_count}个日志文件")
    else:
        print(f"   无日志需要压缩")
    
    return compressed_count


def main():
    parser = argparse.ArgumentParser(description='缓存清理工具')
    parser.add_argument('--days', type=int, default=7, help='清理N天前的缓存（默认7天）')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不实际删除')
    parser.add_argument('--no-cache', action='store_true', help='不清理缓存')
    parser.add_argument('--no-temp', action='store_true', help='不清理临时文件')
    parser.add_argument('--no-log', action='store_true', help='不压缩日志')
    args = parser.parse_args()
    
    print(f"{'='*60}")
    print(f"  🧹 缓存清理工具")
    print(f"{'='*60}")
    
    if args.dry_run:
        print("  ⚠️ 预览模式：不会实际删除文件")
    
    total_files = 0
    total_size = 0
    
    # 清理缓存
    if not args.no_cache:
        for cache_dir in CACHE_DIRS:
            if os.path.exists(cache_dir):
                count, size = cleanup_cache(cache_dir, args.days, args.dry_run)
                total_files += count
                total_size += size
    
    # 清理临时文件
    if not args.no_temp:
        for temp_dir in TEMP_DIRS:
            if os.path.exists(temp_dir):
                count, size = cleanup_temp_files(temp_dir, args.dry_run)
                total_files += count
                total_size += size
    
    # 压缩日志
    if not args.no_log:
        if os.path.exists(LOG_DIR):
            compress_logs(LOG_DIR, args.days, args.dry_run)
    
    print(f"\n{'='*60}")
    print(f"  ✅ 清理完成")
    print(f"  📊 总计: {total_files}个文件, {total_size/1024/1024:.2f}MB")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
```

**测试**:
```bash
# 预览模式
python tools/data/cleanup_cache.py --dry-run

# 实际清理
python tools/data/cleanup_cache.py
```

**风险**: ⭐ 无风险（新增工具）

---

## 📋 Phase 5: 补充测试（下周）

### 5.1 添加策略单元测试

**创建文件**: `tests/unit/test_strategies.py`

```python
"""策略单元测试"""
import pytest
import pandas as pd
import numpy as np
from src.strategies import (
    MACrossStrategy,
    MACDCrossStrategy,
    RSISignalStrategy,
    BollingerBandStrategy,
)

def create_sample_data(days=100):
    """创建测试数据"""
    dates = pd.date_range('2023-01-01', periods=days)
    close = 10 + np.cumsum(np.random.randn(days) * 0.1)
    close = np.maximum(close, 1)  # 确保价格>0
    
    df = pd.DataFrame({
        'date': dates,
        'open': close * (1 + np.random.randn(days) * 0.01),
        'high': close * (1 + np.abs(np.random.randn(days)) * 0.02),
        'low': close * (1 - np.abs(np.random.randn(days)) * 0.02),
        'close': close,
        'volume': np.random.randint(1000000, 10000000, days),
    })
    return df

class TestMACrossStrategy:
    """MA均线策略测试"""
    
    def test_golden_cross(self):
        """测试金叉信号"""
        df = create_sample_data(100)
        # 构造金叉场景
        df.loc[df.index[-10:], 'close'] = df['close'].iloc[-11] * 1.1
        
        strategy = MACrossStrategy(short_window=5, long_window=20)
        signal = strategy.analyze(df)
        
        assert signal.action == 'BUY'
        assert signal.confidence > 0.5
    
    def test_death_cross(self):
        """测试死叉信号"""
        df = create_sample_data(100)
        # 构造死叉场景
        df.loc[df.index[-10:], 'close'] = df['close'].iloc[-11] * 0.9
        
        strategy = MACrossStrategy(short_window=5, long_window=20)
        signal = strategy.analyze(df)
        
        assert signal.action == 'SELL'
        assert signal.confidence > 0.5

# ... 更多测试
```

### 5.2 添加数据Provider测试

**创建文件**: `tests/unit/test_data_provider.py`

```python
"""数据Provider单元测试"""
import pytest
from unittest.mock import Mock, patch
from src.data.provider import UnifiedDataProvider, get_default_kline_provider

class TestUnifiedDataProvider:
    """UnifiedDataProvider测试"""
    
    def test_get_kline_success(self):
        """测试成功获取K线数据"""
        provider = get_default_kline_provider()
        df = provider.get_kline('600000', start_date='2023-01-01', end_date='2023-01-31')
        
        assert df is not None
        assert len(df) > 0
        assert all(col in df.columns for col in ['date', 'open', 'high', 'low', 'close', 'volume'])
    
    def test_get_kline_fallback(self):
        """测试fallback机制"""
        # Mock第一个adapter失败，第二个成功
        ...
    
    def test_circuit_breaker(self):
        """测试熔断机制"""
        ...

# ... 更多测试
```

**风险**: ⭐ 无风险（新增测试）

---

## 📊 执行进度跟踪

### Phase 1: 安全清理 ✅
- [ ] 删除占位文件
- [ ] 更新 .gitignore
- [ ] 合并文档

### Phase 2: 更新导入 ⏳
- [ ] 更新 realtime_data 导入（5个文件）
- [ ] 更新 market_data 导入（3个文件）
- [ ] 更新 etf_data_fetcher 导入（1个文件）
- [ ] 运行测试验证
- [ ] 删除兼容层文件

### Phase 3: 代码重构 ⏳
- [ ] 重构 refresh_stock_pool.py
- [ ] 迁移 validation 测试

### Phase 4: 添加工具 ⏳
- [ ] 添加缓存清理工具
- [ ] 测试缓存清理工具

### Phase 5: 补充测试 ⏳
- [ ] 添加策略单元测试
- [ ] 添加数据Provider测试
- [ ] 添加Adapter测试

---

## 🎯 预期收益

### 代码质量
- ✅ 删除5个冗余文件
- ✅ 合并3个重复文档
- ✅ 统一数据获取接口
- ✅ 补充核心单元测试

### 可维护性
- ✅ 目录结构更清晰
- ✅ 测试统一管理
- ✅ 缓存自动清理
- ✅ 日志自动轮转

### 代码行数
- **减少**: ~50行冗余代码
- **新增**: ~200行测试代码
- **重构**: ~100行数据获取代码

---

## ⚠️ 注意事项

1. **每个Phase独立执行**: 完成一个Phase后再开始下一个
2. **充分测试**: 每个Phase完成后运行完整测试
3. **保持备份**: 重要修改前先commit
4. **逐步推进**: 不要一次性执行所有优化

---

**最后更新**: 2026-03-06  
**执行状态**: Phase 1 待执行
