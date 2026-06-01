"""
季报数据自动抓取模块
功能：从东方财富f10接口获取季报关键数据（持仓、集中度、仓位等）
"""

import sys
import os
import re
import json
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from excel_engine import load_config


def fetch_top10_holdings(fund_code):
    """
    获取基金前十大重仓股
    """
    url = "http://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {
        "type": "jjcc",
        "code": fund_code,
        "topline": 10,
        "year": "",
        "month": "",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"http://fundf10.eastmoney.com/ccmx_{fund_code}.html"
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.encoding = 'utf-8'
        text = resp.text

        result = {}

        # 提取报告期
        date_match = re.search(r'截止至：<font[^>]*>(\d{4}-\d{2}-\d{2})</font>', text)
        if date_match:
            result['report_date'] = date_match.group(1)

        # 解析持仓
        # 格式: <td>序号</td><td><a>代码</a></td><td class='tol'><a>名称</a></td>...<td class='tor'>占比%</td><td class='tor'>持股数</td><td class='tor'>市值</td>
        holdings = []

        # 匹配每一行：序号、代码、名称、占比
        pattern = r"<td>(\d+)</td><td><a[^>]*>(\d{6})</a></td><td class='tol'><a[^>]*>([^<]+)</a></td>.*?<td class='tor'>([\d.]+)%</td>"
        matches = re.findall(pattern, text)

        for m in matches[:10]:
            holdings.append({
                'rank': int(m[0]),
                'code': m[1],
                'stock': m[2],
                'ratio': float(m[3])
            })

        result['holdings'] = holdings
        result['total_ratio'] = round(sum(h['ratio'] for h in holdings), 2) if holdings else None

        return result

    except Exception as e:
        return {"error": str(e)}


def fetch_asset_allocation(fund_code):
    """
    获取基金资产配置（股票仓位、债券、现金等）
    从另一个接口获取
    """
    # 尝试从 pingzhongdata 接口获取资产配置
    url = f"http://fund.eastmoney.com/pingzhongdata/{fund_code}.js"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"http://fund.eastmoney.com/{fund_code}.html"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = 'utf-8'
        text = resp.text

        result = {}

        # pingzhongdata 里有资产配置数据
        # 格式: var Data_assetAllocation = {"categories":["2024-06-30",...],"series":[{"name":"股票","data":[...]},{"name":"债券","data":[...]},{"name":"现金","data":[...]}]}
        if 'Data_assetAllocation' in text:
            alloc_text = text.split('Data_assetAllocation')[1].split('var')[0]

            # 提取 categories（日期列表）
            cat_match = re.search(r'"categories":\[([^\]]+)\]', alloc_text)
            if cat_match:
                dates = re.findall(r'"(\d{4}-\d{2}-\d{2})"', cat_match.group(1))
                if dates:
                    result['report_date'] = dates[-1]  # 最新一期

            # 提取各类资产的最新值
            series_matches = re.findall(r'\{"name":"([^"]+)","type"[^}]*"data":\[([^\]]+)\]', alloc_text)
            if not series_matches:
                series_matches = re.findall(r'"name":"([^"]+)"[^}]*"data":\[([^\]]+)\]', alloc_text)

            for name, data_str in series_matches:
                values = re.findall(r'[\d.]+', data_str)
                if values:
                    latest_val = float(values[-1])  # 取最新一期
                    if '股票' in name:
                        result['stock_ratio'] = latest_val
                    elif '债券' in name:
                        result['bond_ratio'] = latest_val
                    elif '现金' in name:
                        result['cash_ratio'] = latest_val
                    elif '其他' in name:
                        result['other_ratio'] = latest_val

        return result

    except Exception as e:
        return {"error": str(e)}

def fetch_fund_scale_history(fund_code):
    """
    获取基金规模历史
    返回：list of dict [{'date': 日期, 'scale': 规模(亿)}, ...]
    """
    url = "http://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    params = {
        "type": "gmbd",
        "code": fund_code,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"http://fundf10.eastmoney.com/gmbd_{fund_code}.html"
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.encoding = 'utf-8'
        text = resp.text

        # 提取日期和规模
        dates = re.findall(r'(\d{4}-\d{2}-\d{2})', text)
        scales = re.findall(r'([\d,]+\.\d+)亿元', text)

        history = []
        for i in range(min(len(dates), len(scales))):
            scale_val = float(scales[i].replace(',', ''))
            history.append({
                'date': dates[i],
                'scale': scale_val
            })

        return history

    except Exception as e:
        return []


