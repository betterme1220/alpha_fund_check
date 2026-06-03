""" 
每日快检模块 
功能：从东方财富抓取关键信息，判断是否有一票否决风险 
增加：双绿灯机动仓信号检测 + 交易日下午2:30自动定时运行
增加：多源API备用（腾讯FQ→东财→网易），防连接重置
""" 
 
import sys 
import os 
import re 
import json 
import time
import random
import requests 
from datetime import datetime, timedelta, date
from bs4 import BeautifulSoup 
 
# 修正 Python 路径，确保能找到 src/ 下的项目模块
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'src'))

from excel_engine import append_to_sheet, load_config 
from rule_engine import get_fund_rules 
 
# 定时服务依赖（如需后台定时，请执行：pip install schedule）
try:
    import schedule
    SCHEDULE_AVAILABLE = True
except ImportError:
    SCHEDULE_AVAILABLE = False
 
 
# ============ 信号记录文件 ============ 
 
SIGNAL_LOG_PATH = os.path.join(os.path.dirname(__file__), "signal_log.json") 
 
 
def load_signal_log(): 
    """加载信号记录""" 
    if os.path.exists(SIGNAL_LOG_PATH): 
        with open(SIGNAL_LOG_PATH, 'r', encoding='utf-8') as f: 
            return json.load(f) 
    return {} 
 
 
def save_signal_log(data): 
    """保存信号记录""" 
    with open(SIGNAL_LOG_PATH, 'w', encoding='utf-8') as f: 
        json.dump(data, f, ensure_ascii=False, indent=2) 
 
 
def get_last_signal_date(signal_name): 
    """获取某信号上次触发日期""" 
    log = load_signal_log() 
    return log.get(signal_name, None) 
 
 
def update_signal_date(signal_name, date_str): 
    """更新信号触发日期""" 
    log = load_signal_log() 
    log[signal_name] = date_str 
    save_signal_log(log) 
 
 
# ============ 请求加固：随机UA + 重试机制 ============

USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36 Edg/109.0.1518.78",
]

