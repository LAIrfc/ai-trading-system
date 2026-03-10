"""
策略文档管理系统
实现策略的版本管理、性能追踪和文档自动生成
"""

import json
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from loguru import logger


@dataclass
class StrategyVersion:
    """策略版本信息"""
    version: str
    create_time: str
    author: str
    description: str
    parameters: Dict
    changes: List[str]
    backtest_result: Optional[Dict] = None
    status: str = "draft"  # draft / testing / production / deprecated


@dataclass
class StrategyPerformance:
    """策略性能指标"""
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_holding_days: float
    start_date: str
    end_date: str
    last_update: str


class StrategyDocument:
    """策略文档管理器"""
    
    def __init__(self, strategy_name: str, doc_dir: str = "docs/strategies"):
        """
        初始化策略文档管理器
        
        Args:
            strategy_name: 策略名称
            doc_dir: 文档目录
        """
        self.strategy_name = strategy_name
        self.doc_dir = Path(doc_dir)
        self.doc_dir.mkdir(parents=True, exist_ok=True)
        
        self.strategy_file = self.doc_dir / f"{strategy_name}.yaml"
        self.versions_dir = self.doc_dir / strategy_name / "versions"
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        
        self.metadata = self._load_metadata()
        
    def _load_metadata(self) -> Dict:
        """加载策略元数据"""
        if self.strategy_file.exists():
            with open(self.strategy_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        else:
            return self._create_default_metadata()
    
    def _create_default_metadata(self) -> Dict:
        """创建默认元数据"""
        return {
            'name': self.strategy_name,
            'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'description': '',
            'category': '',
            'tags': [],
            'current_version': None,
            'versions': [],
            'performance_history': [],
            'risk_metrics': {},
            'notes': [],
        }
    
    def save_metadata(self):
        """保存元数据"""
        with open(self.strategy_file, 'w', encoding='utf-8') as f:
            yaml.dump(self.metadata, f, allow_unicode=True, indent=2)
        logger.info(f"策略文档已保存: {self.strategy_file}")
    
    def create_version(self, version: StrategyVersion):
        """
        创建新版本
        
        Args:
            version: 版本信息
        """
        # 保存版本详细信息
        version_file = self.versions_dir / f"v{version.version}.json"
        with open(version_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(version), f, ensure_ascii=False, indent=2)
        
        # 更新元数据
        self.metadata['versions'].append({
            'version': version.version,
            'create_time': version.create_time,
            'status': version.status,
            'description': version.description,
        })
        
        # 如果是生产版本，更新当前版本
        if version.status == 'production':
            self.metadata['current_version'] = version.version
        
        self.save_metadata()
        logger.info(f"策略版本已创建: v{version.version}")
    
    def update_version_status(self, version: str, status: str):
        """
        更新版本状态
        
        Args:
            version: 版本号
            status: 新状态
        """
        for v in self.metadata['versions']:
            if v['version'] == version:
                v['status'] = status
                break
        
        # 如果更新为生产版本
        if status == 'production':
            self.metadata['current_version'] = version
        
        self.save_metadata()
        logger.info(f"版本状态已更新: v{version} -> {status}")
    
    def add_performance_record(self, performance: StrategyPerformance):
        """
        添加性能记录
        
        Args:
            performance: 性能指标
        """
        perf_dict = asdict(performance)
        self.metadata['performance_history'].append(perf_dict)
        
        # 更新当前风险指标
        self.metadata['risk_metrics'] = {
            'sharpe_ratio': performance.sharpe_ratio,
            'max_drawdown': performance.max_drawdown,
            'win_rate': performance.win_rate,
            'last_update': performance.last_update,
        }
        
        self.save_metadata()
        logger.info(f"性能记录已添加: {performance.start_date} ~ {performance.end_date}")
    
    def add_note(self, note: str, category: str = "general"):
        """
        添加笔记
        
        Args:
            note: 笔记内容
            category: 笔记分类
        """
        note_entry = {
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'category': category,
            'content': note,
        }
        
        self.metadata['notes'].append(note_entry)
        self.save_metadata()
        logger.info(f"笔记已添加: [{category}] {note[:50]}...")
    
    def get_version(self, version: str) -> Optional[StrategyVersion]:
        """
        获取版本信息
        
        Args:
            version: 版本号
            
        Returns:
            版本信息或None
        """
        version_file = self.versions_dir / f"v{version}.json"
        
        if not version_file.exists():
            logger.warning(f"版本不存在: v{version}")
            return None
        
        with open(version_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return StrategyVersion(**data)
    
    def get_current_version(self) -> Optional[StrategyVersion]:
        """获取当前生产版本"""
        current = self.metadata.get('current_version')
        if current:
            return self.get_version(current)
        return None
    
    def list_versions(self) -> List[Dict]:
        """列出所有版本"""
        return self.metadata.get('versions', [])
    
    def get_performance_history(self) -> List[StrategyPerformance]:
        """获取性能历史"""
        history = []
        for perf_dict in self.metadata.get('performance_history', []):
            history.append(StrategyPerformance(**perf_dict))
        return history
    
    def generate_markdown_report(self) -> str:
        """
        生成Markdown格式的策略报告
        
        Returns:
            Markdown文本
        """
        md = []
        md.append(f"# 策略文档：{self.strategy_name}\n")
        
        # 基本信息
        md.append("## 基本信息\n")
        md.append(f"- **创建时间**: {self.metadata.get('create_time')}")
        md.append(f"- **描述**: {self.metadata.get('description', '暂无')}")
        md.append(f"- **分类**: {self.metadata.get('category', '未分类')}")
        md.append(f"- **标签**: {', '.join(self.metadata.get('tags', []))}")
        md.append(f"- **当前版本**: v{self.metadata.get('current_version', 'N/A')}\n")
        
        # 版本历史
        md.append("## 版本历史\n")
        md.append("| 版本 | 创建时间 | 状态 | 说明 |")
        md.append("|------|----------|------|------|")
        
        for v in reversed(self.metadata.get('versions', [])):
            md.append(f"| v{v['version']} | {v['create_time']} | {v['status']} | {v['description']} |")
        
        md.append("")
        
        # 性能指标
        md.append("## 性能表现\n")
        
        perf_history = self.get_performance_history()
        if perf_history:
            latest = perf_history[-1]
            md.append("### 最新表现\n")
            md.append(f"- **时间区间**: {latest.start_date} ~ {latest.end_date}")
            md.append(f"- **总收益率**: {latest.total_return:.2%}")
            md.append(f"- **年化收益率**: {latest.annual_return:.2%}")
            md.append(f"- **夏普比率**: {latest.sharpe_ratio:.2f}")
            md.append(f"- **最大回撤**: {latest.max_drawdown:.2%}")
            md.append(f"- **胜率**: {latest.win_rate:.2%}")
            md.append(f"- **盈亏比**: {latest.profit_factor:.2f}")
            md.append(f"- **交易次数**: {latest.total_trades}")
            md.append(f"- **平均持仓天数**: {latest.avg_holding_days:.1f}\n")
            
            # 历史趋势
            md.append("### 历史趋势\n")
            md.append("| 时间区间 | 总收益 | 夏普 | 最大回撤 | 胜率 |")
            md.append("|----------|--------|------|----------|------|")
            
            for perf in perf_history:
                md.append(
                    f"| {perf.start_date}~{perf.end_date} | "
                    f"{perf.total_return:.2%} | "
                    f"{perf.sharpe_ratio:.2f} | "
                    f"{perf.max_drawdown:.2%} | "
                    f"{perf.win_rate:.2%} |"
                )
            
            md.append("")
        else:
            md.append("暂无性能数据\n")
        
        # 风险指标
        md.append("## 风险指标\n")
        risk = self.metadata.get('risk_metrics', {})
        if risk:
            md.append(f"- **夏普比率**: {risk.get('sharpe_ratio', 'N/A')}")
            md.append(f"- **最大回撤**: {risk.get('max_drawdown', 'N/A')}")
            md.append(f"- **胜率**: {risk.get('win_rate', 'N/A')}")
            md.append(f"- **最后更新**: {risk.get('last_update', 'N/A')}\n")
        else:
            md.append("暂无风险指标数据\n")
        
        # 笔记
        md.append("## 开发笔记\n")
        notes = self.metadata.get('notes', [])
        if notes:
            for note in reversed(notes[-10:]):  # 只显示最近10条
                md.append(f"### {note['time']} [{note['category']}]\n")
                md.append(f"{note['content']}\n")
        else:
            md.append("暂无笔记\n")
        
        return '\n'.join(md)
    
    def export_report(self, output_file: Optional[str] = None):
        """
        导出策略报告
        
        Args:
            output_file: 输出文件路径，默认为策略名.md
        """
        if not output_file:
            output_file = self.doc_dir / f"{self.strategy_name}_report.md"
        
        report = self.generate_markdown_report()
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        logger.info(f"策略报告已导出: {output_file}")


# 使用示例
if __name__ == '__main__':
    # 创建策略文档
    doc = StrategyDocument("ai_multi_factor")
    
    # 更新基本信息
    doc.metadata['description'] = "基于AI的多因子选股策略"
    doc.metadata['category'] = "量化选股"
    doc.metadata['tags'] = ['AI', '多因子', '中性策略']
    
    # 创建版本
    version = StrategyVersion(
        version="1.0.0",
        create_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        author="研发团队",
        description="初始版本，包含基础因子",
        parameters={
            'max_positions': 10,
            'rebalance_frequency': 'daily',
            'factors': ['momentum', 'value', 'quality']
        },
        changes=[
            "实现基础框架",
            "集成动量、价值、质量因子",
            "添加风控模块"
        ],
        status="testing"
    )
    
    doc.create_version(version)
    
    # 添加性能记录
    performance = StrategyPerformance(
        total_return=0.25,
        annual_return=0.30,
        sharpe_ratio=1.8,
        max_drawdown=0.12,
        win_rate=0.55,
        profit_factor=2.1,
        total_trades=120,
        avg_holding_days=5.5,
        start_date="2023-01-01",
        end_date="2023-12-31",
        last_update=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    
    doc.add_performance_record(performance)
    
    # 添加笔记
    doc.add_note("回测表现良好，准备上线测试", "milestone")
    doc.add_note("需要优化因子权重，当前权重过于平均", "optimization")
    
    # 导出报告
    doc.export_report()
    
    print("策略文档创建完成！")
