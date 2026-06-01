"""
规则引擎 v2
功能：根据配置的红灯/黄灯规则，对输入数据进行自动判定
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from excel_engine import load_config


def get_fund_rules(fund_code):
    """获取指定基金的规则配置"""
    config = load_config()
    rules = config['funds'][fund_code].copy()
    rules.setdefault('drawdown_vs_benchmark_threshold', -15)
    rules.setdefault('concentration_threshold', 60)
    rules.setdefault('defense_asset_min', 10)
    rules.setdefault('underperform_threshold', -5)
    return rules


def check_red_flags(data, rules):
    """检查红灯规则"""
    red_flags = []

    # 1. 核心基金经理离任
    key_person = rules['manager_key_person']
    if data.get('李晓星是否在任') == '否':
        red_flags.append({
            "rule": "核心基金经理离任",
            "detail": f"{key_person}已不在基金经理名单中",
            "action": "30个交易日内清仓"
        })

    # 2. 三人团队12个月内离任>=2人
    team_leave_count = data.get('三人团队12个月内离任人数', 0)
    if isinstance(team_leave_count, (int, float)) and team_leave_count >= 2:
        red_flags.append({
            "rule": "团队核心离任过多",
            "detail": f"三人团队12个月内已离任{int(team_leave_count)}人",
            "action": "30个交易日内清仓"
        })

    # 3. 规模超上限
    current_scale = data.get('当前规模(亿)')
    if isinstance(current_scale, (int, float)) and current_scale > rules['scale_upper_limit']:
        red_flags.append({
            "rule": "规模超上限",
            "detail": f"当前规模{current_scale}亿，超过{rules['scale_upper_limit']}亿上限",
            "action": "不再新增，观察一季度后决定是否减仓"
        })

    # 4. 规模6个月内翻倍
    scale_doubled = data.get('规模6个月内翻倍')
    if scale_doubled == '是':
        current_scale = data.get('当前规模(亿)', 0)
        prev_scale = current_scale / 2 if current_scale else 0
        red_flags.append({
            "rule": "规模6个月内翻倍",
            "detail": f"6个月前{prev_scale}亿 → 现在{current_scale}亿",
            "action": "不再新增，密切关注业绩变化"
        })

    return red_flags


def check_yellow_flags(data, rules):
    """检查黄灯规则"""
    yellow_flags = []

    # 1. 前十大集中度过高
    concentration = data.get('前十大集中度(%)')
    threshold = rules['concentration_threshold']
    if isinstance(concentration, (int, float)) and concentration > threshold:
        yellow_flags.append({
            "rule": "前十大集中度过高",
            "detail": f"集中度{concentration}%，超过{threshold}%",
            "action": "关注，结合持仓分析"
        })

    # 2. 防御资产占比不足
    defense = data.get('防御资产占比(%)')
    defense_min = rules['defense_asset_min']
    if isinstance(defense, (int, float)) and defense < defense_min:
        yellow_flags.append({
            "rule": "防御资产占比不足",
            "detail": f"防御资产占比{defense}%，低于{defense_min}%下限",
            "action": "关注风险敞口"
        })

    # 3. 近6个月跑输基准超5%
    excess = data.get('近6个月相对基准(%)')
    underperform = rules['underperform_threshold']
    if isinstance(excess, (int, float)) and excess < underperform:
        yellow_flags.append({
            "rule": "近6个月跑输基准超5%",
            "detail": f"近6个月相对基准{excess}%",
            "action": "关注，连续2季度则升级为红灯"
        })

    return yellow_flags


def run_judgment(data):
    """
    执行完整判定流程
    输入：data dict，包含基金各项指标
    输出：dict，包含 status, red_flags, yellow_flags, summary, suggested_action
    """
    fund_code = data.get('基金代码', '180031')
    rules = get_fund_rules(fund_code)

    red_flags = check_red_flags(data, rules)
    yellow_flags = check_yellow_flags(data, rules)

    red_count = len(red_flags)
    yellow_count = len(yellow_flags)

    # 判定状态
    if red_count > 0:
        status = "红灯"
        suggested_action = "30个交易日内清仓"
    elif yellow_count >= 3:
        status = "黄灯(高)"
        suggested_action = "暂停定投，减仓20%"
    elif yellow_count >= 2:
        status = "黄灯"
        suggested_action = "暂停定投，密切观察"
    elif yellow_count == 1:
        status = "黄灯(低)"
        suggested_action = "继续持有，加强关注"
    else:
        status = "绿灯"
        suggested_action = "维持持仓，正常定投"

    # 生成摘要
    summary_lines = []
    for flag in red_flags:
        summary_lines.append(f"[红] {flag['rule']}: {flag['detail']}")
    for flag in yellow_flags:
        summary_lines.append(f"[黄] {flag['rule']}: {flag['detail']}")
    if not summary_lines:
        summary_lines.append("[绿] 所有指标正常")

    return {
        "status": status,
        "red_count": red_count,
        "yellow_count": yellow_count,
        "red_flags": red_flags,
        "yellow_flags": yellow_flags,
        "suggested_action": suggested_action,
        "summary": "\n".join(summary_lines)
    }