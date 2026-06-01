"""
每日快检模块
功能：从东方财富抓取关键信息，判断是否有一票否决风险
"""

import sys
import os
import json
import requests
from datetime import datetime
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))

from excel_engine import append_to_sheet, load_config
from rule_engine import get_fund_rules


# ============ 数据抓取 ============

def fetch_fund_managers(fund_code):
    """
    从东方财富基金档案页抓取当前基金经理名单
    返回：list of str，如 ["李晓星", "张萍", "杜宇"]
    """
    url = f"http://fund.eastmoney.com/{fund_code}.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 东方财富基金页面，基金经理在 class="infoOfFund" 的 table 里
        info_div = soup.find('div', class_='infoOfFund')
        if info_div:
            # 找包含"基金经理"的行
            for td in info_div.find_all('td'):
                text = td.get_text()
                if '基金经理' in text:
                    # 提取经理名字（在 <a> 标签里）
                    managers = [a.get_text().strip() for a in td.find_all('a')]
                    if managers:
                        return managers

        # 备用方案：从页面文本中搜索
        page_text = soup.get_text()
        if '基金经理' in page_text:
            return ["[页面已获取但解析失败，请人工确认]"]

        return ["[未能获取基金经理信息]"]

    except Exception as e:
        return [f"[抓取失败: {str(e)}]"]


def fetch_fund_nav(fund_code):
    """
    从东方财富接口获取最新净值和规模
    返回：dict {"nav": 净值, "acc_nav": 累计净值, "date": 日期, "scale": 规模}
    """
    # 东方财富基金净值接口
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

        # 提取最新净值数据
        # 格式：var Data_netWorthTrend = [{x:时间戳,y:净值,equityReturn:涨幅,unitMoney:""},...];
        if 'Data_netWorthTrend' in text:
            import re
            # 找最后一个数据点
            pattern = r'\{"x":(\d+),"y":([\d.]+),"equityReturn":([\d.-]+),"unitMoney":"([^"]*)"\}'
            matches = re.findall(pattern, text)
            if matches:
                last = matches[-1]
                timestamp_ms = int(last[0])
                nav_date = datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d")
                result['nav'] = float(last[1])
                result['date'] = nav_date
                result['daily_return'] = last[2]

        # 提取累计净值
        if 'Data_ACWorthTrend' in text:
            import re
            pattern = r'\[(\d+),([\d.]+)\]'
            matches = re.findall(pattern, text.split('Data_ACWorthTrend')[1].split(';')[0])
            if matches:
                last = matches[-1]
                result['acc_nav'] = float(last[1])

        return result if result else {"error": "解析失败"}

    except Exception as e:
        return {"error": str(e)}


def fetch_fund_announcements(fund_code, page=1):
    """
    从东方财富获取基金公告列表
    返回：list of dict [{"title": 标题, "date": 日期, "url": 链接}, ...]
    """
    url = f"http://api.fund.eastmoney.com/f10/JJGG"
    params = {
        "fundcode": fund_code,
        "pageIndex": page,
        "pageSize": 10,
        "type": 0,  # 0=全部公告
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"http://fundf10.eastmoney.com/jjgg_{fund_code}.html"
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()

        announcements = []
        if data.get('Data'):
            for item in data['Data']:
                announcements.append({
                    "title": item.get('TITLE', ''),
                    "date": item.get('PUBLISHDATE', '')[:10],
                    "url": f"http://fund.eastmoney.com/gonggao/{fund_code},{item.get('ID', '')}.html"
                })
        return announcements

    except Exception as e:
        return [{"title": f"[抓取失败: {str(e)}]", "date": "", "url": ""}]


# ============ 风险关键词检测 ============

RISK_KEYWORDS = [
    "基金经理变更",
    "基金经理离任",
    "基金合同修改",
    "基金合同变更",
    "清盘",
    "终止",
    "转型",
    "限制大额申购",
    "暂停申购",
    "监管",
    "处罚",
    "整改",
    "风险提示",
]


def check_announcement_risks(announcements):
    """
    检查公告标题中是否包含风险关键词
    返回：list of dict，触发的风险公告
    """
    risks = []
    for ann in announcements:
        title = ann.get('title', '')
        for keyword in RISK_KEYWORDS:
            if keyword in title:
                risks.append({
                    "keyword": keyword,
                    "title": title,
                    "date": ann.get('date', ''),
                    "url": ann.get('url', '')
                })
                break  # 一个公告只报一次
    return risks


# ============ 主流程 ============

def run_daily_check():
    """执行每日快检"""
    config = load_config()
    fund_code = config['active_fund']
    fund_info = config['funds'][fund_code]
    fund_name = fund_info['name']
    key_person = fund_info['manager_key_person']

    print("=" * 60)
    print(f"  每日快检 | {fund_code} {fund_name}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    alerts = []

    # 1. 检查基金经理
    print("\n[1/3] 抓取基金经理名单...")
    managers = fetch_fund_managers(fund_code)
    print(f"  当前基金经理: {', '.join(managers)}")

    if key_person not in managers:
        alert = f"⚠️ 红灯警报: {key_person} 不在基金经理名单中！"
        print(f"  {alert}")
        alerts.append({
            "type": "红灯",
            "rule": "核心基金经理离任",
            "detail": f"{key_person}不在当前经理名单: {managers}",
            "action": "立即确认，30个交易日内清仓"
        })
    else:
        print(f"  ✓ {key_person} 在任")

    # 2. 检查最新净值
    print("\n[2/3] 抓取最新净值...")
    nav_data = fetch_fund_nav(fund_code)
    if 'error' not in nav_data:
        print(f"  最新净值: {nav_data.get('nav')} ({nav_data.get('date')})")
        if nav_data.get('acc_nav'):
            print(f"  累计净值: {nav_data.get('acc_nav')}")
    else:
        print(f"  [获取失败] {nav_data.get('error')}")

    # 3. 检查最新公告
    print("\n[3/3] 抓取最新公告...")
    announcements = fetch_fund_announcements(fund_code)
    if announcements:
        print(f"  最近{len(announcements)}条公告:")
        for ann in announcements[:5]:
            print(f"    {ann['date']} | {ann['title']}")

        # 关键词检测
        risks = check_announcement_risks(announcements)
        if risks:
            print(f"\n  ⚠️ 发现 {len(risks)} 条风险公告:")
            for r in risks:
                print(f"    [{r['keyword']}] {r['title']} ({r['date']})")
                alerts.append({
                    "type": "黄灯",
                    "rule": f"公告关键词触发: {r['keyword']}",
                    "detail": r['title'],
                    "action": "人工复核公告内容"
                })
        else:
            print(f"\n  ✓ 公告无风险关键词")
    else:
        print("  [未获取到公告]")

    # 4. 汇总结果
    print("\n" + "=" * 60)
    if alerts:
        print(f"  ⚠️ 发现 {len(alerts)} 个警报！")
        for a in alerts:
            print(f"  [{a['type']}] {a['rule']}: {a['detail']}")
            # 写入执行记录
            record = {
                "触发日期": datetime.now().strftime("%Y-%m-%d"),
                "事件来源": "每日快检",
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
        print("  ✓ 一切正常，无警报")
    print("=" * 60)

    return alerts


if __name__ == '__main__':
    run_daily_check()