"""
季度检查主流程
功能：输入季度数据 → 规则判定 → 回写大表季度检查表 → 追加执行记录
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from excel_engine import upsert_to_sheet, append_to_sheet, get_sheet_columns
from rule_engine import run_judgment


def collect_quarterly_data():
    """
    交互式收集季度检查数据。
    以后可以改成从爬虫自动填入，现在先手动输入。
    """
    print("=" * 60)
    print("  季度检查数据录入")
    print("=" * 60)
    print("提示：直接回车表示跳过该项（留空）\n")

    data = {}

    # 基本信息
    data['检查日期'] = input("检查日期 (如 2025-07-01，回车用今天): ").strip()
    if not data['检查日期']:
        data['检查日期'] = datetime.now().strftime("%Y-%m-%d")

    data['报告期'] = input("报告期 (如 2025Q2): ").strip()
    if not data['报告期']:
        print("[错误] 报告期不能为空！")
        return None

    # 基金经理在任情况
    data['李晓星在任?'] = input("李晓星在任? (是/否): ").strip() or "是"
    data['张萍在任?'] = input("张萍在任? (是/否): ").strip() or "是"
    data['杜宇在任?'] = input("杜宇在任? (是/否): ").strip() or "是"

    # 计算离任人数（用于规则引擎）
    team_members = [data['李晓星在任?'], data['张萍在任?'], data['杜宇在任?']]
    data['_三人团队12个月内离任人数'] = team_members.count('否')

    # 规模
    scale_input = input("基金规模(亿元): ").strip()
    data['基金规模(亿元)'] = float(scale_input) if scale_input else None

    data['6个月规模是否翻倍?'] = input("6个月规模是否翻倍? (是/否): ").strip() or "否"

    # 仓位和集中度
    pos_input = input("股票仓位(%): ").strip()
    data['股票仓位'] = float(pos_input) if pos_input else None

    conc_input = input("前十大集中度(%): ").strip()
    data['前十大集中度'] = float(conc_input) if conc_input else None

    def_input = input("防御资产占比(%): ").strip()
    data['防御资产占比'] = float(def_input) if def_input else None

    # 收益
    fund_ret = input("基金6个月收益(%): ").strip()
    data['基金6个月收益'] = float(fund_ret) if fund_ret else None

    bench_ret = input("基准6个月收益(%): ").strip()
    data['基准6个月收益'] = float(bench_ret) if bench_ret else None

    # 计算超额
    if data['基金6个月收益'] is not None and data['基准6个月收益'] is not None:
        data['6个月超额'] = round(data['基金6个月收益'] - data['基准6个月收益'], 2)
    else:
        data['6个月超额'] = None

    return data


def map_to_rule_engine(data):
    """
    将录入数据映射为规则引擎需要的字段格式
    """
    rule_data = {
        "基金代码": "180031",
        "报告期": data.get('报告期'),
        "李晓星是否在任": data.get('李晓星在任?'),
        "三人团队12个月内离任人数": data.get('_三人团队12个月内离任人数', 0),
        "当前规模(亿)": data.get('基金规模(亿元)'),
        "6个月前规模(亿)": data.get('基金规模(亿元)') / 2 if data.get('6个月规模是否翻倍?') == '是' else data.get('基金规模(亿元)'),
        "股票仓位(%)": data.get('股票仓位'),
        "前十大集中度(%)": data.get('前十大集中度'),
        "防御资产占比(%)": data.get('防御资产占比'),
        "近6个月相对基准(%)": data.get('6个月超额'),
    }
    return rule_data


def run_quarterly_check():
    """执行完整季度检查流程"""

    # 1. 收集数据
    data = collect_quarterly_data()
    if data is None:
        return

    print("\n" + "=" * 60)
    print("  规则判定中...")
    print("=" * 60)

    # 2. 规则判定
    rule_data = map_to_rule_engine(data)
    result = run_judgment(rule_data)

    # 3. 显示结果
    print(f"\n状态: {result['status']}")
    print(f"红灯数: {result['red_count']}  黄灯数: {result['yellow_count']}")
    print(f"建议动作: {result['suggested_action']}")
    print(f"\n详细:")
    print(result['summary'])

    # 4. 计算观察触发数
    data['观察触发数'] = result['yellow_count']
    data['本期结论'] = result['status']

    # 移除内部字段（不写入Excel）
    data.pop('_三人团队12个月内离任人数', None)

    # 5. 回写季度检查表
    print("\n" + "=" * 60)
    print("  回写大表...")
    print("=" * 60)

    upsert_to_sheet("季度检查表", data, ["报告期"])

    # 6. 如果有红灯或黄灯，追加执行记录
    if result['red_count'] > 0 or result['yellow_count'] > 0:
        for flag in result['red_flags'] + result['yellow_flags']:
            record = {
                "触发日期": data['检查日期'],
                "事件来源": f"季度检查-{data['报告期']}",
                "触发层级": "红灯" if flag in result['red_flags'] else "黄灯",
                "规则编号": flag['rule'],
                "证据/数据": flag['detail'],
                "执行动作": flag['action'],
                "执行比例": "",
                "是否已执行": "待执行",
                "复盘日期": "",
                "备注": ""
            }
            append_to_sheet("执行记录", record)

    print("\n" + "=" * 60)
    print("  季度检查完成！")
    print("=" * 60)
    print(f"  结论: {result['status']}")
    print(f"  动作: {result['suggested_action']}")
    print(f"  数据已回写到大表")
    if result['red_count'] > 0 or result['yellow_count'] > 0:
        print(f"  执行记录已追加 {result['red_count'] + result['yellow_count']} 条")
    print("=" * 60)


if __name__ == '__main__':
    run_quarterly_check()