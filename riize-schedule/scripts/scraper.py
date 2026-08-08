#!/usr/bin/env python3
"""
RIIZE 活动自动爬取脚本
只从官方网站获取公告，严格过滤非官方内容
"""

import json
import re
import os
import sys
from datetime import datetime, timedelta
from urllib.parse import urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Installing dependencies...")
    os.system("pip install requests beautifulsoup4")
    import requests
    from bs4 import BeautifulSoup

# ========== 官方来源白名单 ==========
# 只从这些官方域名爬取，其他来源一律忽略
OFFICIAL_SOURCES = [
    {
        "name": "SMTOWN 官网",
        "url": "https://www.smtown.com/notice",
        "domain": "smtown.com",
        "type": "official_notice",
        "category": "公告"
    },
    {
        "name": "SMTOWN JAPAN 官方",
        "url": "https://www.smtown.jp/news/",
        "domain": "smtown.jp",
        "type": "official_notice",
        "category": "公告"
    },
    {
        "name": "Weverse RIIZE",
        "url": "https://weverse.io/riize/notice",
        "domain": "weverse.io",
        "type": "official_notice",
        "category": "公告"
    }
]

# ========== 关键词白名单 ==========
# 标题必须包含这些关键词之一，才认为是RIIZE的活动
RIIZE_KEYWORDS = ["RIIZE", "라이즈", "riize", "RIIZE_"]

# ========== 活动类型关键词 ==========
TYPE_KEYWORDS = {
    "concert": ["CONCERT", "TOUR", "WORLD TOUR", "LIVE", "演唱会", "巡演"],
    "fanmeeting": ["FAN MEETING", "FANMEETING", " FM ", "粉丝见面会", "见面会"],
    "fansign": ["FAN SIGN", "FANSIGN", "签名会", "签售"],
    "smtown": ["SMTOWN", "SM TOWN", "SM LIVE"],
    "album": ["ALBUM", "COMEBACK", "回归", "专辑"]
}

# ========== 黑名单关键词 ==========
# 包含这些关键词的直接跳过（谣言、传闻、粉丝创作等）
BLACKLIST_KEYWORDS = [
    "루머", "rumor", "传闻", "谣言", "网传", "爆料",
    "팬아트", "fanart", "fan art", "同人", "二创", "创作",
    "테스트", "test", "测试",
    "Q&A", "질문", "提问",
    "공지사항", "notice",  # 太泛的词，需要结合其他关键词
]

# ========== 状态关键词 ==========
STATUS_KEYWORDS = {
    "onsale": ["TICKET OPEN", "售票", "开票", "预售", "판매"],
    "soldout": ["SOLD OUT", "售罄", "完售", "매진"],
    "closed": ["CLOSED", "截止", "结束", "마감"]
}


