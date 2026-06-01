"""
规则判定引擎
负责：根据季度检查数据，自动判定红灯/黄灯/绿灯
"""

import json
import os
from datetime import datetime


def load_config():
    """加载基金配置"""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'fund_config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_fund_rules(fund_code=None):
    """获取指定基金的规则参数"""
    config = load_config()
    if fund_code is None:
        fund_code = config['active_fund']
    return config['funds'][fund_code]


# ============ 红灯规则（一票否决） ============

def check_red_flags(data, rules):
    """
    检查红灯条件，任何一条触发即为红灯。
    
    参数：
        data: dict，季度检查数据
        rules: dict，基金规则参数
    
    返回：
        list of dict，每个触发的红灯 {"rule": 规则名, "detail": 具体情况}
    """
    red_flags = []
    
    # 1. 核心基金经理离任
    if data.get('李晓星是否在任') == '否':
        red_flags.append({
            "rule": "核心基金经理离任",
            "detail": f"{rules['manager_key_person']}已不在基金经理名单中",
            "action": "30个交易日内清仓"
        })
    
    # 2. 三人团队12个月内离任>=2人
    team_departure = data.get('三人团队12个月内离任人数', 0)
    if isinstance(team_departure, (int, float)) and team_departure >= 2:
        red_flags.append({
            "rule": "投研团队大面积离职",
            "detail": f"12个月内离任{int(team_departure)}人",
            "action": "30个交易日内清仓"
        })
    
    # 3. 基金规模超上限
    scale = data.get('当前规模(亿)', 0)
    if isinstance(scale, (int, float)) and scale > rules['scale_upper_limit']:
        red_flags.append({
            "rule": "规模超上限",
            "detail": f"当前规模{scale}亿，超过{rules['scale_upper_limit']}亿上限",
            "action": "不再新增，观察一季度后决定是否减仓"
        })
    
    # 4. 6个月内规模翻倍
    scale_now = data.get('当前规模(亿)', 0)
    scale_6m_ago = data.get('6个月前规模(亿)', 0)
    if (isinstance(scale_now, (int, float)) and isinstance(scale_6m_ago, (int, float))
            and scale_6m_ago > 0 and scale_now / scale_6m_ago >= 2):
        red_flags.append({
            "rule": "规模6个月内翻倍",
            "detail": f"6个月前{scale_6m_ago}亿 → 现在{scale_now}亿",
            "action": "立即减仓50%"
        })
    
    # 5. 连续4季度跑输基准
    underperform_q = data.get('连续跑输基准季度数', 0)
    if isinstance(underperform_q, (int, float)) and underperform_q >= rules['underperform_quarters_limit']:
        red_flags.append({
            "rule": "连续4季度跑输基准",
            "detail": f"已连续{int(underperform_q)}个季度跑输基准",
            "action": "减仓50%并启动替换流程"
        })
    
    # 6. 最大回撤超阈值
    drawdown = data.get('复权净值最大回撤(%)', 0)
    if isinstance(drawdown, (int, float)) and drawdown < rules['max_drawdown_threshold']:
        red_flags.append({
            "rule": "最大回撤超阈值",
            "detail": f"回撤{drawdown}%，超过{rules['max_drawdown_threshold']}%阈值",
            "action": "减仓30%"
        })
    
    # 7. 回撤相对基准多跌超阈值
    dd_vs_bench = data.get('回撤相对基准多跌(%)', 0)
    if isinstance(dd_vs_bench, (int, float)) and dd_vs_bench < rules['drawdown_vs_benchmark_threshold']:
        red_flags.append({
            "rule": "回撤相对基准多跌",
            "detail": f"相对基准多跌{dd_vs_bench}%，超过{rules['drawdown_vs_benchmark_threshold']}%阈值",
            "action": "减仓30%"
        })
    
    # 8. 股票仓位连续两季低于下限
    position = data.get('股票仓位(%)', None)
    prev_position = data.get('上季股票仓位(%)', None)
    min_pos = rules['stock_position_range'][0]
    if (isinstance(position, (int, float)) and isinstance(prev_position, (int, float))
            and position < min_pos and prev_position < min_pos):
        red_flags.append({
            "rule": "股票仓位连续两季低于下限",
            "detail": f"本季{position}%，上季{prev_position}%，下限{min_pos}%",
            "action": "黄灯观察，连续两季触发升级为红灯"
        })
    
    return red_flags


# ============ 黄灯规则（观察/预警） ============