def get_headers(referer="http://quote.eastmoney.com/"):
    """生成带随机UA的请求头"""
    return {
        "User-Agent": random.choice(USER_AGENT_POOL),
        "Referer": referer,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


def request_with_retry(url, params=None, headers=None, retries=3, backoff=1.0, timeout=10):
    """带指数退避的重试请求"""
    last_err = None
    for i in range(retries):
        try:
            resp = requests.get(
                url, 
                params=params, 
                headers=headers or get_headers(), 
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            wait = backoff * (i + 1) + random.uniform(0, 0.5)
            time.sleep(wait)
    raise last_err


# ============ 板块对比：银行 vs 科技 ============ 
 
# 中证银行 399986 (深圳) 
BANK_SECID = "0.399986" 
# 中证科技龙头 931087 (国证/中证跨市场，用 "1.931087") 
TECH_SECID = "1.931087" 
# 对比周期：10个交易日 
COMPARE_DAYS = 10 


def secid_to_tencent(secid: str) -> str:
    """东财 secid 转 腾讯代码: 0.399986 -> sz399986"""
    if secid.startswith("0."):
        return "sz" + secid.split(".")[1]
    elif secid.startswith("1."):
        return "sh" + secid.split(".")[1]
    return secid

def secid_to_163(secid: str) -> str:
    """东财 secid 转 网易代码: 深圳1+code，上海0+code"""
    if secid.startswith("0."):
        return "1" + secid.split(".")[1]
    elif secid.startswith("1."):
        return "0" + secid.split(".")[1]
    return secid

def _parse_return(first_close: float, last_close: float) -> float:
    if first_close == 0:
        return 0.0
    return round((last_close - first_close) / first_close * 100, 2)


# ---------- API 1: 腾讯财经 FQK 线（最稳定，不限IP） ----------
def _fetch_tencent_kline(secid, days=COMPARE_DAYS):
    code = secid_to_tencent(secid)
    url = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": f"{code},day,,,{days},qfq"}
    try:
        resp = request_with_retry(url, params=params, headers=get_headers("http://stockpage.10jqka.com.cn/"), timeout=10)
        data = resp.json()
        stock_data = data.get("data", {}).get(code, {})
        klines = stock_data.get("day", []) or stock_data.get("qfqday", [])
        if len(klines) < 2:
            return None
        recent = klines[-days:] if len(klines) >= days else klines
        first_close = float(recent[0][2])
        last_close = float(recent[-1][2])
        return _parse_return(first_close, last_close)
    except Exception as e:
        print(f"  [腾讯备用] 获取失败({secid}): {e}")
        return None


# ---------- API 2: 东方财富（原接口+重试） ----------
def _fetch_eastmoney_kline(secid, days=COMPARE_DAYS):
    url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": days + 5,
    }
    try:
        resp = request_with_retry(
            url, params=params, headers=get_headers("http://quote.eastmoney.com/"),
            retries=3, backoff=1.5, timeout=15,
        )
        data = resp.json()
        klines = data.get('data', {}).get('klines', [])
        if len(klines) < 2:
            return None
        recent = klines[-days:] if len(klines) >= days else klines
        first_close = float(recent[0].split(',')[2])
        last_close = float(recent[-1].split(',')[2])
        return _parse_return(first_close, last_close)
    except Exception as e:
        print(f"  [东财主源] 获取失败({secid}): {e}")
        return None


# ---------- API 3: 网易财经 CSV（兜底） ----------
def _fetch_163_csv(secid, days=COMPARE_DAYS):
    code = secid_to_163(secid)
    end_date = date.today().strftime("%Y%m%d")
    start_dt = date.today() - timedelta(days=days * 2 + 10)
    start_date = start_dt.strftime("%Y%m%d")
    url = "http://quotes.money.163.com/service/chddata.html"
    params = {
        "code": code,
        "start": start_date,
        "end": end_date,
        "fields": "TCLOSE",
    }
    try:
        resp = request_with_retry(url, params=params, headers=get_headers("http://quotes.money.163.com/"), timeout=15)
        resp.encoding = 'utf-8'
        lines = resp.text.strip().splitlines()
        if len(lines) < 3:
            return None
        # 网易CSV第一行是最新日期，按顺序：日期,代码,名称,收盘,...
        data_lines = lines[1:]
        recent = data_lines[:days] if len(data_lines) >= days else data_lines
        first_close = float(recent[-1].split(',')[3])
        last_close = float(recent[0].split(',')[3])
        return _parse_return(first_close, last_close)
    except Exception as e:
        print(f"  [网易兜底] 获取失败({secid}): {e}")
        return None


def fetch_sector_return(secid, days=COMPARE_DAYS): 
    """获取板块指数近N个交易日涨幅（多源优先：腾讯 → 东财 → 网易）""" 
    ret = _fetch_tencent_kline(secid, days)
    if ret is not None:
        return ret
    ret = _fetch_eastmoney_kline(secid, days)
    if ret is not None:
        return ret
    ret = _fetch_163_csv(secid, days)
    if ret is not None:
        return ret
    return None
 
 
def check_bank_vs_tech(): 
    """判断银行是否强于科技（近10个交易日）""" 
    print(f"  对比周期: 近{COMPARE_DAYS}个交易日") 
    print(f"  银行代表: 中证银行(399986)") 
    print(f"  科技代表: 中证科技龙头(931087)") 
 
    bank_ret = fetch_sector_return(BANK_SECID, COMPARE_DAYS) 
    tech_ret = fetch_sector_return(TECH_SECID, COMPARE_DAYS) 
 
    if tech_ret is None: 
        print(f"  [降级] 科技龙头接口失败，尝试中证信息技术(399363)") 
        tech_ret = fetch_sector_return("0.399363", COMPARE_DAYS) 
 
    if bank_ret is None or tech_ret is None: 
        print(f"  [警告] 板块数据获取不完整 bank={bank_ret}, tech={tech_ret}") 
        return None, bank_ret, tech_ret 
 
    bank_stronger = bank_ret > tech_ret 
    return bank_stronger, bank_ret, tech_ret 
 

# ============ 净值回撤计算 ============ 
 
def fetch_nav_history(fund_code, days=120): 
    """获取基金净值历史数据，用于计算回撤""" 
    url = f"http://fund.eastmoney.com/pingzhongdata/{fund_code}.js" 
    headers = get_headers(f"http://fund.eastmoney.com/{fund_code}.html")
    try: 
        resp = request_with_retry(url, headers=headers, retries=2, timeout=15)
        text = resp.text 
        pattern = r'\{"x":(\d+),"y":([\d.]+),"equityReturn":([\d.-]+),"unitMoney":"([^"]*)"\}' 
        matches = re.findall(pattern, text) 
        if not matches: 
            return [] 
        nav_list = [] 
        for m in matches[-days:]: 
            timestamp_ms = int(m[0]) 
            nav = float(m[1]) 
            date_str = datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d") 
            nav_list.append({"date": date_str, "nav": nav}) 
        return nav_list 
    except Exception as e: 
        print(f"  [错误] 获取净值历史失败: {e}") 
        return [] 
 
 
def calc_max_drawdown_from_peak(nav_list): 
    """计算当前净值相对于近期最高点的回撤""" 
    if not nav_list or len(nav_list) < 2: 
        return None, None, None, None 
    peak_nav = 0 
    peak_date = "" 
    for item in nav_list: 
        if item['nav'] >= peak_nav: 
            peak_nav = item['nav'] 
            peak_date = item['date'] 
    current_nav = nav_list[-1]['nav'] 
    if peak_nav == 0: 
        return None, None, None, None 
    drawdown = (peak_nav - current_nav) / peak_nav * 100 
    return round(drawdown, 2), peak_nav, peak_date, current_nav 
 

# ============ 双绿灯信号判定 ============ 
 
def check_double_green_signal(fund_code, trading_days_interval=5): 
    """双绿灯判定：银行不强于科技 + 回撤>=8% + 冷却期""" 
    print("\n[附加] 双绿灯机动仓检测...") 
    print("-" * 40) 
 
    result = { 
        "triggered": False, 
        "bank_stronger": None, 
        "drawdown": None, 
        "cooldown_ok": False, 
        "message": "" 
    } 
 
    # 条件1: 银行 vs 科技 
    print("  检测条件①: 银行是否强于科技...") 
    bank_stronger, bank_ret, tech_ret = check_bank_vs_tech() 
 
    if bank_stronger is None: 
        result["message"] = "板块数据获取失败，跳过" 
        print(f"  {result['message']}") 
        return result 
 
    result["bank_stronger"] = bank_stronger 
    status1 = "❌ 银行强于科技" if bank_stronger else "✅ 银行不强于科技" 
    print(f"    银行近{COMPARE_DAYS}日: {bank_ret:+.2f}%") 
    print(f"    科技近{COMPARE_DAYS}日: {tech_ret:+.2f}%") 
    print(f"    判定: {status1}") 
 
    # 条件2: 净值回撤 
    print("  检测条件②: 净值回撤是否≥8%...") 
    nav_list = fetch_nav_history(fund_code, days=120) 
    drawdown, peak_nav, peak_date, current_nav = calc_max_drawdown_from_peak(nav_list) 
 
    if drawdown is None: 
        result["message"] = "净值数据获取失败，跳过" 
        print(f"  {result['message']}") 
        return result 
 
    result["drawdown"] = drawdown 
    drawdown_ok = drawdown >= 8.0 
    status2 = f"✅ 回撤{drawdown:.2f}% ≥ 8%" if drawdown_ok else f"❌ 回撤{drawdown:.2f}% < 8%" 
    print(f"    近期高点: {peak_nav:.4f} ({peak_date})") 
    print(f"    当前净值: {current_nav:.4f}") 
    print(f"    当前回撤: {drawdown:.2f}%") 
    print(f"    判定: {status2}") 
 
    # 双绿灯判定 
    both_green = (not bank_stronger) and drawdown_ok 
 
    if not both_green: 
        reasons = [] 
        if bank_stronger: 
            reasons.append("银行强于科技") 
        if not drawdown_ok: 
            reasons.append(f"回撤不足8%(当前{drawdown:.2f}%)") 
        result["message"] = f"双绿灯未触发: {', '.join(reasons)}" 
        print(f"\n  结论: {result['message']}") 
        return result 
 
    # 条件3: 冷却间隔检查 
    print("  检测条件③: 冷却间隔≥5个交易日...") 
    last_signal = get_last_signal_date("double_green") 
    today_str = datetime.now().strftime("%Y-%m-%d") 
 
    if last_signal: 
        last_date = datetime.strptime(last_signal, "%Y-%m-%d") 
        today_date = datetime.strptime(today_str, "%Y-%m-%d") 
        calendar_days = (today_date - last_date).days 
        approx_trading_days = int(calendar_days * 5 / 7) 
 
        print(f"    上次信号: {last_signal}") 
        print(f"    间隔: ~{approx_trading_days}个交易日 (自然日{calendar_days}天)") 
 
        if approx_trading_days < trading_days_interval: 
            result["cooldown_ok"] = False 
            result["message"] = f"双绿灯已触发但冷却中(距上次~{approx_trading_days}交易日 < {trading_days_interval})" 
            print(f"    判定: ❌ 冷却期内，不重复提示") 
            print(f"\n  结论: {result['message']}") 
            return result 
 
    result["cooldown_ok"] = True 
    result["triggered"] = True 
    result["message"] = f"🟢🟢 双绿灯触发！可加机动仓 | 回撤{drawdown:.2f}% + 科技占优(近{COMPARE_DAYS}日)" 
 
    update_signal_date("double_green", today_str) 
 
    print(f"    判定: ✅ 冷却期已过") 
    print(f"\n  {'='*40}") 
    print(f"  🟢🟢 双绿灯触发！建议可加机动仓") 
    print(f"       回撤: {drawdown:.2f}% (≥8%)") 
    print(f"       板块: 科技({tech_ret:+.2f}%) 优于 银行({bank_ret:+.2f}%) [近{COMPARE_DAYS}日]") 
    print(f"  {'='*40}") 
 
    return result 
 

# ============ 数据抓取 ============ 
 
# 过滤脏数据
_NOT_MANAGER_NAMES = {"期间申购", "期间赎回", "总份额", "单位净值", "累计净值", "分红"}

def fetch_fund_managers(fund_code): 
    """获取当前基金经理列表（过滤非人名脏数据）""" 
    url = f"http://fund.eastmoney.com/pingzhongdata/{fund_code}.js" 
    headers = get_headers(f"http://fund.eastmoney.com/{fund_code}.html")
    try: 
        resp = request_with_retry(url, headers=headers, retries=2, timeout=15)
        text = resp.text 
        match = re.search(r'var Data_currentFundManager\s*=\s*(\[.*?\]);', text) 
        if match: 
            manager_text = match.group(1) 
            names = re.findall(r'"name":"([^"]+)"', manager_text) 
            names = [n for n in names if n not in _NOT_MANAGER_NAMES]
            return names if names else [] 
        return [] 
    except Exception as e: 
        print(f"  [错误] 获取经理信息失败: {e}") 
        return [] 
 
 
def fetch_fund_nav(fund_code): 
    """从东方财富接口获取最新净值""" 
    url = f"http://fund.eastmoney.com/pingzhongdata/{fund_code}.js" 
    headers = get_headers(f"http://fund.eastmoney.com/{fund_code}.html")
    try: 
        resp = request_with_retry(url, headers=headers, retries=2, timeout=15)
        text = resp.text 
        result = {} 
        if 'Data_netWorthTrend' in text: 
            pattern = r'\{"x":(\d+),"y":([\d.]+),"equityReturn":([\d.-]+),"unitMoney":"([^"]*)"\}' 
            matches = re.findall(pattern, text) 
            if matches: 
                last = matches[-1] 
                timestamp_ms = int(last[0]) 
                nav_date = datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d") 
                result['nav'] = float(last[1]) 
                result['date'] = nav_date 
                result['daily_return'] = last[2] 
        if 'Data_ACWorthTrend' in text: 
            pattern = r'\[(\d+),([\d.]+)\]' 
            matches = re.findall(pattern, text.split('Data_ACWorthTrend')[1].split(';')[0]) 
            if matches: 
                last = matches[-1] 
                result['acc_nav'] = float(last[1]) 
        return result if result else {"error": "解析失败"} 
    except Exception as e: 
        return {"error": str(e)} 
 
 
def fetch_fund_announcements(fund_code, page=1): 
    """从东方财富获取基金公告列表""" 
    url = f"http://api.fund.eastmoney.com/f10/JJGG" 
    params = { 
        "fundcode": fund_code, 
        "pageIndex": page, 
        "pageSize": 10, 
        "type": 0, 
    } 
    headers = get_headers(f"http://fundf10.eastmoney.com/jjgg_{fund_code}.html")
    try: 
        resp = request_with_retry(url, params=params, headers=headers, retries=2, timeout=15)
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
    """检查公告标题中是否包含风险关键词""" 
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
                break 
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
    print("\n[1/4] 抓取基金经理名单...") 
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
    print("\n[2/4] 抓取最新净值...") 
    nav_data = fetch_fund_nav(fund_code) 
    if 'error' not in nav_data: 
        print(f"  最新净值: {nav_data.get('nav')} ({nav_data.get('date')})") 
        if nav_data.get('acc_nav'): 
            print(f"  累计净值: {nav_data.get('acc_nav')}") 
    else: 
        print(f"  [获取失败] {nav_data.get('error')}") 
 
    # 3. 检查最新公告 
    print("\n[3/4] 抓取最新公告...") 
    announcements = fetch_fund_announcements(fund_code) 
    if announcements: 
        print(f"  最近{len(announcements)}条公告:") 
        for ann in announcements[:5]: 
            print(f"    {ann['date']} | {ann['title']}") 
 
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
 
    # 4. 双绿灯机动仓检测 
    print("\n[4/4] 双绿灯机动仓检测...") 
    signal = check_double_green_signal(fund_code) 
 
    if signal["triggered"]: 
        alerts.append({ 
            "type": "绿灯(加仓)", 
            "rule": "双绿灯机动仓信号", 
            "detail": signal["message"], 
            "action": "可加机动仓位(需人工确认)" 
        }) 
 
    # 5. 汇总结果 
    print("\n" + "=" * 60) 
    if alerts: 
        print(f"  共 {len(alerts)} 个提醒:") 
        for a in alerts: 
            print(f"  [{a['type']}] {a['rule']}: {a['detail']}") 
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
        print("  ✓ 一切正常，无警报，无加仓信号") 
    print("=" * 60) 
 
    return alerts 
 

# ============ 定时服务与交易日判断 ============ 
 
def is_trading_day(): 
    """判断是否为交易日。默认排除周末；如需精确节假日，请安装 chinese-calendar""" 
    weekday = datetime.now().weekday() 
    if weekday >= 5: 
        return False 
    # import chinese_calendar as cc
    # return cc.is_workday(datetime.now())
    return True 
 
 
def timed_job(): 
    """定时任务包装器：仅交易日执行，并捕获异常防止中断调度""" 
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S") 
    if not is_trading_day(): 
        print(f"\n[{now}] ⏸️ 非交易日，跳过今日快检") 
        return 
    print(f"\n[{now}] ⏰ 交易日下午 2:30，启动每日快检...") 
    try: 
        run_daily_check() 
    except Exception as e: 
        print(f"[{now}] ❌ 执行异常: {e}") 
 
 
def start_scheduler(run_immediately=False, run_time="14:30"): 
    """启动定时调度服务""" 
    if not SCHEDULE_AVAILABLE:
        print("=" * 60)
        print("请先安装 schedule 库：")
        print("    pip install schedule")
        print("如需精确 A 股节假日判断，额外安装：")
        print("    pip install chinese-calendar")
        print("=" * 60)
        sys.exit(1)

    schedule.every().day.at(run_time).do(timed_job) 
 
    if run_immediately: 
        print("⚡ 立即执行一次快检...") 
        timed_job() 
 
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 🕐 定时服务已启动") 
    print(f"   规则：每日 {run_time} 执行（仅交易日）") 
    print("   操作：按 Ctrl+C 停止服务\n") 
 
    while True: 
        schedule.run_pending() 
        time.sleep(30) 
 
 
if __name__ == '__main__': 
    if "--once" in sys.argv:
        print("⚡ 单次快检模式...")
        run_daily_check()
        print(f"\n[{datetime.now().strftime('%H:%M')}] ✅ 单次检测完成，已退出")
    elif "--now" in sys.argv: 
        start_scheduler(run_immediately=True) 
    else: 
        start_scheduler(run_immediately=False)