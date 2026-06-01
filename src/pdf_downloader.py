"""
PDF 公告下载存档模块
功能：下载基金公告PDF到本地，按日期归档
"""

import os
import sys
import re
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from excel_engine import load_config
from daily_check import fetch_fund_announcements


def get_download_dir(fund_code):
    """获取PDF存档目录"""
    config = load_config()
    base_dir = os.path.join(os.path.dirname(__file__), '..')
    download_dir = os.path.join(base_dir, config['data_raw_path'], fund_code, 'pdf')
    os.makedirs(download_dir, exist_ok=True)
    return download_dir


def sanitize_filename(name):
    """清理文件名中的非法字符"""
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    return name[:100]  # 限制长度


def download_pdf(url, save_path):
    """下载单个PDF文件"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "http://fund.eastmoney.com/"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=30, stream=True)
        if resp.status_code == 200:
            with open(save_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        else:
            print(f"  [失败] HTTP {resp.status_code}")
            return False
    except Exception as e:
        print(f"  [失败] {str(e)}")
        return False


def fetch_pdf_url_from_announcement(fund_code, announcement_id):
    """
    从公告详情页获取PDF下载链接
    东方财富公告PDF链接格式通常是：
    http://pdf.dfcfw.com/pdf/H2_公告ID_1.pdf
    """
    # 东方财富PDF链接的常见模式
    pdf_url = f"http://pdf.dfcfw.com/pdf/H2_{announcement_id}_1.pdf"
    return pdf_url


def download_recent_announcements(fund_code=None, count=10, keyword_filter=None):
    """
    下载最近的公告PDF

    参数：
        fund_code: 基金代码，默认用配置中的 active_fund
        count: 下载数量
        keyword_filter: 关键词过滤，只下载标题包含关键词的公告
    """
    if fund_code is None:
        config = load_config()
        fund_code = config['active_fund']

    download_dir = get_download_dir(fund_code)

    print("=" * 60)
    print(f"  PDF公告下载 | {fund_code}")
    print(f"  存档目录: {download_dir}")
    print("=" * 60)

    # 获取公告列表
    print("\n获取公告列表...")
    announcements = fetch_fund_announcements(fund_code)

    if not announcements:
        print("  未获取到公告")
        return

    # 关键词过滤
    if keyword_filter:
        announcements = [a for a in announcements if any(kw in a['title'] for kw in keyword_filter)]
        print(f"  关键词过滤后: {len(announcements)} 条")

    # 限制数量
    announcements = announcements[:count]

    print(f"\n准备下载 {len(announcements)} 条公告:\n")

    downloaded = 0
    skipped = 0

    for i, ann in enumerate(announcements, 1):
        title = ann['title']
        date = ann['date']
        url = ann['url']

        # 从URL中提取公告ID
        # URL格式: http://fund.eastmoney.com/gonggao/180031,AN202405281633825640.html
        ann_id = ""
        if ',' in url:
            ann_id = url.split(',')[-1].replace('.html', '')

        # 构造文件名
        filename = sanitize_filename(f"{date}_{title}.pdf")
        save_path = os.path.join(download_dir, filename)

        # 检查是否已下载
        if os.path.exists(save_path):
            print(f"  [{i}/{len(announcements)}] 已存在，跳过: {filename[:50]}...")
            skipped += 1
            continue

        # 获取PDF链接并下载
        if ann_id:
            pdf_url = fetch_pdf_url_from_announcement(fund_code, ann_id)
            print(f"  [{i}/{len(announcements)}] 下载: {title[:40]}...")

            if download_pdf(pdf_url, save_path):
                # 验证是否真的是PDF（检查文件头）
                with open(save_path, 'rb') as f:
                    header = f.read(4)
                if header == b'%PDF':
                    print(f"    ✓ 已保存: {filename[:50]}")
                    downloaded += 1
                else:
                    # 不是PDF，删除
                    os.remove(save_path)
                    print(f"    ✗ 非PDF文件，已删除")
            else:
                print(f"    ✗ 下载失败")
        else:
            print(f"  [{i}/{len(announcements)}] 无法解析公告ID: {title[:40]}")

    print(f"\n{'=' * 60}")
    print(f"  下载完成: 成功 {downloaded} | 跳过 {skipped} | 失败 {len(announcements) - downloaded - skipped}")
    print(f"  存档目录: {download_dir}")
    print(f"{'=' * 60}")


def download_important_announcements(fund_code=None):
    """
    只下载重要公告（季报、年报、基金经理变更等）
    """
    important_keywords = [
        "季度报告", "年度报告", "中期报告",
        "基金经理变更", "基金合同",
        "分红", "限制", "暂停"
    ]
    download_recent_announcements(
        fund_code=fund_code,
        count=20,
        keyword_filter=important_keywords
    )


# ============ 主入口 ============

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'important':
        download_important_announcements()
    else:
        download_recent_announcements()