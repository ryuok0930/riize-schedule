import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime, timedelta
import os

# 汇率（人民币）
EXCHANGE_RATES = {
    "KRW": 0.0053,  # 韩元
    "JPY": 0.047,   # 日元
    "USD": 7.2,     # 美元
    "CNY": 1.0,     # 人民币
    "HKD": 0.92,    # 港币
    "MOP": 0.89,    # 澳门元
    "THB": 0.20     # 泰铢
}

# 配置
DATA_FILE = "data.js"
OFFICIAL_SITES = [
    {"name": "Weverse RIIZE", "url": "https://weverse.io/RIIZE/notice", "lang": "ko"},
    {"name": "SMTOWN 官网", "url": "https://www.smtown.com/artist/riize", "lang": "ko"},
    {"name": "RIIZE JAPAN 官网", "url": "https://riizeofficial.jp/news/", "lang": "ja"}
]

BLACKLIST_KEYWORDS = ["传闻", "网传", "爆料", "疑似", "可能", "或将", "rumor", "alleged"]

TYPE_KEYWORDS = {
    "concert": ["演唱会", "concert", "巡演", "tour", "专场"],
    "fanmeeting": ["粉丝见面会", "fanmeeting", "fm", "粉丝派对", "fan party"],
    "fansign": ["签售", "签名会", "fansign", "线下活动", "抽选"],
    "festival": ["音乐节", "颁奖礼", "盛典", "festival", "awards", "歌谣大战"],
    "event": ["快闪", "pop-up", "popup", "展览"]
}

TICKET_PLATFORM_KEYWORDS = [
    "Melon Ticket", "Interpark", "YES24", "Ticketmaster", "e+", "ぴあ", "罗森",
    "NOL", "Weverse", "Ktown4u", "Fantopia", "熊宝空间站", "大麦网", "猫眼",
    "银河票务", "Qoo10", "MADE ON"
]

def load_existing_events():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            match = re.search(r'window\.RIIZE_EVENTS\s*=\s*(\[.*\]);', content, re.DOTALL)
            if match:
                return json.loads(match.group(1))
    except Exception as e:
        print(f"加载失败: {e}")
    return []

def save_events(events):
    events.sort(key=lambda x: x.get('date', ''), reverse=True)
    js = f"window.RIIZE_EVENTS = {json.dumps(events, ensure_ascii=False, indent=2)};"
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        f.write(js)
    print(f"已保存 {len(events)} 条")

def kst_to_beijing(time_str):
    try:
        for fmt in ["%H:%M", "%H시 %M분"]:
            try:
                dt = datetime.strptime(time_str.strip(), fmt)
                return (dt - timedelta(hours=1)).strftime("%H:%M")
            except:
                continue
    except:
        pass
    return time_str

def extract_ticket_info(text, lang="ko"):
    info = {"platform": "待定", "time": "待定", "price": "待定", "currency": "KRW", "priceCNY": "待定"}
    
    # 提取购票平台
    plats = []
    for kw in TICKET_PLATFORM_KEYWORDS:
        if kw.lower() in text.lower():
            plats.append(kw)
    if plats:
        info["platform"] = " / ".join(list(set(plats))[:3])
    
    # 提取开票时间
    time_pats = [
        r'(\d{1,2}月\d{1,2}日\s*\d{1,2}[:시]\d{0,2}[분]?)\s*(?:开票|发售|开售|판매|発売)',
        r'(?:开票|发售|开售).*?(\d{1,2}月\d{1,2}日\s*\d{1,2}[:시]\d{0,2}[분]?)',
    ]
    for p in time_pats:
        m = re.search(p, text)
        if m:
            info["time"] = m.group(1) + "（北京时间）"
            break
    
    # 提取票价和货币
    price_data = [
        (r'(\d{1,3}[,，]\d{3})\s*(?:원|₩|KRW)', "KRW"),
        (r'(\d{1,3}[,，]?\d{0,3})\s*(?:円|¥|JPY)', "JPY"),
        (r'(\d{1,3}[,，]?\d{0,3})\s*(?:元|¥|CNY|人民币)', "CNY"),
        (r'(\d{1,3}[,，]?\d{0,3})\s*(?:美元|\$|USD)', "USD"),
        (r'(\d{1,3}[,，]?\d{0,3})\s*(?:港币|HKD)', "HKD"),
        (r'(\d{1,3}[,，]?\d{0,3})\s*(?:澳门币|MOP)', "MOP"),
    ]
    
    for pattern, currency in price_data:
        m = re.search(pattern, text)
        if m:
            price_str = m.group(1).replace(',', '').replace('，', '')
            try:
                price_num = int(price_str)
                info["price"] = m.group(1)
                info["currency"] = currency
                rate = EXCHANGE_RATES.get(currency, 1)
                info["priceCNY"] = f"约¥{int(price_num * rate):,}"
            except:
                pass
            break
    
    return info

