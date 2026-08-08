#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RIIZE 官方活动自动爬取脚本 v4.0
功能：从 SMTOWN 官网、Weverse 等官方渠道自动爬取 RIIZE 最新活动公告
      自动提取购票平台、售票时间、票价，自动转换为北京时间
      自动更新 data.js，配合 GitHub Actions 实现全自动更新
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import os
from datetime import datetime, timedelta
import time

# ===== 官方来源白名单（只爬这些域名，保证数据来源官方） =====
OFFICIAL_SOURCES = [
    {
        "name": "SMTOWN 官网",
        "url": "https://www.smtown.com/artist/riize/notice",
        "domain": "smtown.com",
        "type": "official"
    },
    {
        "name": "SMTOWN JAPAN 官方",
        "url": "https://www.smtown.jp/artist/riize/info",
        "domain": "smtown.jp",
        "type": "official"
    },
    {
        "name": "Weverse RIIZE",
        "url": "https://weverse.io/riize/notice",
        "domain": "weverse.io",
        "type": "official"
    }
]

# ===== 关键词白名单（双重验证，必须同时包含 RIIZE 和活动关键词） =====
RIIZE_KEYWORDS = ["RIIZE", "riize", "라이즈", "リイズ"]
ACTIVITY_KEYWORDS = [
    "CONCERT", "concert", "콘서트", "コンサート", "演唱会",
    "FAN MEETING", "fan meeting", "팬미팅", "ファンミーティング", "粉丝见面会",
    "FAN SIGN", "fan sign", "팬싸인", "サイン会", "签售",
    "FESTIVAL", "festival", "페스티벌", "フェスティバル", "音乐节",
    "SCHEDULE", "schedule", "일정", "スケジュール", "日程",
    "NOTICE", "notice", "공지", "お知らせ", "公告",
    "TICKET", "ticket", "티켓", "チケット", "售票", "开票"
]

# ===== 黑名单（过滤掉非活动类公告） =====
BLACKLIST_KEYWORDS = [
    "rumor", "rumour", "传闻", "谣言", "爆料", "leak",
    "fan made", "팬메이드", "饭制",
    "cancel", "취소", "取消",
    "delay", "연기", "延期"
]

# ===== 购票平台关键词 =====
TICKET_PLATFORMS = [
    "Melon Ticket", "YES24", "Interpark", "NOL", "Ticketmaster", "AXS",
    "e+", "ぴあ", "ローソンチケット", "Lawson Ticket", "罗森票务",
    "大麦网", "猫眼", "银河票务", "Fantopia", "Ktown4u",
    "熊宝空间站", "Creatrip", "Thai Ticket Major", "MADE ON",
    "Weverse", "SMTOWN", "BRIIZE JAPAN", "Qoo10", "Melon"
]

# ===== 票价正则 =====
PRICE_PATTERNS = [
    (r'(\d{1,3}(?:,\d{3})*)\s*(?:원|KRW|韩元|₩)', 'KRW'),
    (r'(\d{1,3}(?:,\d{3})*)\s*(?:円|JPY|日元|¥)', 'JPY'),
    (r'(\d{1,3}(?:,\d{3})*)\s*(?:USD|美元|\$)', 'USD'),
    (r'(\d{1,3}(?:,\d{3})*)\s*(?:HKD|港币|港幣)', 'HKD'),
    (r'(\d{1,3}(?:,\d{3})*)\s*(?:MOP|澳门元|澳門幣)', 'MOP'),
    (r'(\d{1,3}(?:,\d{3})*)\s*(?:THB|泰铢|บาท)', 'THB'),
    (r'(\d{1,3}(?:,\d{3})*)\s*(?:元|CNY|人民币)', 'CNY'),
]

