"""
月度检查模块
功能：每月跟踪回撤、相对收益、规模变化，判断是否触发预警
"""

import sys
import os
import re
import requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from excel_engine import load_config, append_to_sheet
from rule_engine import get_fund_rules


# ============ 数据抓取 ============

def fetch_fund_detail(fund_code):
    """
    从东方财富获取基金详细数据：规模、近期收益、回撤等
    """
    url = f"http://fund.eastmoney.com/pingzhongdata/{fund_code}.js"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"http://fund.eastmoney.com/{fund_code}.html"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        text = resp.text
        result = {}

        # 提取净值走势数据，计算回撤
        if 'Data_netWorthTrend' in text:
            pattern = r'\{"x":(\d+),"y":([\d.]+),"equityReturn":([\d.-]+),"unitMoney":"([^"]*)"\}'
            matches = re.findall(pattern, text)
            if matches:
                navs = [(int(m[0]), float(m[1])) for m in matches]
                result['nav_history'] = navs
                result['latest_nav'] = navs[-1][1]
                result['latest_date'] = datetime.fromtimestamp(navs[-1][0] / 1000).strftime("%Y-%m-%d")

                # 计算近6个月最大回撤
                six_months_ago = datetime.now() - timedelta(days=180)
                six_months_ts = int(six_months_ago.timestamp() * 1000)
                recent_navs = [n[1] for n in navs if n[0] >= six_months_ts]

                if recent_navs:
                    max_drawdown = calculate_max_drawdown(recent_navs)
                    result['max_drawdown_6m'] = max_drawdown

                # 计算近1个月、3个月、6个月收益率
                now_nav = navs[-1][1]

                one_month_ago = datetime.now() - timedelta(days=30)
                three_months_ago = datetime.now() - timedelta(days=90)

                one_month_ts = int(one_month_ago.timestamp() * 1000)
                three_months_ts = int(three_months_ago.timestamp() * 1000)

                # 找最接近目标日期的净值
                one_month_nav = find_closest_nav(navs, one_month_ts)
                three_month_nav = find_closest_nav(navs, three_months_ts)
                six_month_nav = find_closest_nav(navs, six_months_ts)

                if one_month_nav:
                    result['return_1m'] = round((now_nav / one_month_nav - 1) * 100, 2)
                if three_month_nav:
                    result['return_3m'] = round((now_nav / three_month_nav - 1) * 100, 2)
                if six_month_nav:
                    result['return_6m'] = round((now_nav / six_month_nav - 1) * 100, 2)

        # 提取基金规模（从页面其他接口）
        scale = fetch_fund_scale(fund_code)
        if scale:
            result['scale'] = scale

        return result

    except Exception as e:
        return {"error": str(e)}


def fetch_fund_scale(fund_code):
    """从东方财富获取基金规模"""
    url = f"http://fund.eastmoney.com/{fund_code}.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'

        # 搜索规模信息
        pattern = r'基金规模</a>：([\d.]+)亿元'
        match = re.search(pattern, resp.text)
        if match:
            return float(match.group(1))

        # 备用模式
        pattern2 = r'资产规模：([\d.]+)亿元'
        match2 = re.search(pattern2, resp.text)
        if match2:
            return float(match2.group(1))

        return None

    except Exception:
        return None


def fetch_benchmark_return(fund_code):
    """
    从东方财富获取基准收益数据
    """
    url = f"http://fund.eastmoney.com/pingzhongdata/{fund_code}.js"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"http://fund.eastmoney.com/{fund_code}.html"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        text = resp.text

        # 提取基准走势 Data_grandTotal 中的第二条线（基准）
        if 'Data_grandTotal' in text:
            # 格式: var Data_grandTotal = [[时间戳,基金累计收益],[时间戳,基准累计收益]]
            section = text.split('Data_grandTotal')[1].split(';')[0]
            # 找第二个数组（基准）
            arrays = re.findall(r'\[\[(.*?)\]\]', section)
            if len(arrays) >= 2:
                bench_data = re.findall(r'\[(\d+),([\d.-]+)\]', arrays[1])
                if bench_data:
                    bench_navs = [(int(b[0]), float(b[1])) for b in bench_data]

                    # 计算近6个月基准收益
                    six_months_ago = datetime.now() - timedelta(days=180)
                    six_months_ts = int(six_months_ago.timestamp() * 1000)

                    now_val = bench_navs[-1][1]
                    six_month_val = find_closest_value(bench_navs, six_months_ts)

                    if six_month_val is not None:
                        return {
                            'bench_return_6m': round(now_val - six_month_val, 2)
                        }

        return {}

    except Exception:
        return {}


# ============ 计算工具 ============