def is_official_url(url):
    """检查URL是否来自官方域名"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        for source in OFFICIAL_SOURCES:
            if source["domain"] in domain:
                return True
        return False
    except:
        return False


def is_valid_rize_title(title):
    """检查标题是否真的是RIIZE的官方公告"""
    title_lower = title.lower()
    
    # 必须包含 RIIZE 关键词
    has_rize = any(kw.lower() in title_lower for kw in RIIZE_KEYWORDS)
    if not has_rize:
        return False
    
    # 不能包含黑名单关键词
    has_blacklist = any(kw.lower() in title_lower for kw in BLACKLIST_KEYWORDS)
    if has_blacklist:
        return False
    
    # 必须是活动相关（有演唱会/见面会/专辑等关键词）
    # 或者是公告类型但包含活动关键词
    has_activity = any(
        any(kw.lower() in title_lower for kw in keywords)
        for keywords in TYPE_KEYWORDS.values()
    )
    
    # 如果没有明确的活动关键词，但包含 RIIZE 和 公告/通知，也先加进去
    has_notice = any(kw in title for kw in ["NOTICE", "公告", "공지", "안내"])
    
    return has_activity or has_notice


def load_events():
    """加载活动数据"""
    with open("data.js", "r", encoding="utf-8") as f:
        content = f.read()
    
    match = re.search(r'window\.RIIZE_EVENTS\s*=\s*(\[[\s\S]*?\]);', content)
    if not match:
        print("❌ 找不到活动数据")
        return []
    
    events_str = match.group(1)
    try:
        events_str_clean = events_str.strip()
        events_str_clean = re.sub(r"'([^']*)':", r'"\1":', events_str_clean)
        events_str_clean = re.sub(r": '([^']*)'", r': "\1"', events_str_clean)
        events_str_clean = re.sub(r',\s*([}\]])', r'\1', events_str_clean)
        return json.loads(events_str_clean)
    except Exception as e:
        print(f"⚠️ 解析失败: {e}")
        ids = re.findall(r'id:\s*(\d+)', events_str)
        titles = re.findall(r'title:\s*["\']([^"\']+)["\']', events_str)
        return [{"id": int(ids[i]) if i < len(ids) else i+100, "title": t} for i, t in enumerate(titles)]


def save_events(events):
    """保存活动数据"""
    js = "window.RIIZE_EVENTS = [\n"
    for i, e in enumerate(events):
        js += "  {\n"
        for key, value in e.items():
            if isinstance(value, str):
                value_escaped = value.replace("\\", "\\\\").replace("'", "\\'")
                js += f"    {key}: '{value_escaped}',\n"
            elif isinstance(value, list):
                js += f"    {key}: {json.dumps(value, ensure_ascii=False)},\n"
            else:
                js += f"    {key}: {value},\n"
        js += "  }"
        if i < len(events) - 1:
            js += ","
        js += "\n"
    js += "];"
    
    with open("data.js", "w", encoding="utf-8") as f:
        f.write(js)
    
    print(f"✅ 已保存 {len(events)} 条活动数据")


def get_next_id(events):
    """获取下一个可用ID"""
    if not events:
        return 1
    return max(e.get("id", 0) for e in events) + 1


def parse_event_info(title, source_name, url):
    """从标题中解析活动信息"""
    event = {
        "title": title[:80],
        "subtitle": f"来自 {source_name} 的官方公告",
        "type": "concert",
        "typeLabel": "官方公告",
        "date": "",
        "endDate": "",
        "time": "18:00",
        "city": "待确认",
        "venue": "待确认",
        "status": "upcoming",
        "statusLabel": "新公告",
        "ticketNote": "待官方公布",
        "price": "待官方公布",
        "ticketUrl": url,
        "officialUrl": url,
        "highlights": [
            {"title": "📢 官方公告", "content": f"来自 {source_name} 的官方消息"},
            {"title": "ℹ️ 信息待补充", "content": "自动爬取，详细信息待后续更新"}
        ],
        "schedule": []
    }
    
    # 判断类型
    title_lower = title.lower()
    for t, keywords in TYPE_KEYWORDS.items():
        if any(kw.lower() in title_lower for kw in keywords):
            event["type"] = t
            type_labels = {
                "concert": "演唱会",
                "fanmeeting": "粉丝见面会",
                "fansign": "签名会",
                "smtown": "SMTOWN",
                "album": "专辑回归"
            }
            event["typeLabel"] = type_labels.get(t, "官方公告")
            break
    
    # 判断状态
    for s, keywords in STATUS_KEYWORDS.items():
        if any(kw.lower() in title_lower for kw in keywords):
            event["status"] = s
            status_labels = {
                "onsale": "售票中",
                "soldout": "已售罄",
                "closed": "已截止"
            }
            event["statusLabel"] = status_labels.get(s, "新公告")
            break
    
    # 尝试提取日期（YYYY.MM.DD 或 YYYY-MM-DD）
    date_patterns = [
        r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})',
        r'(\d{1,2})月(\d{1,2})日',
        r'(\d{1,2})/(\d{1,2})'
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, title)
        if match:
            groups = match.groups()
            if len(groups) == 3:
                year, month, day = groups
            else:
                year = str(datetime.now().year)
                month, day = groups
            
            try:
                date_str = f"{year}-{int(month):02d}-{int(day):02d}"
                event["date"] = date_str
                event["endDate"] = date_str
            except:
                pass
            break
    
    # 尝试提取城市
    cities = ["서울", "首尔", "도쿄", "东京", "오사카", "大阪", "후쿠오카", "福冈",
              "홍콩", "香港", "대만", "台北", "방콕", "曼谷",
              "뉴욕", "纽约", "로스앤젤레스", "洛杉矶", "샌프란시스코", "旧金山",
              "시애틀", "西雅图", "워싱턴", "华盛顿", "애틀랜타", "亚特兰大",
              "런던", "伦敦", "파리", "巴黎", "싱가포르", "新加坡",
              "자카르타", "雅加达", "마닐라", "马尼拉"]
    
    for city in cities:
        if city in title:
            # 转换为中文城市名
            city_map = {
                "서울": "韩国首尔", "도쿄": "日本东京", "오사카": "日本大阪",
                "후쿠오카": "日本福冈", "홍콩": "中国香港", "대만": "中国台北",
                "방콕": "泰国曼谷", "뉴욕": "美国纽约", "로스앤젤레스": "美国洛杉矶",
                "샌프란시스코": "美国旧金山", "시애틀": "美国西雅图",
                "워싱턴": "美国华盛顿", "애틀랜타": "美国亚特兰大",
                "런던": "英国伦敦", "파리": "法国巴黎", "싱가포르": "新加坡",
                "자카르타": "印尼雅加达", "마닐라": "菲律宾马尼拉"
            }
            event["city"] = city_map.get(city, city)
            break
    
    return event


def scrape_official_site(source):
    """爬取单个官方网站"""
    new_events = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6,zh-CN;q=0.5,zh;q=0.4"
        }
        
        print(f"   正在访问 {source['name']}...")
        resp = requests.get(source["url"], headers=headers, timeout=15, allow_redirects=True)
        
        if resp.status_code != 200:
            print(f"   ⚠️ HTTP {resp.status_code}")
            return new_events
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 查找所有链接
        links = soup.find_all("a", href=True)
        found = 0
        
        for link in links:
            href = link["href"]
            text = link.get_text(strip=True)
            
            if not text or len(text) < 8:
                continue
            
            # 检查是否是官方链接
            full_url = href
            if not href.startswith("http"):
                if href.startswith("/"):
                    full_url = f"https://{source['domain']}{href}"
                else:
                    full_url = f"https://{source['domain']}/{href}"
            
            if not is_official_url(full_url):
                continue
            
            # 检查是否是 RIIZE 的有效公告
            if is_valid_rize_title(text):
                event = parse_event_info(text, source["name"], full_url)
                new_events.append(event)
                found += 1
                
                if found >= 5:  # 每个来源最多取5条
                    break
        
        print(f"   ✅ 找到 {found} 条 RIIZE 官方公告")
                    
    except Exception as e:
        print(f"   ⚠️ 爬取失败: {e}")
    
    return new_events


def main():
    print("🔍 RIIZE 官方活动自动检查")
    print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"📋 官方来源: {len(OFFICIAL_SOURCES)} 个")
    print(f"🔒 严格模式: 只接受官方域名 + RIIZE关键词 + 活动关键词")
    print("=" * 60)
    
    # 加载已有活动
    events = load_events()
    existing_titles = set(e.get("title", "")[:30] for e in events)
    print(f"\n📊 已有活动: {len(events)} 条")
    
    all_new = []
    
    # 逐个检查官方来源
    for source in OFFICIAL_SOURCES:
        print(f"\n📡 检查 {source['name']}...")
        new_events = scrape_official_site(source)
        all_new.extend(new_events)
    
    # 去重
    truly_new = []
    seen_titles = set()
    
    for event in all_new:
        title_key = event["title"][:30]
        
        # 和已有活动对比
        is_duplicate = False
        for existing_title in existing_titles:
            # 标题前30字相同，或者互相包含，就算重复
            if (title_key in existing_title or 
                existing_title in title_key or
                title_key == existing_title):
                is_duplicate = True
                break
        
        if not is_duplicate and title_key not in seen_titles:
            seen_titles.add(title_key)
            truly_new.append(event)
    
    print(f"\n{'=' * 60}")
    print(f"✨ 新增官方活动: {len(truly_new)} 条")
    
    if truly_new:
        next_id = get_next_id(events)
        
        print("\n📋 新增列表:")
        for i, event in enumerate(truly_new):
            event["id"] = next_id + i
            events.append(event)
            print(f"  {i+1}. [{event['typeLabel']}] {event['title']}")
            print(f"      来源: {event['subtitle']}")
            print(f"      链接: {event['officialUrl']}")
        
        # 保存
        save_events(events)
        
        # 保存变更记录
        with open("update_log.txt", "w", encoding="utf-8") as f:
            f.write(f"更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"新增官方活动: {len(truly_new)} 条\n\n")
            for event in truly_new:
                f.write(f"[{event['typeLabel']}] {event['title']}\n")
                f.write(f"  来源: {event['subtitle']}\n")
                f.write(f"  链接: {event['officialUrl']}\n\n")
        
        print("\n✅ 活动数据已更新，将自动部署")
        return 1  # 有更新
    else:
        print("\n✅ 没有新的官方活动")
        return 0  # 没有更新


if __name__ == "__main__":
    sys.exit(main())
