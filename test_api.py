import requests

# 测试前十大持仓接口
url = "http://fundf10.eastmoney.com/FundArchivesDatas.aspx"
params = {
    "type": "jjcc",
    "code": "180031",
    "topline": 10,
    "year": "",
    "month": "",
}
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "http://fundf10.eastmoney.com/ccmx_180031.html"
}

resp = requests.get(url, params=params, headers=headers, timeout=15)
resp.encoding = 'utf-8'
text = resp.text
print("=== 前十大持仓 (前2000字符) ===")
print(text[:2000])

print("\n\n")

# 测试资产配置接口
params2 = {
    "type": "jjzc",
    "code": "180031",
    "year": "",
}
headers2 = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "http://fundf10.eastmoney.com/zcpz_180031.html"
}

resp2 = requests.get(url, params=params2, headers=headers2, timeout=15)
resp2.encoding = 'utf-8'
text2 = resp2.text
print("=== 资产配置 (前2000字符) ===")
print(text2[:2000])