def calculate_max_drawdown(nav_list):
    """计算最大回撤（百分比）"""
    if not nav_list or len(nav_list) < 2:
        return 0

    peak = nav_list[0]
    max_dd = 0

    for nav in nav_list:
        if nav > peak:
            peak = nav
        dd = (nav - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd

    return round(max_dd, 2)


def find_closest_nav(navs, target_ts):
    """找最接近目标时间戳的净值"""
    closest = None
    min_diff = float('inf')

    for ts, nav in navs:
        diff = abs(ts - target_ts)
        if diff < min_diff:
            min_diff = diff
            closest = nav

    return closest


def find_closest_value(data_list, target_ts):
    """找最接近目标时间戳的值"""
    closest = None
    min_diff = float('inf')

    for ts, val in data_list:
        diff = abs(ts - target_ts)
        if diff < min_diff:
            min_diff = diff
            closest = val

    return closest


# ============ 月度判定 ============

def run_monthly_check():
    """执行月度检查"""
    config = load_config()
    fund_code = config['active_fund']
    fund_info = config['funds'][fund_code]
    rules = get_fund_rules(fund_code)

    print("=" * 60)
    print(f"  月度检查 | {fund_code} {fund_info['name']}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    alerts = []

    # 1. 获取基金详细数据
    print("\n[1/3] 获取基金净值和收益数据...")
    detail = fetch_fund_detail(fund_code)

    if 'error' in detail:
        print(f"  [错误] {detail['error']}")
        return

    print(f"  最新净值: {detail.get('latest_nav')} ({detail.get('latest_date')})")

    if detail.get('return_1m') is not None:
        print(f"  近1个月收益: {detail['return_1m']}%")
    if detail.get('return_3m') is not None:
        print(f"  近3个月收益: {detail['return_3m']}%")
    if detail.get('return_6m') is not None:
        print(f"  近6个月收益: {detail['return_6m']}%")
    if detail.get('max_drawdown_6m') is not None:
        print(f"  近6个月最大回撤: {detail['max_drawdown_6m']}%")

    # 2. 获取规模
    print("\n[2/3] 获取基金规模...")
    scale = detail.get('scale')
    if scale:
        print(f"  当前规模: {scale}亿元")

        # 规模超限检查
        if scale > rules['scale_upper_limit']:
            alert = f"规模{scale}亿超过{rules['scale_upper_limit']}亿上限"
            print(f"  ⚠️ {alert}")
            alerts.append({
                "type": "红灯",
                "rule": "规模超上限",
                "detail": alert,
                "action": "不再新增，观察一季度"
            })
        else:
            print(f"  ✓ 规模正常（上限{rules['scale_upper_limit']}亿）")
    else:
        print("  [未获取到规模数据]")

    # 3. 回撤检查
    print("\n[3/3] 回撤与收益检查...")
    max_dd = detail.get('max_drawdown_6m')
    if max_dd is not None:
        if max_dd < rules['max_drawdown_threshold']:
            alert = f"近6个月最大回撤{max_dd}%，超过{rules['max_drawdown_threshold']}%阈值"
            print(f"  ⚠️ {alert}")
            alerts.append({
                "type": "红灯",
                "rule": "最大回撤超阈值",
                "detail": alert,
                "action": "减仓30%"
            })
        else:
            print(f"  ✓ 回撤正常（阈值{rules['max_drawdown_threshold']}%）")

    # 获取基准收益对比
    print("\n  获取基准收益对比...")
    bench = fetch_benchmark_return(fund_code)
    if bench.get('bench_return_6m') is not None and detail.get('return_6m') is not None:
        excess = round(detail['return_6m'] - bench['bench_return_6m'], 2)
        print(f"  基金6个月收益: {detail['return_6m']}%")
        print(f"  基准6个月收益: {bench['bench_return_6m']}%")
        print(f"  超额收益: {excess}%")

        if excess < -5:
            alert = f"近6个月跑输基准{abs(excess)}%"
            print(f"  ⚠️ {alert}")
            alerts.append({
                "type": "黄灯",
                "rule": "近6个月跑输基准超5%",
                "detail": alert,
                "action": "关注，结合季报分析原因"
            })
        else:
            print(f"  ✓ 相对收益正常")
    else:
        print("  [基准数据获取不完整，跳过对比]")

    # 4. 汇总
    print("\n" + "=" * 60)
    if alerts:
        print(f"  ⚠️ 发现 {len(alerts)} 个警报！")
        for a in alerts:
            print(f"  [{a['type']}] {a['rule']}: {a['detail']}")

            # 写入执行记录
            record = {
                "触发日期": datetime.now().strftime("%Y-%m-%d"),
                "事件来源": "月度检查",
                "触发层级": a['type'],
                "规则编号": a['rule'],
                "证据/数据": a['detail'],
                "执行动作": a['action'],
                "执行比例": "",
                "是否已执行": "待确认",
                "复盘日期": "",
                "备注": ""
            }
            append_to_sheet("执行记录", record)

        print(f"\n  已追加 {len(alerts)} 条执行记录到大表")
    else:
        print("  ✓ 月度检查通过，所有指标正常")
    print("=" * 60)

    return alerts


if __name__ == '__main__':
    run_monthly_check()