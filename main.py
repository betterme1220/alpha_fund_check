"""
Alpha Fund Check 统一入口
用法：
    python main.py daily          每日快检
    python main.py quarterly      季度检查（交互式）
    python main.py monthly        月度检查
    python main.py status         查看当前状态
"""

import sys
import os

# 确保 src 目录在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def show_status():
    """显示当前基金监控状态"""
    from excel_engine import load_config, get_sheet_columns, read_sheet

    config = load_config()
    fund_code = config['active_fund']
    fund_info = config['funds'][fund_code]

    print("=" * 60)
    print("  Alpha Fund Check 当前状态")
    print("=" * 60)
    print(f"  监控基金: {fund_code} {fund_info['name']}")
    print(f"  核心经理: {fund_info['manager_key_person']}")
    print(f"  规模上限: {fund_info['scale_upper_limit']}亿")
    print(f"  回撤阈值: {fund_info['max_drawdown_threshold']}%")
    print(f"  连续跑输上限: {fund_info['underperform_quarters_limit']}季度")
    print("=" * 60)

    # 读取最近一次季度检查
    try:
        df = read_sheet('季度检查表')
        # 过滤掉空行
        df = df.dropna(subset=['报告期'])
        if not df.empty:
            last = df.iloc[-1]
            print(f"\n  最近一次检查:")
            print(f"    报告期: {last.get('报告期', 'N/A')}")
            print(f"    结论: {last.get('本期结论', 'N/A')}")
            print(f"    观察触发数: {last.get('观察触发数', 'N/A')}")
        else:
            print("\n  暂无季度检查记录")
    except Exception as e:
        print(f"\n  读取季度检查表失败: {e}")

    print("=" * 60)


def show_help():
    """显示帮助信息"""
    print("""
Alpha Fund Check - 主动基金风控监控系统
==========================================

用法: python main.py <命令>

可用命令:
  daily       每日快检（抓取经理/净值/公告，检测风险）
  quarterly   季度检查（交互式录入数据，自动判定，回写大表）
  monthly     月度检查（回撤/相对收益/规模跟踪）
  pdf         下载最近公告PDF
  pdf-important  只下载重要公告（季报/年报/经理变更）
  status      查看当前监控状态
  help        显示此帮助

示例:
  python main.py daily
  python main.py quarterly
  python main.py status
""")


def main():
    if len(sys.argv) < 2:
        show_help()
        return

    command = sys.argv[1].lower()

    if command == 'daily':
        from daily_check import run_daily_check
        run_daily_check()

    elif command == 'quarterly':
        from quarterly_check import run_quarterly_check
        run_quarterly_check()

    elif command == 'monthly':
        from monthly_check import run_monthly_check
        run_monthly_check()

    elif command == 'pdf':
        from pdf_downloader import download_recent_announcements
        download_recent_announcements()

    elif command == 'pdf-important':
        from pdf_downloader import download_important_announcements
        download_important_announcements()
    elif command == 'status':
        show_status()

    elif command == 'pool':
        from pool_manager import run_pool_scan
        run_pool_scan()
        
    elif command == 'help':
        show_help()

    else:
        print(f"[错误] 未知命令: {command}")
        show_help()


if __name__ == '__main__':
    main()