def fetch_all_quarter_data(fund_code=None):
    """
    一次性获取所有季报相关数据
    返回：dict，包含所有自动获取的季报数据
    """
    if fund_code is None:
        config = load_config()
        fund_code = config['active_fund']

    print(f"  [自动抓取] 基金代码: {fund_code}")

    result = {
        '基金代码': fund_code,
    }

    # 1. 前十大持仓
    print("  [1/3] 获取前十大重仓股...")
    holdings = fetch_top10_holdings(fund_code)
    if 'error' not in holdings:
        result['前十大持仓'] = holdings.get('holdings', [])
        result['前十大集中度(%)'] = holdings.get('total_ratio')
        result['持仓报告期'] = holdings.get('report_date')
        if holdings.get('total_ratio'):
            print(f"        前十大集中度: {holdings['total_ratio']}%")
            print(f"        报告期: {holdings.get('report_date')}")
            for h in holdings.get('holdings', [])[:5]:
                print(f"          {h['stock']} ({h['code']}): {h['ratio']}%")
            if len(holdings.get('holdings', [])) > 5:
                print(f"          ... 共{len(holdings['holdings'])}只")
        else:
            print("        [未解析到持仓数据]")
    else:
        print(f"        [获取失败] {holdings['error']}")

    # 2. 资产配置（股票仓位）
    print("  [2/3] 获取资产配置...")
    allocation = fetch_asset_allocation(fund_code)
    if 'error' not in allocation:
        result['股票仓位(%)'] = allocation.get('stock_ratio')
        result['债券占比(%)'] = allocation.get('bond_ratio')
        result['现金占比(%)'] = allocation.get('cash_ratio')
        result['资产配置报告期'] = allocation.get('report_date')

        if allocation.get('stock_ratio'):
            print(f"        股票仓位: {allocation['stock_ratio']}%")
            print(f"        债券占比: {allocation.get('bond_ratio')}%")
            print(f"        现金占比: {allocation.get('cash_ratio')}%")
            print(f"        报告期: {allocation.get('report_date')}")

            # 计算防御资产占比 = 债券 + 现金
            bond = allocation.get('bond_ratio', 0) or 0
            cash = allocation.get('cash_ratio', 0) or 0
            result['防御资产占比(%)'] = round(bond + cash, 2)
            print(f"        防御资产占比(债券+现金): {result['防御资产占比(%)']}%")
        else:
            print("        [未解析到资产配置数据]")
    else:
        print(f"        [获取失败] {allocation['error']}")

    # 3. 规模历史
    print("  [3/3] 获取规模历史...")
    scale_history = fetch_fund_scale_history(fund_code)
    if scale_history:
        latest = scale_history[0]
        result['当前规模(亿)'] = latest['scale']
        result['规模日期'] = latest['date']
        print(f"        最新规模: {latest['scale']}亿 ({latest['date']})")

        # 判断6个月内是否翻倍
        if len(scale_history) >= 2:
            # 找6个月前的规模
            from datetime import timedelta
            latest_date = datetime.strptime(latest['date'], '%Y-%m-%d')
            six_months_ago = latest_date - timedelta(days=180)

            prev_scale = None
            for s in scale_history:
                s_date = datetime.strptime(s['date'], '%Y-%m-%d')
                if s_date <= six_months_ago:
                    prev_scale = s['scale']
                    break

            if prev_scale and prev_scale > 0:
                if latest['scale'] / prev_scale >= 2:
                    result['6个月规模翻倍'] = '是'
                    print(f"        ⚠️ 6个月前规模{prev_scale}亿，已翻倍！")
                else:
                    result['6个月规模翻倍'] = '否'
                    print(f"        6个月前规模: {prev_scale}亿（未翻倍）")
    else:
        print("        [未获取到规模历史]")

    return result


if __name__ == '__main__':
    data = fetch_all_quarter_data()
    print("\n" + "=" * 60)
    print("  汇总:")
    for k, v in data.items():
        if k != '前十大持仓':
            print(f"    {k}: {v}")