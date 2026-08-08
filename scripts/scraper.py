import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime

EXCHANGE_RATES = {
    'KRW': 0.0053, 'JPY': 0.047, 'USD': 7.2, 'CNY': 1.0,
    'HKD': 0.92, 'MOP': 0.89, 'THB': 0.20
}

TICKET_PLATFORMS = [
    'Melon Ticket', 'YES24', 'Interpark', 'NOL', 'Ticketmaster', 'AXS',
    'e+', 'ぴあ', '罗森票务', 'ローソンチケット',
    '大麦网', '猫眼', '银河票务', 'Fantopia', 'Ktown4u',
    '熊宝空间站', 'Creatrip', 'Thai Ticket Major', 'MADE ON',
    'Weverse', 'SMTOWN', 'BRIIZE JAPAN', 'Qoo10'
]

PRICE_PATTERNS = [
    r'(\d{1,3}(?:,\d{3})*)\s*(?:원|KRW|韩元|₩)',
    r'(\d{1,3}(?:,\d{3})*)\s*(?:円|JPY|日元|¥)',
    r'(\d{1,3}(?:,\d{3})*)\s*(?:USD|美元|\$)',
    r'(\d{1,3}(?:,\d{3})*)\s*(?:HKD|港币)',
    r'(\d{1,3}(?:,\d{3})*)\s*(?:MOP|澳门元)',
    r'(\d{1,3}(?:,\d{3})*)\s*(?:THB|泰铢|บาท)',
    r'(\d{1,3}(?:,\d{3})*)\s*(?:元|CNY|人民币)',
]

CURRENCY_MAP = {
    'KRW': 'KRW', '원': 'KRW', '韩元': 'KRW',
    'JPY': 'JPY', '円': 'JPY', '日元': 'JPY',
    'USD': 'USD', '美元': 'USD',
    'HKD': 'HKD', '港币': 'HKD',
    'MOP': 'MOP', '澳门元': 'MOP',
    'THB': 'THB', '泰铢': 'THB',
    'CNY': 'CNY', '元': 'CNY', '人民币': 'CNY',
}

OFFICIAL_SITES = [
    {'url': 'https://weverse.io/RIIZE/notice', 'name': 'Weverse', 'timezone': 'KST'},
    {'url': 'https://www.smtown.com/', 'name': 'SMTOWN', 'timezone': 'KST'},
    {'url': 'https://www.riizeofficial.jp/news/', 'name': 'RIIZE JAPAN', 'timezone': 'JST'},
]

BLACKLIST = ['루머', 'rumor', '传闻', '爆料', '小道消息', '미확인', 'unconfirmed']

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def kst_to_bj(hour, minute=0):
    return (hour - 1) % 24, minute

def jst_to_bj(hour, minute=0):
    return (hour - 1) % 24, minute

def extract_prices(text):
    prices = []
    currency = 'KRW'
    for pattern in PRICE_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            for m in matches:
                num = int(m.replace(',', ''))
                if 1000 <= num <= 300000:
                    prices.append(m)
            for key in CURRENCY_MAP:
                if key in pattern:
                    currency = CURRENCY_MAP[key]
                    break
    if len(prices) > 0:
        return ' / '.join(list(dict.fromkeys(prices))[:3]), currency
    return None, currency

def extract_ticket_platform(text):
    found = []
    for platform in TICKET_PLATFORMS:
        if platform.lower() in text.lower():
            found.append(platform)
    if len(found) > 0:
        return ' / '.join(list(dict.fromkeys(found))[:4])
    return None

def extract_ticket_time(text, timezone='KST'):
    member_time = None
    general_time = None
    
    member_patterns = [
        r'(?:팬클럽|팬클럽선예매|会员先行|FC先行|pre-sale|presale|member.*?sale)[^\d]*(\d{1,2})月\s*(\d{1,2})日[^\d]*(\d{1,2})[:：](\d{1,2})',
        r'(?:팬클럽|会员先行|FC先行)[^\d]*(\d{1,2})[월/](\d{1,2})[일/][^\d]*(\d{1,2})[:시](\d{1,2})',
    ]
    
    general_patterns = [
        r'(?:일반|一般售票|一般发售|general sale)[^\d]*(\d{1,2})月\s*(\d{1,2})日[^\d]*(\d{1,2})[:：](\d{1,2})',
        r'(?:일반|一般)[^\d]*(\d{1,2})[월/](\d{1,2})[일/][^\d]*(\d{1,2})[:시](\d{1,2})',
    ]
    
    for pattern in member_patterns:
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
            break
    
    for pattern in general_patterns:
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
            break
    
    if member_time and general_time:
        return f"{member_time}<br>{general_time}"
    elif member_time:
        return member_time
    elif general_time:
        return general_time
    
    if '已开票' in text or '售票中' in text:
        return '已开票（北京时间）'
    if '报名中' in text:
        return '报名中（北京时间）'
    if '已售罄' in text:
        return '已售罄'
    if '已结束' in text:
        return '已结束'
    
    return None

