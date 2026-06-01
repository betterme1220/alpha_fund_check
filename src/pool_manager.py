"""
备用基金池管理模块
功能：监控备用基金池中候选基金的状态，方便替换时快速决策
"""

import sys
import os
import re
import requests
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from excel_engine import load_config, read_sheet
from monthly_check import fetch_fund_detail, fetch_benchmark_return, calculate_max_drawdown


# ============ 备用基金池配置 ============

def get_pool_funds():
    """
    从大表'备用基金池' sheet 读取候选基金列表
    如果读取失败，返回默认列表
    """
    try:
        df = read_sheet('备用基金池')
        # 尝试找基金代码列
        code_col = None
        for col in df.columns:
            if '代码' in str(col) or 'code' in str(col).lower():
                code_col = col
                break

        if code_col:
            codes = df[code_col].dropna().astype(str).tolist()
            # 清理代码格式
            codes = [c.split('.')[0].zfill(6) for c in codes if c.strip() and c != 'nan']
            return codes

    except Exception as e:
        print(f"  [提示] 读取备用基金池失败: {e}")

    # 默认备用池（可在config中配置）
    config = load_config()
    return config.get('backup_pool', [])


def fetch_fund_basic_info(fund_code):
    """获取基金基本信息：名称、经理、规模"""
    url = f"http://fund.eastmoney.com/pingzhongdata/{fund_code}.js"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    info = {"code": fund_code}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        text = resp.text

        # 基金名称
        name_match = re.search(r'var fS_name = "([^"]+)"', text)
        if name_match:
            info['name'] = name_match.group(1)

        # 基金经理
        from daily_check import fetch_fund_managers
        managers = fetch_fund_managers(fund_code)
        info['managers'] = managers

        # 规模
        scale_match = re.search(r'基金规模</a>：([\d.]+)亿元', text)
        if scale_match:
            info['scale'] = float(scale_match.group(1))
        else:
            scale_match2 = re.search(r'资产规模：([\d.]+)亿元', text)
            if scale_match2:
                info['scale'] = float(scale_match2.group(1))

    except Exception as e:
        info['error'] = str(e)

    return info


def scan_pool():
    """扫描备用基金池，获取所有候选基金的最新状态"""
    config = load_config()
    pool_codes = config.get('backup_pool', [])

    if not pool_codes:
        # 尝试从大表读取
        pool_codes = get_pool_funds()

    if not pool_codes:
        print("  备用基金池为空，请在 config/fund_config.json 的 backup_pool 中添加基金代码")
        return []

    print(f"  备用基金池共 {len(pool_codes)} 只基金\n")

    results = []

    for i, code in enumerate(pool_codes, 1):
        print(f"  [{i}/{len(pool_codes)}] 扫描 {code}...")

        # 基本信息
        info = fetch_fund_basic_info(code)

        # 净值和收益
        detail = fetch_fund_detail(code)
        if 'error' not in detail:
            info['latest_nav'] = detail.get('latest_nav')
            info['return_1m'] = detail.get('return_1m')
            info['return_3m'] = detail.get('return_3m')
            info['return_6m'] = detail.get('return_6m')
            info['max_drawdown_6m'] = detail.get('max_drawdown_6m')

        results.append(info)

    return results


def run_pool_scan():
    """执行备用基金池扫描"""
    print("=" * 60)
    print(f"  备用基金池扫描")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = scan_pool()

    if not results:
        return

    # 打印结果表格
    print("\n" + "-" * 80)
    print(f"{'代码':<8}{'名称':<20}{'经理':<15}{'近6月':<8}{'回撤':<8}{'规模':<8}")
    print("-" * 80)

    for r in results:
        code = r.get('code', '')
        name = r.get('name', '未知')[:18]
        managers = ','.join(r.get('managers', []))[:12]
        ret_6m = f"{r.get('return_6m', 'N/A')}%" if r.get('return_6m') is not None else 'N/A'
        dd = f"{r.get('max_drawdown_6m', 'N/A')}%" if r.get('max_drawdown_6m') is not None else 'N/A'
        scale = f"{r.get('scale', 'N/A')}亿" if r.get('scale') is not None else 'N/A'

        print(f"{code:<8}{name:<20}{managers:<15}{ret_6m:<8}{dd:<8}{scale:<8}")

    print("-" * 80)

    # 排名建议
    ranked = [r for r in results if r.get('return_6m') is not None]
    if ranked:
        ranked.sort(key=lambda x: x.get('return_6m', 0), reverse=True)
        print(f"\n  近6个月收益排名第一: {ranked[0].get('code')} {ranked[0].get('name')} ({ranked[0].get('return_6m')}%)")

    print("=" * 60)


if __name__ == '__main__':
    run_pool_scan()