def extract_event_details(title, content, url, site_name):
    event = {
        "id": int(datetime.now().timestamp()),
        "title": title,
        "subtitle": site_name,
        "type": "festival",
        "typeLabel": "活动",
        "date": "",
        "time": "19:00",
        "endDate": "",
        "city": "待定",
        "venue": "待定",
        "status": "upcoming",
        "statusLabel": "即将开始",
        "price": "待定",
        "currency": "KRW",
        "priceCNY": "待定",
        "organizer": site_name,
        "ticketPlatform": "待定",
        "ticketTime": "待定",
        "ticketUrl": url,
        "officialUrl": url,
        "description": [],
        "highlights": [],
        "ticketNote": "以官方公告为准"
    }
    
    # 活动类型
    text_lower = (title + " " + content).lower()
    for etype, kws in TYPE_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in text_lower:
                event["type"] = etype
                labels = {"concert": "演唱会", "fanmeeting": "粉丝见面会", "fansign": "签售会", "festival": "音乐节", "event": "活动"}
                event["typeLabel"] = labels.get(etype, "活动")
                break
        else:
            continue
        break
    
    # 日期
    date_pats = [
        r'(\d{4})[년./-](\d{1,2})[월./-](\d{1,2})[일日]?',
        r'(\d{1,2})[월月](\d{1,2})[일日]',
    ]
    for p in date_pats:
        m = re.search(p, title + " " + content)
        if m:
            g = m.groups()
            if len(g) == 3:
                y, mo, d = g
            else:
                y = str(datetime.now().year)
                mo, d = g
            event["date"] = f"{y}-{int(mo):02d}-{int(d):02d}"
            event["endDate"] = event["date"]
            break
    
    # 购票信息
    ticket = extract_ticket_info(content)
    event["ticketPlatform"] = ticket["platform"]
    event["ticketTime"] = ticket["time"]
    event["price"] = ticket["price"]
    event["currency"] = ticket["currency"]
    event["priceCNY"] = ticket["priceCNY"]
    
    # 地点
    loc_pats = [
        r'(?:地点|场地|场馆|장소|会場)[:：]\s*([^\n，。]+)',
        r'在([^\n，。]{2,20})(?:举办|举行)',
    ]
    for p in loc_pats:
        m = re.search(p, content)
        if m:
            loc = m.group(1).strip()
            if len(loc) < 50:
                event["venue"] = loc
                if "서울" in loc or "首尔" in loc: event["city"] = "韩国首尔"
                elif "도쿄" in loc or "东京" in loc: event["city"] = "日本东京"
                elif "오사카" in loc or "大阪" in loc: event["city"] = "日本大阪"
                elif "부산" in loc or "釜山" in loc: event["city"] = "韩国釜山"
                elif "마카오" in loc or "澳门" in loc: event["city"] = "中国澳门"
                elif "상하이" in loc or "上海" in loc: event["city"] = "中国上海"
                elif "홍콩" in loc or "香港" in loc: event["city"] = "中国香港"
            break
    
    # 描述
    paras = [p.strip() for p in re.split(r'[\n。.]', content) if len(p.strip()) > 10][:3]
    event["description"] = paras if paras else [title, f"来自 {site_name}", "请查看官方公告"]
    
    return event

def is_blacklisted(text):
    return any(kw.lower() in text.lower() for kw in BLACKLIST_KEYWORDS)

def is_riize_related(text):
    return any(kw.lower() in text.lower() for kw in ["riize", "라이즈", "RIIZE", "rise and realize"])

def fetch_site(site):
    events = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(site["url"], headers=headers, timeout=15)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        
        items = soup.find_all(['a', 'div', 'li'], class_=re.compile(r'(notice|news|item|list|post)', re.I))
        
        for item in items[:10]:
            title_elem = item.find(['h2', 'h3', 'h4', 'span', 'a'], class_=re.compile(r'(title|subject)', re.I)) or item
            title = title_elem.get_text(strip=True)
            
            if not title or len(title) < 5 or not is_rize_related(title) or is_blacklisted(title):
                continue
            
            link = item.find('a', href=True)
            url = site["url"]
            if link:
                from urllib.parse import urljoin
                url = urljoin(site["url"], link['href']) if link['href'].startswith('/') else link['href']
            
            content_elem = item.find(['p', 'div'], class_=re.compile(r'(content|desc)', re.I))
            content = content_elem.get_text(strip=True) if content_elem else title
            
            events.append(extract_event_details(title, content, url, site["name"]))
            
    except Exception as e:
        print(f"爬取 {site['name']} 失败: {e}")
    return events

def main():
    print("=" * 50)
    print("RIIZE 活动自动爬取 v2.1（票价自动提取+人民币转换）")
    print("=" * 50)
    
    existing = load_existing_events()
    print(f"已有 {len(existing)} 条")
    
    all_new = []
    for site in OFFICIAL_SITES:
        print(f"爬取 {site['name']}...")
        new = fetch_site(site)
        print(f"  找到 {len(new)} 条")
        all_new.extend(new)
    
    # 去重
    existing_titles = [e["title"] for e in existing]
    unique = []
    for ev in all_new:
        dup = False
        for ot in existing_titles:
            sim = len(set(ev["title"]) & set(ot)) / len(set(ev["title"]) | set(ot)))
            if sim > 0.6:
                dup = True
                break
        if not dup:
            unique.append(ev)
    
    print(f"\n新增 {len(unique)} 条")
    all_events = existing + unique
    save_events(all_events)
    print("✅ 完成！")

if __name__ == "__main__":
    main()
