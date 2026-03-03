"""
跨平台配置
自动检测操作系统并使用对应配置
"""

import platform
from pathlib import Path


class PlatformConfig:
    """平台配置"""
    
    def __init__(self):
        self.system = platform.system()  # 'Windows', 'Linux', 'Darwin'
        self.is_windows = self.system == 'Windows'
        self.is_linux = self.system == 'Linux'
        self.is_mac = self.system == 'Darwin'
    
    def get_tonghuashun_path(self):
        """获取同花顺路径"""
        if self.is_windows:
            # Windows常见路径
            possible_paths = [
                r'C:\Program Files (x86)\同花顺\hexin.exe',
                r'C:\同花顺\hexin.exe',
                r'D:\Program Files (x86)\同花顺\hexin.exe',
                r'D:\同花顺\hexin.exe',
            ]
            
            # 检查哪个存在
            for path in possible_paths:
                if Path(path).exists():
                    return path
            
            # 默认返回第一个
            return possible_paths[0]
        
        elif self.is_linux:
            return '/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp'
        
        elif self.is_mac:
            # Mac用户需要自己配置
            return '/Applications/同花顺.app/Contents/MacOS/同花顺'
        
        else:
            return None
    
    def get_tonghuashun_process_name(self):
        """获取同花顺进程名"""
        if self.is_windows:
            return 'hexin.exe'
        elif self.is_linux:
            return 'HevoNext.B2CApp'
        elif self.is_mac:
            return '同花顺'
        else:
            return None
    
    def get_data_dir(self):
        """获取数据目录（优先使用 mydate，备选 data）"""
        base_dir = Path.cwd()
        mydate_dir = base_dir / 'mydate'
        data_dir = base_dir / 'data'
        
        # 优先使用 mydate 目录
        if mydate_dir.exists():
            return mydate_dir
        elif data_dir.exists():
            return data_dir
        else:
            # 都不存在时，返回 mydate（会创建）
            return mydate_dir
    
    def get_log_dir(self):
        """获取日志目录（优先使用 mylog，备选 logs）"""
        base_dir = Path.cwd()
        mylog_dir = base_dir / 'mylog'
        logs_dir = base_dir / 'logs'
        
        # 优先使用 mylog 目录
        if mylog_dir.exists():
            return mylog_dir
        elif logs_dir.exists():
            return logs_dir
        else:
            # 都不存在时，返回 mylog（会创建）
            return mylog_dir
    
    def print_info(self):
        """打印平台信息"""
        print(f"\n{'='*60}")
        print(f"  平台信息")
        print(f"{'='*60}")
        print(f"操作系统: {self.system}")
        print(f"Python版本: {platform.python_version()}")
        print(f"同花顺路径: {self.get_tonghuashun_path()}")
        print(f"同花顺进程: {self.get_tonghuashun_process_name()}")
        print(f"数据目录: {self.get_data_dir()}")
        print(f"日志目录: {self.get_log_dir()}")
        print(f"{'='*60}\n")


# 全局配置实例
platform_config = PlatformConfig()


if __name__ == "__main__":
    # 测试
    platform_config.print_info()
