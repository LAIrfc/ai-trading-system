#!/usr/bin/env python3
"""
💼 持仓同步工具（简化版）

用法:
  # 买入
  python tools/portfolio/sync_portfolio.py --buy 002120 --shares 1000 --price 7.05
  
  # 卖出
  python tools/portfolio/sync_portfolio.py --sell 002120 --shares 500
  
  # 清仓
  python tools/portfolio/sync_portfolio.py --sell 002120 --shares all
"""

import sys
import os
import json
import shutil
from datetime import datetime

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORTFOLIO_FILE = os.path.join(base_dir, 'mydate', 'my_portfolio.json')
BACKUP_DIR = os.path.join(base_dir, 'mydate', 'portfolio_backups')


def backup_portfolio():
    """备份持仓文件"""
    if not os.path.exists(PORTFOLIO_FILE):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = os.path.join(BACKUP_DIR, f'my_portfolio_{timestamp}.json')
    shutil.copy2(PORTFOLIO_FILE, backup_file)


def load_portfolio():
    """加载持仓"""
    if not os.path.exists(PORTFOLIO_FILE):
        return {
            'updated': datetime.now().strftime('%Y-%m-%d'),
            'note': '持仓数据',
            'holdings': []
        }
    with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_portfolio(portfolio):
    """保存持仓"""
    portfolio['updated'] = datetime.now().strftime('%Y-%m-%d')
    with open(PORTFOLIO_FILE, 'w', encoding='utf-8') as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)
    print(f"✅ 已更新: {PORTFOLIO_FILE}")


def find_holding(portfolio, code):
    """查找持仓"""
    for h in portfolio['holdings']:
        if h['code'] == code:
            return h
    return None


def get_stock_name(code):
    """获取股票名称"""
    pool_file = os.path.join(base_dir, 'mydate', 'stock_pool_all.json')
    if os.path.exists(pool_file):
        with open(pool_file, 'r', encoding='utf-8') as f:
            pool = json.load(f)
            for stock in pool.get('stocks', []):
                if stock['code'] == code:
                    return stock['name']
    return code


def buy_stock(portfolio, code, shares, price):
    """买入"""
    holding = find_holding(portfolio, code)
    
    if holding:
        # 补仓
        old_shares = holding.get('shares', 0)
        old_cost = holding.get('avg_cost', 0)
        new_total = old_shares * old_cost + shares * price
        new_shares = old_shares + shares
        new_cost = new_total / new_shares
        
        print(f"\n补仓 {code} {holding['name']}")
        print(f"  原: {old_shares:,}股 @ {old_cost:.2f}")
        print(f"  新: {shares:,}股 @ {price:.2f}")
        print(f"  合计: {new_shares:,}股 @ {new_cost:.2f}")
        
        holding['shares'] = new_shares
        holding['avg_cost'] = round(new_cost, 3)
        if 'comment' in holding:
            del holding['comment']
    else:
        # 新建
        name = get_stock_name(code)
        print(f"\n新建持仓 {code} {name}")
        print(f"  {shares:,}股 @ {price:.2f}")
        
        portfolio['holdings'].append({
            'code': code,
            'name': name,
            'avg_cost': price,
            'market_value_ref': 0,
            'shares': shares,
        })


def sell_stock(portfolio, code, shares_to_sell):
    """卖出"""
    holding = find_holding(portfolio, code)
    
    if not holding:
        print(f"❌ 未找到持仓: {code}")
        return False
    
    current_shares = holding.get('shares', 0)
    if current_shares <= 0:
        print(f"❌ {code} 当前持仓为0")
        return False
    
    if isinstance(shares_to_sell, str) and shares_to_sell.lower() == 'all':
        shares_to_sell = current_shares
    else:
        shares_to_sell = int(shares_to_sell)
    
    if shares_to_sell > current_shares:
        print(f"❌ 卖出数量超过持仓")
        return False
    
    new_shares = current_shares - shares_to_sell
    
    print(f"\n卖出 {code} {holding['name']}")
    print(f"  原: {current_shares:,}股")
    print(f"  卖: {shares_to_sell:,}股")
    print(f"  剩: {new_shares:,}股")
    
    holding['shares'] = new_shares
    
    if new_shares == 0:
        today = datetime.now().strftime('%Y-%m-%d')
        holding['comment'] = f"{today} 已清仓"
        print(f"  ✅ 已清仓")
    
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description='持仓同步')
    parser.add_argument('--buy', type=str, help='买入股票代码')
    parser.add_argument('--sell', type=str, help='卖出股票代码')
    parser.add_argument('--shares', help='股数（卖出时可用 all）')
    parser.add_argument('--price', type=float, help='买入价格')
    args = parser.parse_args()
    
    if not args.buy and not args.sell:
        parser.print_help()
        return
    
    backup_portfolio()
    portfolio = load_portfolio()
    
    if args.buy:
        if not args.shares or not args.price:
            print("❌ 买入需要 --shares 和 --price")
            return
        buy_stock(portfolio, args.buy, int(args.shares), args.price)
    elif args.sell:
        if not args.shares:
            print("❌ 卖出需要 --shares")
            return
        if not sell_stock(portfolio, args.sell, args.shares):
            return
    
    save_portfolio(portfolio)
    
    print("\n💡 记得手动编辑 docs\\DAILY_TRACKING.md 记录操作原因")


if __name__ == '__main__':
    main()
