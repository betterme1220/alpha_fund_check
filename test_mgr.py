import requests, re

url = "http://fund.eastmoney.com/pingzhongdata/180031.js"
headers = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "http://fund.eastmoney.com/180031.html"
}
resp = requests.get(url, headers=headers, timeout=10)
resp.encoding = 'utf-8'
text = resp.text

# 提取完整的 Data_currentFundManager
match = re.search(r'var Data_currentFundManager\s*=\s*(\[.*?\]);', text)
if match:
    print("完整经理数据:")
    print(match.group(1)[:1000])
else:
    print("没找到 Data_currentFundManager")

# 也找所有 name 字段
names = re.findall(r'"name":"([^"]+)"', text.split('Data_currentFundManager')[1].split(';')[0] if 'Data_currentFundManager' in text else '')
print(f"\n所有经理名字: {names}")