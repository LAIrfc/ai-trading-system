"""
分行业 PE/PB 估值阈值配置

不同行业的合理估值区间差异很大：
- 银行/地产/周期股：PE 低（5~15），应优先用 PB
- 科技/医药/消费：PE 高（30~80），应主要用 PE
- 固定阈值会导致：银行永远低估（PE=5 < 任何分位数），科技永远高估

核心改进：
1. 按行业大类设置不同的 low_quantile/high_quantile
2. 标记每个行业应偏重 PE 还是 PB（或二者并重）
3. 提供行业分类映射（申万二级 → 行业大类）
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class SectorValuationProfile:
    """行业估值特征"""
    pe_low_quantile: float
    pe_high_quantile: float
    pb_low_quantile: float
    pb_high_quantile: float
    prefer: str  # 'pe', 'pb', 'both'

    @property
    def pe_thresholds(self) -> Tuple[float, float]:
        return self.pe_low_quantile, self.pe_high_quantile

    @property
    def pb_thresholds(self) -> Tuple[float, float]:
        return self.pb_low_quantile, self.pb_high_quantile


DEFAULT_PROFILE = SectorValuationProfile(
    pe_low_quantile=0.20, pe_high_quantile=0.80,
    pb_low_quantile=0.20, pb_high_quantile=0.80,
    prefer='both',
)

SECTOR_PROFILES: Dict[str, SectorValuationProfile] = {
    # 金融——PE 波动大，PB 更稳定
    '银行': SectorValuationProfile(0.15, 0.85, 0.10, 0.70, 'pb'),
    '保险': SectorValuationProfile(0.15, 0.85, 0.15, 0.75, 'pb'),
    '证券': SectorValuationProfile(0.20, 0.80, 0.15, 0.75, 'pb'),
    '资本市场服务': SectorValuationProfile(0.20, 0.80, 0.15, 0.75, 'pb'),
    '货币金融服务': SectorValuationProfile(0.15, 0.85, 0.10, 0.70, 'pb'),
    '其他金融业': SectorValuationProfile(0.15, 0.85, 0.15, 0.75, 'pb'),

    # 周期——PB 底部更有参考价值
    '有色金属': SectorValuationProfile(0.25, 0.75, 0.15, 0.75, 'pb'),
    '煤炭': SectorValuationProfile(0.25, 0.75, 0.15, 0.75, 'pb'),
    '钢铁': SectorValuationProfile(0.25, 0.75, 0.10, 0.70, 'pb'),
    '石油': SectorValuationProfile(0.25, 0.75, 0.15, 0.75, 'pb'),
    '化工': SectorValuationProfile(0.20, 0.80, 0.15, 0.75, 'both'),
    '建材': SectorValuationProfile(0.20, 0.80, 0.15, 0.75, 'both'),

    # 地产/基建——PB 为主
    '房地产': SectorValuationProfile(0.30, 0.70, 0.10, 0.65, 'pb'),
    '建筑': SectorValuationProfile(0.20, 0.80, 0.15, 0.75, 'pb'),

    # 消费——PE 更稳定
    '食品饮料': SectorValuationProfile(0.15, 0.85, 0.20, 0.80, 'pe'),
    '医药': SectorValuationProfile(0.15, 0.85, 0.25, 0.80, 'pe'),
    '家电': SectorValuationProfile(0.20, 0.80, 0.20, 0.80, 'both'),
    '纺织': SectorValuationProfile(0.20, 0.80, 0.20, 0.80, 'both'),
    '农业': SectorValuationProfile(0.20, 0.80, 0.20, 0.80, 'both'),

    # 科技/成长——PE 估值中枢高，放宽阈值
    '半导体': SectorValuationProfile(0.15, 0.90, 0.25, 0.85, 'pe'),
    '计算机': SectorValuationProfile(0.15, 0.85, 0.25, 0.85, 'pe'),
    '电子': SectorValuationProfile(0.15, 0.85, 0.25, 0.85, 'pe'),
    '通信': SectorValuationProfile(0.20, 0.85, 0.25, 0.80, 'pe'),
    '软件': SectorValuationProfile(0.15, 0.85, 0.25, 0.85, 'pe'),
    '互联网': SectorValuationProfile(0.15, 0.85, 0.25, 0.85, 'pe'),

    # 高端制造
    '汽车': SectorValuationProfile(0.20, 0.80, 0.20, 0.80, 'both'),
    '电气设备': SectorValuationProfile(0.20, 0.80, 0.20, 0.80, 'both'),
    '机械': SectorValuationProfile(0.20, 0.80, 0.20, 0.80, 'both'),
    '军工': SectorValuationProfile(0.15, 0.85, 0.25, 0.85, 'pe'),
    '航空航天': SectorValuationProfile(0.15, 0.85, 0.25, 0.85, 'pe'),

    # 公用事业——PB 低估值稳定
    '电力': SectorValuationProfile(0.20, 0.80, 0.15, 0.75, 'pb'),
    '水务': SectorValuationProfile(0.20, 0.80, 0.15, 0.75, 'pb'),
    '燃气': SectorValuationProfile(0.20, 0.80, 0.15, 0.75, 'pb'),
    '交通运输': SectorValuationProfile(0.20, 0.80, 0.15, 0.75, 'both'),
    '港口': SectorValuationProfile(0.20, 0.80, 0.15, 0.75, 'pb'),
}

_SECTOR_CODE_MAPPING: Dict[str, str] = {
    'J66货币金融服务': '货币金融服务',
    'J67资本市场服务': '资本市场服务',
    'J68保险业': '保险',
    'J69其他金融业': '其他金融业',
    'K70房地产业': '房地产',
    'C39计算机、通信和其他电子设备制造业': '电子',
    'I65软件和信息技术服务业': '软件',
    'I64互联网和相关服务': '互联网',
    'I63电信、广播电视和卫星传输服务': '通信',
    'C27医药制造业': '医药',
    'C36汽车制造业': '汽车',
    'C38电气机械和器材制造业': '电气设备',
    'C35专用设备制造业': '机械',
    'C34通用设备制造业': '机械',
    'C37铁路、船舶、航空航天和其他运输设备制造业': '航空航天',
    'C26化学原料和化学制品制造业': '化工',
    'C28化学纤维制造业': '化工',
    'C30非金属矿物制品业': '建材',
    'C31黑色金属冶炼和压延加工业': '钢铁',
    'C32有色金属冶炼和压延加工业': '有色金属',
    'C15酒、饮料和精制茶制造业': '食品饮料',
    'C14食品制造业': '食品饮料',
    'C13农副食品加工业': '食品饮料',
    'D44电力、热力生产和供应业': '电力',
    'D45燃气生产和供应业': '燃气',
    'D46水的生产和供应业': '水务',
    'B06煤炭开采和洗选业': '煤炭',
    'B07石油和天然气开采业': '石油',
    'B09有色金属矿采选业': '有色金属',
    'B11开采专业及辅助性活动': '石油',
    'E48土木工程建筑业': '建筑',
    'E49建筑安装业': '建筑',
    'G55水上运输业': '交通运输',
    'G56航空运输业': '交通运输',
    'G53铁路运输业': '交通运输',
    'G54道路运输业': '交通运输',
    'G58多式联运和运输代理业': '交通运输',
    'G60邮政业': '交通运输',
    'A01农业': '农业',
    'A03畜牧业': '农业',
    'C18纺织服装、服饰业': '纺织',
    'C17纺织业': '纺织',
    'C19皮革、毛皮、羽毛及其制品和制鞋业': '纺织',
    'Q84卫生': '医药',
    'N77生态保护和环境治理业': '电力',
    'C29橡胶和塑料制品业': '化工',
    'C25石油、煤炭及其他燃料加工业': '化工',
    'F51批发业': '食品饮料',
    'F52零售业': '食品饮料',
    'C40仪器仪表制造业': '机械',
    'C33金属制品业': '钢铁',
    'C42废弃资源综合利用业': '化工',
    'C22造纸和纸制品业': '建材',
    'C21家具制造业': '家电',
    'L72商务服务业': '食品饮料',
    'M73研究和试验发展': '机械',
    'R87广播、电视、电影和录音制作业': '互联网',
    'M74专业技术服务业': '机械',
    'H61住宿业': '食品饮料',
    'R86新闻和出版业': '互联网',
    'C24文教、工美、体育和娱乐用品制造业': '家电',
    'C41其他制造业': '机械',
    'L71租赁业': '食品饮料',
    'P83教育': '互联网',
    'M75科技推广和应用服务业': '软件',
    'R88文化艺术业': '互联网',
    '半导体': '半导体',
    '有色金属': '有色金属',
    '证券': '证券',
    '创新药': '医药',
    '商业航天': '航空航天',
}


def map_sector_code_to_category(sector_code: str) -> str:
    """将股票池中的行业代码映射为行业大类名。"""
    if sector_code in _SECTOR_CODE_MAPPING:
        return _SECTOR_CODE_MAPPING[sector_code]
    for key_part, cat in _SECTOR_CODE_MAPPING.items():
        if key_part in sector_code or sector_code in key_part:
            return cat
    return ''


def get_profile(sector_code: str) -> SectorValuationProfile:
    """根据行业代码获取估值特征，未匹配时返回默认值。"""
    category = map_sector_code_to_category(sector_code)
    return SECTOR_PROFILES.get(category, DEFAULT_PROFILE)


def get_pe_thresholds(sector_code: str) -> Tuple[float, float]:
    """返回 (low_quantile, high_quantile) for PE."""
    return get_profile(sector_code).pe_thresholds


def get_pb_thresholds(sector_code: str) -> Tuple[float, float]:
    """返回 (low_quantile, high_quantile) for PB."""
    return get_profile(sector_code).pb_thresholds


def get_preferred_indicator(sector_code: str) -> str:
    """返回 'pe', 'pb', 'both'。"""
    return get_profile(sector_code).prefer
