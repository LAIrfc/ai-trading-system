#!/usr/bin/env python3
"""
因子衰减自动检测工具

监控因子IC的时序变化，自动检测衰减并预警
"""

import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))


def detect_factor_decay(ic_history_file='results/rolling_ic_monitor.json', 
                       decay_threshold=-0.3, 
                       alert_threshold=-0.5):
    """
    检测因子衰减
    
    Args:
        ic_history_file: 滚动IC历史文件
        decay_threshold: 衰减警告阈值（-30%）
        alert_threshold: 衰减严重阈值（-50%）
    
    Returns:
        dict: 检测结果
    """
    if not os.path.exists(ic_history_file):
        print(f"⚠️ IC历史文件不存在: {ic_history_file}")
        print("   请先运行: python3 tools/analysis/rolling_ic_monitor.py")
        return None
    
    # 加载IC历史
    with open(ic_history_file, 'r') as f:
        ic_data = json.load(f)
    
    print("=" * 80)
    print("因子衰减自动检测")
    print("=" * 80)
    
    print(f"\n📊 IC统计（来自: {ic_history_file}）")
    print(f"   数据时间: {ic_data.get('date', 'unknown')}")
    
    ic_stats = ic_data.get('ic_stats', {})
    
    if not ic_stats:
        print("⚠️ 无IC统计数据")
        return None
    
    # 检测规则
    alerts = []
    warnings = []
    healthy = []
    
    print(f"\n" + "=" * 80)
    print("🔍 因子健康度检测")
    print("=" * 80)
    
    for factor, stats in ic_stats.items():
        avg_ic = stats.get('avg_ic', 0)
        ir = stats.get('ir', 0)
        latest_ic = stats.get('latest_ic', 0)
        
        # 检测逻辑
        status = "✅ 健康"
        level = "healthy"
        reasons = []
        
        # 规则1: 平均IC < 0.05（机构标准）
        if avg_ic < 0.05:
            reasons.append(f"平均IC过低({avg_ic:.3f})")
            if avg_ic < 0:
                status = "🚨 严重"
                level = "alert"
            else:
                status = "⚠️ 警告"
                level = "warning"
        
        # 规则2: IR < 0.5
        if ir < 0.5:
            reasons.append(f"IR过低({ir:.3f})")
            if status == "✅ 健康":
                status = "⚠️ 警告"
                level = "warning"
        
        # 规则3: 最新IC显著低于平均IC
        if latest_ic < avg_ic * 0.5:
            reasons.append(f"最新IC衰减({latest_ic:.3f} vs {avg_ic:.3f})")
            if status == "✅ 健康":
                status = "⚠️ 警告"
                level = "warning"
        
        # 规则4: 最新IC为负且绝对值>0.1
        if latest_ic < -0.1:
            reasons.append(f"最新IC强负值({latest_ic:.3f})")
            status = "🚨 严重"
            level = "alert"
        
        # 输出
        print(f"\n{factor}:")
        print(f"   状态: {status}")
        print(f"   平均IC: {avg_ic:.3f}")
        print(f"   IR: {ir:.3f}")
        print(f"   最新IC: {latest_ic:.3f}")
        
        if reasons:
            print(f"   原因: {', '.join(reasons)}")
        
        # 分类
        if level == "alert":
            alerts.append({
                'factor': factor,
                'avg_ic': avg_ic,
                'ir': ir,
                'latest_ic': latest_ic,
                'reasons': reasons
            })
        elif level == "warning":
            warnings.append({
                'factor': factor,
                'avg_ic': avg_ic,
                'ir': ir,
                'latest_ic': latest_ic,
                'reasons': reasons
            })
        else:
            healthy.append(factor)
    
    # 汇总建议
    print(f"\n" + "=" * 80)
    print("💡 优化建议")
    print("=" * 80)
    
    if alerts:
        print(f"\n🚨 严重问题（{len(alerts)}个）:")
        for alert in alerts:
            print(f"   - {alert['factor']}: {', '.join(alert['reasons'])}")
            print(f"     建议: 考虑移除或大幅降低权重")
    
    if warnings:
        print(f"\n⚠️ 需要关注（{len(warnings)}个）:")
        for warning in warnings:
            print(f"   - {warning['factor']}: {', '.join(warning['reasons'])}")
            print(f"     建议: 降低权重或优化计算方法")
    
    if healthy:
        print(f"\n✅ 健康因子（{len(healthy)}个）:")
        for factor in healthy:
            print(f"   - {factor}")
    
    # 保存检测结果
    result_file = 'results/factor_decay_detection.json'
    
    detection_result = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'alerts': alerts,
        'warnings': warnings,
        'healthy': healthy
    }
    
    with open(result_file, 'w') as f:
        json.dump(detection_result, f, indent=2)
    
    print(f"\n✅ 检测结果已保存: {result_file}")
    print("=" * 80)
    
    return detection_result


if __name__ == '__main__':
    detect_factor_decay()