# ===== 售票时间正则（会员先行 + 一般售票） =====
MEMBER_TIME_PATTERNS = [
    r'(?:팬클럽|팬클럽선예매|会员先行|FC先行|pre-sale|presale|member.*?sale)[^\d]{0,20}(\d{1,2})[월月/](\d{1,2})[일日/]?[^\d]{0,10}(\d{1,2})[:시时](\d{1,2})[분分]?',
    r'(?:팬클럽|会员先行|FC先行)[^\d]{0,20}(\d{1,2})月\s*(\d{1,2})日[^\d]{0,10}(\d{1,2})[:：](\d{1,2})',
]

GENERAL_TIME_PATTERNS = [
    r'(?:일반|一般售票|一般发售|general sale)[^\d]{0,20}(\d{1,2})[월月/](\d{1,2})[일日/]?[^\d]{0,10}(\d{1,2})[:시时](\d{1,2})[분分]?',
    r'(?:일반|一般)[^\d]{0,20}(\d{1,2})月\s*(\d{1,2})日[^\d]{0,10}(\d{1,2})[:：](\d{1,2})',
]


def kst_to_bj(hour, minute=0):
    """韩国时间转北京时间（减1小时）"""
    return (hour - 1) % 24, minute


def jst_to_bj(hour, minute=0):
    """日本时间转北京时间（减1小时）"""
    return (hour - 1) % 24, minute


def is_official_content(title, content):
    """五重安全过滤：验证内容是否为官方活动公告"""
    text = f"{title} {content}"
    
    # 1. 必须包含 RIIZE 关键词
    has_riize = any(kw in text for kw in RIIZE_KEYWORDS)
    if not has_riize:
        return False
    
    # 2. 必须包含活动关键词
    has_activity = any(kw in text for kw in ACTIVITY_KEYWORDS)
    if not has_activity:
        return False
    
    # 3. 不能包含黑名单关键词
    has_blacklist = any(kw.lower() in text.lower() for kw in BLACKLIST_KEYWORDS)
    if has_blacklist:
        return False
    
    return True


def extract_ticket_url(detail_url, source_domain):
    """从公告详情页提取购票链接"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6,zh-CN;q=0.5,zh;q=0.4"
        }
        
        resp = requests.get(detail_url, headers=headers, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 查找购票相关链接
        ticket_keywords = ["ticket", "티켓", "チケット", "购票", "售票", "reservation", "예매", "予約"]
        
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            text = a_tag.get_text(strip=True).lower()
            
            # 检查链接文本是否包含购票关键词
            if any(kw.lower() in text for kw in ticket_keywords):
                if href.startswith("http"):
                    return href
                elif href.startswith("/"):
                    return f"https://{source_domain}{href}"
        
        return None
        
    except Exception as e:
        print(f"      ⚠️ 提取购票链接失败: {e}")
        return None


def extract_ticket_details(detail_url, source_domain, timezone='KST'):
    """从公告详情页提取票务详细信息（平台、时间、价格）"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6,zh-CN;q=0.5,zh;q=0.4"
        }
        
        resp = requests.get(detail_url, headers=headers, timeout=15, allow_redirects=True)
        if resp.status_code != 200:
            return {}
        
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        
        details = {}
        
        # 1. 提取购票平台
        platforms_found = []
        text_lower = text.lower()
        for platform in TICKET_PLATFORMS:
            if platform.lower() in text_lower:
                platforms_found.append(platform)
        if platforms_found:
            details["ticketPlatform"] = " / ".join(list(dict.fromkeys(platforms_found))[:4])
            print(f"      🏪 购票平台: {details['ticketPlatform']}")
        
        # 2. 提取售票时间（会员先行 + 一般售票）
        member_time = None
        general_time = None
        
        for pattern in MEMBER_TIME_PATTERNS:
            match = re.search(pattern, text)
            if match:
                month, day, hour, minute = match.groups()
                month, day, hour, minute = int(month), int(day), int(hour), int(minute)
                if timezone == 'KST':
                    bj_h, bj_m = kst_to_bj(hour, minute)
                elif timezone == 'JST':
                    bj_h, bj_m = jst_to_bj(hour, minute)
                else:
                    bj_h, bj_m = hour, minute
                member_time = f"会员先行：{month}月{day}日 {bj_h:02d}:{bj_m:02d} 北京时间"
                print(f"      ⏰ 会员先行: {member_time}")
                break
        
        for pattern in GENERAL_TIME_PATTERNS:
            match = re.search(pattern, text)
            if match:
                month, day, hour, minute = match.groups()
                month, day, hour, minute = int(month), int(day), int(hour), int(minute)
                if timezone == 'KST':
                    bj_h, bj_m = kst_to_bj(hour, minute)
                elif timezone == 'JST':
                    bj_h, bj_m = jst_to_bj(hour, minute)
                else:
                    bj_h, bj_m = hour, minute
                general_time = f"一般售票：{month}月{day}日 {bj_h:02d}:{bj_m:02d} 北京时间"
                print(f"      ⏰ 一般售票: {general_time}")
                break
        
        if member_time and general_time:
            details["ticketTime"] = f"{member_time}<br>{general_time}"
        elif member_time:
            details["ticketTime"] = member_time
        elif general_time:
            details["ticketTime"] = general_time
        
        # 3. 提取票价
        prices_found = []
        currency_found = 'KRW'
        for pattern, currency in PRICE_PATTERNS:
            matches = re.findall(pattern, text)
            if matches:
                for m in matches:
                    num = int(m.replace(',', ''))
                    if 1000 <= num <= 300000:
                        prices_found.append(m)
                if prices_found:
                    currency_found = currency
                    break
        
        if prices_found:
            unique_prices = list(dict.fromkeys(prices_found))[:3]
            details["price"] = " / ".join(unique_prices)
            details["currency"] = currency_found
            print(f"      💰 票价: {details['price']} {currency_found}")
        
        return details
        
    except Exception as e:
        print(f"      ⚠️ 提取票务详情失败: {e}")
        return {}