def is_riize_event(text):
    text_lower = text.lower()
    if 'riize' not in text_lower and '라이즈' not in text:
        return False
    for word in BLACKLIST:
        if word.lower() in text_lower:
            return False
    return True

def detect_event_type(text):
    text_lower = text.lower()
    if 'concert' in text_lower or '콘서트' in text or '演唱会' in text:
        return 'concert', '演唱会'
    if 'fanmeeting' in text_lower or '팬미팅' in text or '粉丝见面会' in text or 'FM' in text:
        return 'fanmeeting', '粉丝见面会'
    if 'fansign' in text_lower or '팬사인' in text or '签售' in text or '签名会' in text:
        return 'fansign', '签售会'
    if 'festival' in text_lower or '페스티벌' in text or '音乐节' in text or 'fes' in text_lower:
        return 'festival', '音乐节'
    if 'pop-up' in text_lower or 'popup' in text_lower or '快闪' in text:
        return 'event', '快闪店'
    return 'event', '活动'

def scrape_site(url, name, timezone):
    print(f"正在爬取 {name}...")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        events = []
        links = soup.find_all('a', href=True)
        
        for link in links:
            title = clean_text(link.get_text())
            href = link['href']
            
            if not title or len(title) < 5:
                continue
            if not is_riize_event(title):
                continue
            
            full_url = href if href.startswith('http') else url.rstrip('/') + '/' + href.lstrip('/')
            
            event = {
                'id': abs(hash(title)) % 100000,
                'title': title[:60],
                'subtitle': name,
                'type': 'event',
                'typeLabel': '活动',
                'date': datetime.now().strftime('%Y-%m-%d'),
                'endDate': datetime.now().strftime('%Y-%m-%d'),
                'time': '18:00',
                'city': '待定',
                'venue': '待定',
                'status': 'upcoming',
                'statusLabel': '即将开始',
                'price': '待定',
                'currency': 'KRW',
                'ticketPlatform': '待定',
                'ticketTime': '待定（北京时间）',
                'organizer': name,
                'ticketUrl': full_url,
                'officialUrl': full_url,
                'description': [title],
                'highlights': [],
                'ticketNote': '请关注官方公告'
            }
            
            try:
                detail_resp = requests.get(full_url, headers=headers, timeout=10)
                detail_resp.encoding = 'utf-8'
                detail_soup = BeautifulSoup(detail_resp.text, 'html.parser')
                detail_text = clean_text(detail_soup.get_text())
                
                if len(detail_text) > 50:
                    event['description'] = [detail_text[i:i+100] for i in range(0, min(300, len(detail_text)), 100)]
                    
                    price, currency = extract_prices(detail_text)
                    if price:
                        event['price'] = price
                        event['currency'] = currency
                    
                    platform = extract_ticket_platform(detail_text)
                    if platform:
                        event['ticketPlatform'] = platform
                    
                    ticket_time = extract_ticket_time(detail_text, timezone)
                    if ticket_time:
                        event['ticketTime'] = ticket_time
                    
                    etype, elabel = detect_event_type(detail_text)
                    event['type'] = etype
                    event['typeLabel'] = elabel
                    
                    for city in ['서울', '首尔', 'Seoul', '도쿄', '东京', 'Tokyo', '오사카', '大阪', 'Osaka', '부산', '釜山', 'Busan']:
                        if city in detail_text:
                            event['city'] = city
                            break
                            
            except Exception as e:
                print(f"  详情页抓取失败: {e}")
            
            events.append(event)
        
        print(f"  找到 {len(events)} 条相关活动")
        return events
        
    except Exception as e:
        print(f"  爬取失败: {e}")
        return []

def main():
    print("=" * 60)
    print("RIIZE 活动爬虫 v3.0 - 会员/非会员售票时间提取")
    print("=" * 60)
    
    all_events = []
    
    for site in OFFICIAL_SITES:
        events = scrape_site(site['url'], site['name'], site['timezone'])
        all_events.extend(events)
    
    print(f"\n共找到 {len(all_events)} 条活动")
    
    print("\n提取结果示例：")
    for e in all_events[:5]:
        print(f"  📌 {e['title']}")
        print(f"     💰 票价: {e['price']} {e['currency']}")
        print(f"     🏪 平台: {e['ticketPlatform']}")
        print(f"     ⏰ 购票时间: {e['ticketTime'].replace('<br>', ' / ')}")
        print()
    
    print("✅ 爬取完成！")
    print("   购票时间自动转换为北京时间")
    print("   自动提取会员先行 + 一般售票两个时间")

if __name__ == '__main__':
    main()
