"""
季度检查模块
功能：自动获取季报数据 → 规则判定 → 回写大表
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from excel_engine import load_config, upsert_to_sheet, append_to_sheet
from rule_engine import run_judgment


def collect_quarterly_data(report_period=None):
    """
    自动收集季度检查数据，所有数据从网上抓取。
    只需要传入报告期（如 2025Q2），其余全部自动。
    """
    from monthly_check import fetch_fund_detail, fetch_benchmark_return
    from daily_check import fetch_fund_managers
    from quarter_data_fetcher import fetch_all_quarter_data

    config = load_config()
    fund_code = config['active_fund']
    fund_info = config['funds'][fund_code]

    print("=" * 60)
    print(f"  季度检查 | {fund_code} {fund_info['name']}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    data = {}
    data['检查日期'] = datetime.now().strftime("%Y-%m-%d")

    if not report_period:
        report_period = input("\n报告期 (如 2026Q1): ").strip()
    if not report_period:
        print("[错误] 报告期不能为空！")
        return None
    data['报告期'] = report_period

    print("\n[1/4] 获取基金经理...")
    managers = fetch_fund_managers(fund_code)
    print(f"  当前经理: {', '.join(managers)}")

    team = fund_info['manager_team']
    for member in team:
        if member in managers:
            data[f'{member}在任?'] = '是'
            print(f"    {member}: 在任 ✓")
        else:
            data[f'{member}在任?'] = '否'
            print(f"    {member}: ⚠️ 不在名单中！")

    team_status = [data.get(f'{m}在任?', '是') for m in team]
    data['_三人团队12个月内离任人数'] = team_status.count('否')

    print("\n[2/4] 获取季报数据...")
    quarter_data = fetch_all_quarter_data(fund_code)

    data['基金规模(亿元)'] = quarter_data.get('当前规模(亿)')
    data['股票仓位'] = quarter_data.get('股票仓位(%)')
    data['前十大集中度'] = quarter_data.get('前十大集中度(%)')
    data['防御资产占比'] = quarter_data.get('防御资产占比(%)')
    data['6个月规模是否翻倍?'] = quarter_data.get('6个月规模翻倍', '否')

    print("\n[3/4] 获取收益数据...")
    detail = fetch_fund_detail(fund_code)
    bench = fetch_benchmark_return(fund_code)

    data['基金6个月收益'] = detail.get('return_6m')
    data['基准6个月收益'] = bench.get('bench_return_6m')

    if data['基金6个月收益'] is not None:
        print(f"  基金近6个月收益: {data['基金6个月收益']}%")
    if data['基准6个月收益'] is not None:
        print(f"  基准近6个月收益: {data['基准6个月收益']}%")

    if data['基金6个月收益'] is not None and data['基准6个月收益'] is not None:
        data['6个月超额'] = round(data['基金6个月收益'] - data['基准6个月收益'], 2)
        print(f"  超额收益: {data['6个月超额']}%")
    else:
        data['6个月超额'] = None

    print("\n[4/4] 数据汇总")
    print("-" * 40)
    print(f"  报告期: {data['报告期']}")
    leave_count = data['_三人团队12个月内离任人数']
    print(f"  经理团队: {'全部在任' if leave_count == 0 else f'离任{leave_count}人'}")
    print(f"  规模: {data.get('基金规模(亿元)', 'N/A')}亿")
    print(f"  股票仓位: {data.get('股票仓位', 'N/A')}%")
    print(f"  前十大集中度: {data.get('前十大集中度', 'N/A')}%")
    print(f"  防御资产占比: {data.get('防御资产占比', 'N/A')}%")
    print(f"  基金6个月收益: {data.get('基金6个月收益', 'N/A')}%")
    print(f"  基准6个月收益: {data.get('基准6个月收益', 'N/A')}%")
    print(f"  超额: {data.get('6个月超额', 'N/A')}%")
    print(f"  规模翻倍: {data.get('6个月规模是否翻倍?', '否')}")
    print("-" * 40)

    return data


def run_quarterly_check(report_period=None):
    """执行季度检查完整流程"""
    data = collect_quarterly_data(report_period)
    if data is None:
        return

    rule_data = {
        '基金代码': '180031',
        '李晓星是否在任': data.get('李晓星在任?', '是'),
        '三人团队12个月内离任人数': data.get('_三人团队12个月内离任人数', 0),
        '当前规模(亿)': data.get('基金规模(亿元)'),
        '规模6个月内翻倍': data.get('6个月规模是否翻倍?', '否'),
        '前十大集中度(%)': data.get('前十大集中度'),
        '防御资产占比(%)': data.get('防御资产占比'),
        '近6个月相对基准(%)': data.get('6个月超额'),
    }

    print("\n" + "=" * 60)
    print("  规则判定中...")
    print("=" * 60)

    result = run_judgment(rule_data)

    print(f"\n  状态: {result['status']}")
    print(f"  红灯数: {result['red_count']}  黄灯数: {result['yellow_count']}")
    print(f"  建议动作: {result['suggested_action']}")
    print(f"\n  详细:")
    print(f"  {result['summary']}")

    print("\n" + "=" * 60)
    print("  回写大表...")
    print("=" * 60)

    record = {
        "检查日期": data['检查日期'],
        "报告期": data['报告期'],
        "李晓星在任?": data.get('李晓星在任?', '是'),
        "张萍在任?": data.get('张萍在任?', '是'),
        "杜宇在任?": data.get('杜宇在任?', '是'),
        "基金规模(亿元)": data.get('基金规模(亿元)'),
        "6个月规模是否翻倍?": data.get('6个月规模是否翻倍?', '否'),
        "股票仓位": data.get('股票仓位'),
        "前十大集中度": data.get('前十大集中度'),
        "防御资产占比": data.get('防御资产占比'),
        "基金6个月收益": data.get('基金6个月收益'),
        "基准6个月收益": data.get('基准6个月收益'),
        "6个月超额": data.get('6个月超额'),
        "观察触发数": len(result.get('red_flags', [])) + len(result.get('yellow_flags', [])),
        "本期结论": result['status'],
    }
    upsert_to_sheet("季度检查表", record, ["报告期"])

    all_flags = result['red_flags'] + result['yellow_flags']
    if all_flags:
        for flag in all_flags:
            exec_record = {
                "触发日期": data['检查日期'],
                "事件来源": "季度检查",
                "触发层级": "红灯" if flag in result['red_flags'] else "黄灯",
                "规则编号": flag['rule'],
                "证据/数据": flag['detail'],
                "执行动作": flag['action'],
                "执行比例": "",
                "是否已执行": "待确认",
                "复盘日期": "",
                "备注": ""
            }
            upsert_to_sheet("执行记录", exec_record, ["触发日期", "规则编号"])

    print("\n" + "=" * 60)
    print("  季度检查完成！")
    print("=" * 60)
    print(f"  结论: {result['status']}")
    print(f"  动作: {result['suggested_action']}")
    print(f"  数据已回写到大表")
    print("=" * 60)

    return result


if __name__ == '__main__':
    run_quarterly_check()
