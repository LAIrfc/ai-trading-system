"""
AI量化交易系统主入口
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime
import yaml
from loguru import logger

# 添加项目根目录到Python路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def setup_logging(config: dict):
    """
    配置日志系统
    
    Args:
        config: 日志配置
    """
    log_config = config.get('logging', {})
    log_level = log_config.get('level', 'INFO')
    log_dir = PROJECT_ROOT / log_config.get('log_dir', 'logs')
    log_dir.mkdir(exist_ok=True)
    
    # 移除默认的logger
    logger.remove()
    
    # 添加控制台输出
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
    )
    
    # 添加文件输出
    logger.add(
        log_dir / "trading_{time:YYYY-MM-DD}.log",
        rotation="00:00",  # 每天午夜轮转
        retention="30 days",  # 保留30天
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    )
    
    logger.info("=" * 50)
    logger.info("AI量化交易系统启动")
    logger.info(f"日志级别: {log_level}")
    logger.info("=" * 50)


def load_config(config_path: str) -> dict:
    """
    加载配置文件
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        配置字典
    """
    config_file = PROJECT_ROOT / config_path
    
    if not config_file.exists():
        logger.error(f"配置文件不存在: {config_file}")
        sys.exit(1)
    
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    logger.info(f"配置文件加载成功: {config_file}")
    return config


def run_backtest(args):
    """
    运行回测
    
    Args:
        args: 命令行参数
    """
    logger.info("=" * 50)
    logger.info("回测模式")
    logger.info(f"策略: {args.strategy}")
    logger.info(f"开始日期: {args.start}")
    logger.info(f"结束日期: {args.end}")
    logger.info("=" * 50)
    
    # 加载配置
    trading_config = load_config('config/trading_config.yaml')
    risk_config = load_config('config/risk_config.yaml')
    
    # TODO: 实现回测逻辑
    logger.warning("⚠️ 回测功能正在开发中...")
    
    # 示例：加载数据
    from src.data.collectors.market_data_collector import DataCollectorFactory
    
    data_source = trading_config['data']['source']
    collector = DataCollectorFactory.create_collector(data_source, trading_config)
    
    # 获取股票列表
    stock_list = collector.get_stock_list()
    logger.info(f"股票池数量: {len(stock_list)}")
    
    # 示例：获取沪深300成分股的历史数据
    # TODO: 实现完整的回测流程
    
    logger.info("回测完成")


def run_live_trading(args):
    """
    运行实盘交易
    
    Args:
        args: 命令行参数
    """
    logger.critical("=" * 50)
    logger.critical("⚠️ 实盘交易模式 - 请谨慎操作！")
    logger.critical(f"策略: {args.strategy}")
    logger.critical("=" * 50)
    
    # 二次确认
    if not args.confirm:
        logger.error("实盘交易需要 --confirm 参数确认")
        logger.error("示例: python src/main.py --mode live --strategy your_strategy --confirm")
        sys.exit(1)
    
    # 加载配置
    trading_config = load_config('config/trading_config.yaml')
    risk_config = load_config('config/risk_config.yaml')
    
    # 检查是否为模拟模式
    mode = trading_config['account'].get('mode', 'simulation')
    if mode != 'live':
        logger.warning(f"当前配置为 {mode} 模式，不会进行真实交易")
    
    # TODO: 实现实盘交易逻辑
    logger.warning("⚠️ 实盘交易功能正在开发中...")
    
    # 实盘交易主循环
    # 1. 连接券商API
    # 2. 获取账户信息
    # 3. 启动策略
    # 4. 风控监控
    # 5. 信号执行
    # 6. 持仓管理
    
    logger.info("实盘交易系统已启动")


def run_data_download(args):
    """
    下载历史数据
    
    Args:
        args: 命令行参数
    """
    logger.info("=" * 50)
    logger.info("数据下载模式")
    logger.info(f"开始日期: {args.start}")
    logger.info(f"结束日期: {args.end}")
    logger.info("=" * 50)
    
    # 加载配置
    trading_config = load_config('config/trading_config.yaml')
    
    from src.data.collectors.market_data_collector import DataCollectorFactory
    
    data_source = trading_config['data']['source']
    collector = DataCollectorFactory.create_collector(data_source, trading_config)
    
    # 获取股票列表
    logger.info("获取股票列表...")
    stock_list = collector.get_stock_list()
    logger.info(f"共{len(stock_list)}只股票")
    
    # TODO: 批量下载数据并保存
    logger.warning("⚠️ 数据下载功能正在开发中...")
    
    logger.info("数据下载完成")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='AI量化交易系统')
    
    # 运行模式
    parser.add_argument('--mode', type=str, required=True,
                       choices=['backtest', 'live', 'download'],
                       help='运行模式: backtest(回测) / live(实盘) / download(下载数据)')
    
    # 策略参数
    parser.add_argument('--strategy', type=str,
                       help='策略名称')
    
    # 日期参数
    parser.add_argument('--start', type=str,
                       help='开始日期 YYYYMMDD')
    
    parser.add_argument('--end', type=str,
                       help='结束日期 YYYYMMDD')
    
    # 实盘确认
    parser.add_argument('--confirm', action='store_true',
                       help='确认执行实盘交易')
    
    # 配置文件
    parser.add_argument('--config', type=str,
                       default='config/trading_config.yaml',
                       help='配置文件路径')
    
    args = parser.parse_args()
    
    # 加载配置并设置日志
    try:
        config = load_config(args.config)
        setup_logging(config)
    except Exception as e:
        print(f"配置加载失败: {e}")
        sys.exit(1)
    
    # 根据模式执行
    try:
        if args.mode == 'backtest':
            if not args.strategy or not args.start or not args.end:
                logger.error("回测模式需要 --strategy, --start, --end 参数")
                sys.exit(1)
            run_backtest(args)
            
        elif args.mode == 'live':
            if not args.strategy:
                logger.error("实盘模式需要 --strategy 参数")
                sys.exit(1)
            run_live_trading(args)
            
        elif args.mode == 'download':
            if not args.start or not args.end:
                logger.error("下载模式需要 --start, --end 参数")
                sys.exit(1)
            run_data_download(args)
            
    except KeyboardInterrupt:
        logger.warning("用户中断程序")
        sys.exit(0)
        
    except Exception as e:
        logger.exception(f"程序运行出错: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