def check_yellow_flags(data, rules):
    """
    检查黄灯条件。
    
    返回：
        list of dict，每个触发的黄灯
    """
    yellow_flags = []
    
    # 1. 前十大集中度过高
    concentration = data.get('前十大集中度(%)', 0)
    if isinstance(concentration, (int, float)) and concentration > rules['top10_concentration_limit']:
        yellow_flags.append({
            "rule": "前十大集中度过高",
            "detail": f"集中度{concentration}%，超过{rules['top10_concentration_limit']}%",
            "action": "观察，连续两季则考虑减仓"
        })
    
    # 2. 防御资产占比过低
    defense = data.get('防御资产占比(%)', 100)
    if isinstance(defense, (int, float)) and defense < rules['defense_asset_min_ratio']:
        yellow_flags.append({
            "rule": "防御资产占比不足",
            "detail": f"防御资产占比{defense}%，低于{rules['defense_asset_min_ratio']}%下限",
            "action": "观察一季度"
        })
    
    # 3. 近6个月跑输基准
    underperform_6m = data.get('近6个月相对基准(%)', 0)
    if isinstance(underperform_6m, (int, float)) and underperform_6m < -5:
        yellow_flags.append({
            "rule": "近6个月跑输基准超5%",
            "detail": f"近6个月相对基准{underperform_6m}%",
            "action": "关注，结合季报分析原因"
        })
    
    # 4. 近12个月跑输基准
    underperform_12m = data.get('近12个月相对基准(%)', 0)
    if isinstance(underperform_12m, (int, float)) and underperform_12m < -8:
        yellow_flags.append({
            "rule": "近12个月跑输基准超8%",
            "detail": f"近12个月相对基准{underperform_12m}%",
            "action": "启动深度复盘"
        })
    
    # 5. 关键词一致性异常
    keyword_score = data.get('关键词一致性评分', 10)
    if isinstance(keyword_score, (int, float)) and keyword_score < 6:
        yellow_flags.append({
            "rule": "季报关键词一致性低",
            "detail": f"一致性评分{keyword_score}/10",
            "action": "人工复核季报文字与持仓方向"
        })
    
    return yellow_flags


# ============ 综合判定 ============

def run_judgment(data):
    """
    综合判定，返回完整结果。
    
    参数：
        data: dict，季度检查数据
    
    返回：
        dict: {
            "status": "红灯"/"黄灯"/"绿灯",
            "red_flags": [...],
            "yellow_flags": [...],
            "summary": "...",
            "suggested_action": "...",
            "check_time": "..."
        }
    """
    rules = get_fund_rules(data.get('基金代码'))
    
    red_flags = check_red_flags(data, rules)
    yellow_flags = check_yellow_flags(data, rules)
    
    # 判定最终状态
    if red_flags:
        status = "红灯"
        # 取最严重的动作
        suggested_action = red_flags[0]['action']
    elif yellow_flags:
        status = "黄灯"
        suggested_action = "持续观察，下季度重点关注"
    else:
        status = "绿灯"
        suggested_action = "维持持仓，正常定投"
    
    # 生成摘要
    summary_parts = []
    for flag in red_flags:
        summary_parts.append(f"[红] {flag['rule']}: {flag['detail']}")
    for flag in yellow_flags:
        summary_parts.append(f"[黄] {flag['rule']}: {flag['detail']}")
    if not summary_parts:
        summary_parts.append("[绿] 所有指标正常")
    
    return {
        "status": status,
        "red_flags": red_flags,
        "yellow_flags": yellow_flags,
        "red_count": len(red_flags),
        "yellow_count": len(yellow_flags),
        "summary": "\n".join(summary_parts),
        "suggested_action": suggested_action,
        "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


# ============ 测试入口 ============

if __name__ == '__main__':
    print("=== 规则引擎测试 ===\n")
    
    # 模拟一组正常数据
    test_normal = {
        "基金代码": "180031",
        "报告期": "2025Q2",
        "李晓星是否在任": "是",
        "三人团队12个月内离任人数": 0,
        "当前规模(亿)": 45,
        "6个月前规模(亿)": 40,
        "连续跑输基准季度数": 1,
        "复权净值最大回撤(%)": -15,
        "回撤相对基准多跌(%)": -5,
        "股票仓位(%)": 85,
        "上季股票仓位(%)": 82,
        "前十大集中度(%)": 48,
        "防御资产占比(%)": 15,
        "近6个月相对基准(%)": 2.5,
        "近12个月相对基准(%)": 3.1,
        "关键词一致性评分": 8
    }
    
    result = run_judgment(test_normal)
    print(f"正常数据测试 → 状态: {result['status']}")
    print(f"摘要: {result['summary']}\n")
    
    # 模拟一组触发红灯的数据
    test_red = {
        "基金代码": "180031",
        "报告期": "2025Q2",
        "李晓星是否在任": "否",
        "三人团队12个月内离任人数": 2,
        "当前规模(亿)": 120,
        "6个月前规模(亿)": 50,
        "连续跑输基准季度数": 5,
        "复权净值最大回撤(%)": -30,
        "回撤相对基准多跌(%)": -18,
        "股票仓位(%)": 55,
        "上季股票仓位(%)": 58,
        "前十大集中度(%)": 65,
        "防御资产占比(%)": 5,
        "近6个月相对基准(%)": -8,
        "近12个月相对基准(%)": -12,
        "关键词一致性评分": 4
    }
    
    result = run_judgment(test_red)
    print(f"红灯数据测试 → 状态: {result['status']}")
    print(f"红灯数: {result['red_count']}，黄灯数: {result['yellow_count']}")
    print(f"建议动作: {result['suggested_action']}")
    print(f"\n详细摘要:\n{result['summary']}")