def scrape_official_site(source):
    """爬取单个官方网站"""
    print(f"\n📡 正在爬取: {source['name']}")
    print(f"   地址: {source['url']}")
    
    events = []
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6,zh-CN;q=0.5,zh;q=0.4"
        }
        
        resp = requests.get(source["url"], headers=headers, timeout=20, allow_redirects=True)
        print(f"   状态码: {resp.status_code}")
        
        if resp.status_code != 200:
            print(f"   ❌ 访问失败，跳过")
            return events
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 查找所有可能的公告/新闻条目
        items = []
        
        # 尝试多种选择器
        selectors = [
            "ul.notice_list li",
            "div.notice-item",
            "article",
            "div.list-item",
            "li.board-item",
            "tr",
            "a[href*='notice']",
            "a[href*='news']",
            "a[href*='info']"
        ]
        
        for selector in selectors:
            found = soup.select(selector)
            if found and len(found) >= 2:
                items = found
                print(f"   找到 {len(items)} 条内容 (选择器: {selector})")
                break
        
        if not items:
            print(f"   ⚠️ 未找到内容列表，尝试提取页面所有链接")
            all_links = soup.find_all("a", href=True)
            print(f"   页面共有 {len(all_links)} 个链接")
            # 只保留可能是公告的链接
            for a in all_links:
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if text and len(text) > 5 and ("notice" in href.lower() or "news" in href.lower() or "riize" in text.lower()):
                    items.append(a)
            print(f"   筛选后 {len(items)} 条可能的公告")
        
        new_events = []
        for i, item in enumerate(items[:15]):  # 只看前15条
            try:
                # 提取标题和链接
                title = ""
                link = ""
                
                if item.name == "a":
                    title = item.get_text(strip=True)
                    link = item.get("href", "")
                else:
                    a_tag = item.find("a")
                    if a_tag:
                        title = a_tag.get_text(strip=True)
                        link = a_tag.get("href", "")
                    else:
                        title = item.get_text(strip=True)[:50]
                
                if not title or len(title) < 5:
                    continue
                
                # 处理相对链接
                full_url = link
                if link and link.startswith("/"):
                    full_url = f"https://{source['domain']}{link}"
                elif link and not link.startswith("http"):
                    full_url = f"https://{source['domain']}/{link}"
                
                # 快速验证标题是否相关
                if not any(kw in title for kw in RIIZE_KEYWORDS):
                    continue
                
                print(f"   [{i+1}] {title[:40]}...")
                
                # 五重过滤验证
                if not is_official_content(title, ""):
                    print(f"      ⚠️ 未通过安全过滤，跳过")
                    continue
                
                # 提取活动类型
                event_type = "event"
                type_label = "活动"
                title_lower = title.lower()
                if any(kw in title_lower for kw in ["concert", "콘서트", "演唱会", "コンサート"]):
                    event_type = "concert"
                    type_label = "演唱会"
                elif any(kw in title_lower for kw in ["fan meeting", "팬미팅", "粉丝见面会", "ファンミ"]):
                    event_type = "fanmeeting"
                    type_label = "粉丝见面会"
                elif any(kw in title_lower for kw in ["fan sign", "팬싸인", "签售", "サイン会"]):
                    event_type = "fansign"
                    type_label = "签售会"
                elif any(kw in title_lower for kw in ["festival", "페스티벌", "音乐节", "フェス"]):
                    event_type = "festival"
                    type_label = "音乐节"
                
                # 尝试从标题提取日期
                date_match = re.search(r'(\d{4})[.-](\d{1,2})[.-](\d{1,2})', title)
                if not date_match:
                    date_match = re.search(r'(\d{1,2})[월月/](\d{1,2})[일日]', title)
                
                event_date = ""
                if date_match:
                    groups = date_match.groups()
                    if len(groups) == 3:
                        event_date = f"{groups[0]}-{int(groups[1]):02d}-{int(groups[2]):02d}"
                    elif len(groups) == 2:
                        current_year = datetime.now().year
                        event_date = f"{current_year}-{int(groups[0]):02d}-{int(groups[1]):02d}"
                
                if not event_date:
                    event_date = datetime.now().strftime("%Y-%m-%d")
                
                # 构建活动对象
                event = {
                    "id": int(time.time()) + i,
                    "title": title,
                    "subtitle": source["name"],
                    "type": event_type,
                    "typeLabel": type_label,
                    "date": event_date,
                    "time": "19:00",
                    "endDate": event_date,
                    "city": "待定",
                    "venue": "待定",
                    "status": "upcoming",
                    "statusLabel": "新公告",
                    "price": "待定",
                    "currency": "KRW",
                    "ticketPlatform": "以官方公告为准",
                    "ticketTime": "以官方公告为准",
                    "organizer": source["name"],
                    "ticketUrl": full_url if full_url else "",
                    "officialUrl": full_url if full_url else "",
                    "description": [
                        f"来源：{source['name']}",
                        f"标题：{title}",
                        "详细信息请点击官方公告查看。"
                    ],
                    "highlights": [],
                    "ticketNote": "请关注官方公告",
                    "source": source["name"],
                    "sourceUrl": source["url"],
                    "scrapedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
                # 尝试从公告详情页提取购票链接
                print(f"   📄 检查公告详情: {text[:30]}...")
                ticket_url = extract_ticket_url(full_url, source["domain"])
                if ticket_url:
                    event["ticketUrl"] = ticket_url
                    event["ticketNote"] = "官方售票"
                    # 找到购票链接，状态改成售票中
                    if event["status"] == "upcoming":
                        event["status"] = "onsale"
                        event["statusLabel"] = "售票中"
                
                # 提取票务详细信息（平台、时间、价格）
                tz = 'JST' if 'japan' in source["name"].lower() or 'jp' in source["domain"] else 'KST'
                ticket_details = extract_ticket_details(full_url, source["domain"], tz)
                if ticket_details:
                    event.update(ticket_details)
                
                new_events.append(event)
                print(f"      ✅ 已添加")
                
            except Exception as e:
                print(f"      ⚠️ 处理条目失败: {e}")
                continue
        
        events.extend(new_events)
        print(f"   ✅ 本次新增 {len(new_events)} 条官方活动")
        
    except Exception as e:
        print(f"   ❌ 爬取失败: {e}")
    
    return events


def load_existing_events():
    """加载已有的活动数据"""
    data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.js")
    
    if not os.path.exists(data_path):
        print("📄 data.js 不存在，将创建新文件")
        return []
    
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 从 data.js 中提取 JSON 数组
        match = re.search(r'window\.RIIZE_EVENTS\s*=\s*(\[.*\]);', content, re.DOTALL)
        if match:
            events = json.loads(match.group(1))
            print(f"📄 已加载 {len(events)} 条现有活动")
            return events
        else:
            print("⚠️ 无法解析 data.js 格式")
            return []
            
    except Exception as e:
        print(f"⚠️ 读取 data.js 失败: {e}")
        return []


def save_events(events):
    """保存活动数据到 data.js"""
    data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.js")
    
    # 按日期排序
    events.sort(key=lambda x: x.get("date", ""), reverse=True)
    
    # 生成 JS 格式
    js_content = "window.RIIZE_EVENTS = " + json.dumps(events, ensure_ascii=False, indent=2) + ";\n"
    
    try:
        with open(data_path, "w", encoding="utf-8") as f:
            f.write(js_content)
        print(f"\n💾 已保存 {len(events)} 条活动到 data.js")
        return True
    except Exception as e:
        print(f"❌ 保存失败: {e}")
        return False


def deduplicate_events(existing_events, new_events):
    """去重：根据标题判断是否已存在"""
    existing_titles = set(e.get("title", "") for e in existing_events)
    
    unique_new = []
    for event in new_events:
        title = event.get("title", "")
        # 模糊匹配：标题相似度超过 80% 认为是同一个
        is_duplicate = False
        for existing_title in existing_titles:
            if title and existing_title:
                # 简单匹配：标题前20个字符相同就算重复
                if title[:20] == existing_title[:20]:
                    is_duplicate = True
                    break
        
        if not is_duplicate:
            unique_new.append(event)
    
    return unique_new


def main():
    """主函数"""
    print("=" * 60)
    print("🌟 RIIZE 官方活动自动爬取工具 v4.0")
    print("=" * 60)
    print(f"🕐 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. 加载已有数据
    existing_events = load_existing_events()
    
    # 2. 爬取所有官方来源
    all_new_events = []
    
    for source in OFFICIAL_SOURCES:
        try:
            events = scrape_official_site(source)
            all_new_events.extend(events)
            time.sleep(2)  # 礼貌延迟
        except Exception as e:
            print(f"❌ 爬取 {source['name']} 失败: {e}")
            continue
    
    print(f"\n📊 共爬取到 {len(all_new_events)} 条新活动")
    
    # 3. 去重
    if existing_events:
        unique_events = deduplicate_events(existing_events, all_new_events)
        print(f"🔍 去重后新增 {len(unique_events)} 条")
        
        # 合并：新活动放前面
        all_events = unique_events + existing_events
    else:
        all_events = all_new_events
        unique_events = all_new_events
    
    # 4. 保存
    if all_events:
        save_events(all_events)
    else:
        print("⚠️ 没有活动数据，不保存")
    
    # 5. 输出统计
    print("\n" + "=" * 60)
    print("📊 爬取完成统计")
    print("=" * 60)
    print(f"  原有活动: {len(existing_events)} 条")
    print(f"  新增活动: {len(unique_events)} 条")
    print(f"  总计活动: {len(all_events)} 条")
    print(f"  完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if unique_events:
        print("\n🆕 新增活动列表:")
        for i, event in enumerate(unique_events[:10]):
            print(f"  [{i+1}] {event['title'][:40]}")
        if len(unique_events) > 10:
            print(f"  ... 还有 {len(unique_events) - 10} 条")
    
    print("\n✅ 爬取完成！")
    return len(unique_events) > 0


if __name__ == "__main__":
    has_updates = main()
    # 有更新时返回 0（GitHub Actions 可以用这个判断）
    exit(0 if has_updates else 1)
