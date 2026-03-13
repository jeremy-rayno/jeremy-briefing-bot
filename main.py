import requests
import json
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from openai import OpenAI
from google.oauth2 import service_account
from googleapiclient.discovery import build
import os

# =========================
# ENV
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
GOOGLE_CALENDAR_KEY = os.getenv("GOOGLE_CALENDAR_KEY")
CALENDAR_ID_1 = os.getenv("CALENDAR_ID_1", "jeremyson@raynofilm.com")
CALENDAR_ID_2 = os.getenv("CALENDAR_ID_2", "global@raynofilm.com")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DB_ID = os.getenv("NOTION_DB_ID")

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# 신뢰할 수 없는 소스 블랙리스트
# 일반 shop, blog, 개인 사이트 등 제외
# =========================

BLOCKED_SOURCES = [
    "blogspot", "wordpress", "medium.com", "substack",
    "tumblr", "wix", "squarespace", "weebly",
    "bringatrailer", "craigslist", "ebay", "amazon",
    "reddit", "quora", "yahoo answers", "yelp",
    "tripadvisor", "trustpilot", "sitejabber"
]

def is_trusted_source(source_name, url):
    """
    블랙리스트 소스 필터링
    일반 shop, blog, 개인 사이트 제외
    """
    source_lower = source_name.lower()
    url_lower = url.lower()

    for blocked in BLOCKED_SOURCES:
        if blocked in source_lower or blocked in url_lower:
            return False

    return True

# =========================
# NEWS QUERIES
# =========================

# 태국 — 자동차 애프터마켓 전반으로 확대
TH_QUERIES = [
    "Thailand automotive market",
    "Thailand car industry",
    "Thailand vehicle market",
    "Thailand window film",
    "Thailand paint protection film"
]

# 인도네시아 — 자동차 애프터마켓 전반으로 확대
ID_QUERIES = [
    "Indonesia automotive market",
    "Indonesia car industry",
    "Indonesia vehicle market",
    "Indonesia window film",
    "Indonesia paint protection film"
]

# 경쟁사 — 화이트리스트 제거, GPT 필터링으로만 관리
COMPETITOR_QUERIES = [
    "XPEL window film",
    "XPEL paint protection",
    "XPEL Technologies",
    "Llumar window film",
    "Llumar Eastman",
    "3M window film",
    "3M paint protection film",
    "Suntek window film",
    "Suntek PPF",
    "SolarGard window film",
    "SolarGard Saint Gobain"
]

# =========================
# MARKET DATA
# =========================

def get_market():

    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        fx_url = "https://finance.naver.com/marketindex/"
        res = requests.get(fx_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        usd = soup.select_one("span.value").text
    except Exception:
        usd = "N/A"

    try:
        kospi_url = "https://finance.naver.com/sise/"
        res = requests.get(kospi_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        kospi = soup.select_one("#KOSPI_now").text
    except Exception:
        kospi = "N/A"

    try:
        samsung_url = "https://finance.naver.com/item/main.naver?code=005930"
        res = requests.get(samsung_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        samsung = soup.select_one("p.no_today span.blind").text
    except Exception:
        samsung = "N/A"

    return usd, kospi, samsung


# =========================
# GOOGLE CALENDAR
# =========================

def get_calendar_events():

    try:
        key_data = json.loads(GOOGLE_CALENDAR_KEY)
        credentials = service_account.Credentials.from_service_account_info(
            key_data,
            scopes=["https://www.googleapis.com/auth/calendar.readonly"]
        )
        service = build("calendar", "v3", credentials=credentials)

        now_kst = datetime.now(timezone.utc) + timedelta(hours=9)
        today_start = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now_kst.replace(hour=23, minute=59, second=59, microsecond=0)

        time_min = (today_start - timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%SZ")
        time_max = (today_end - timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%SZ")

        all_events = []

        for calendar_id in [CALENDAR_ID_1, CALENDAR_ID_2]:
            try:
                result = service.events().list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime"
                ).execute()

                for event in result.get("items", []):
                    summary = event.get("summary", "(제목 없음)")
                    start = event.get("start", {})

                    if "dateTime" in start:
                        dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
                        dt_kst = dt + timedelta(hours=9) if dt.tzinfo and str(dt.tzinfo) == "UTC" else dt
                        time_str = dt_kst.strftime("%H:%M")
                    else:
                        time_str = "종일"

                    all_events.append({
                        "time": time_str,
                        "summary": summary,
                        "sort_key": start.get("dateTime", start.get("date", ""))
                    })

            except Exception as e:
                print(f"Calendar error ({calendar_id}):", str(e))

        all_events.sort(key=lambda x: x["sort_key"])
        return all_events

    except Exception as e:
        print("Calendar init error:", str(e))
        return []


def format_calendar(events):

    now_kst = datetime.now(timezone.utc) + timedelta(hours=9)
    day_str = now_kst.strftime("%m.%d (%a)").replace(
        "Mon", "월").replace("Tue", "화").replace("Wed", "수").replace(
        "Thu", "목").replace("Fri", "금").replace("Sat", "토").replace("Sun", "일")

    if not events:
        return f"<b>📅 Today's Schedule</b>  <i>{day_str}</i>\n일정 없음"

    lines = [f"<b>📅 Today's Schedule</b>  <i>{day_str}</i>"]
    for e in events:
        lines.append(f"{e['time']}  {e['summary']}")

    return "\n".join(lines)


# =========================
# NEWS FETCH — NewsAPI
# =========================

def get_top_headlines():
    """글로벌 헤드라인 — business + technology"""

    news = []
    seen_urls = set()

    for category in ["business", "technology"]:
        try:
            url = "https://newsapi.org/v2/top-headlines"
            params = {
                "category": category,
                "language": "en",
                "pageSize": 10,
                "apiKey": NEWS_API_KEY
            }

            res = requests.get(url, params=params, timeout=10)
            data = res.json()

            print(f"top-headlines [{category}] status: {data.get('status')} / total: {data.get('totalResults', 0)}")

            if data.get("status") == "ok":
                for article in data.get("articles", []):
                    title = article.get("title", "")
                    article_url = article.get("url", "")
                    source = article.get("source", {}).get("name", "")

                    if not title or title == "[Removed]":
                        continue
                    if not article_url:
                        continue
                    if article_url in seen_urls:
                        continue
                    if not is_trusted_source(source, article_url):
                        continue

                    seen_urls.add(article_url)
                    news.append({
                        "title": title,
                        "url": article_url,
                        "source": source
                    })
            else:
                print(f"top-headlines error [{category}]: {data.get('code')} / {data.get('message')}")

        except Exception as e:
            print(f"top-headlines exception ({category}):", str(e))

    return news


def get_news(queries, page_size=5, sort_by="publishedAt"):

    news = []
    seen_urls = set()

    for query in queries:
        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": query,
                "sortBy": sort_by,
                "pageSize": page_size,
                "language": "en",
                "apiKey": NEWS_API_KEY
            }

            res = requests.get(url, params=params, timeout=10)
            data = res.json()

            print(f"NewsAPI [{query}] status: {data.get('status')} / total: {data.get('totalResults', 0)}")

            if data.get("status") == "ok":
                for article in data.get("articles", []):
                    title = article.get("title", "")
                    article_url = article.get("url", "")
                    source = article.get("source", {}).get("name", "")

                    if not title or title == "[Removed]":
                        continue
                    if not article_url:
                        continue
                    if article_url in seen_urls:
                        continue
                    if not is_trusted_source(source, article_url):
                        continue

                    seen_urls.add(article_url)
                    news.append({
                        "title": title,
                        "url": article_url,
                        "source": source
                    })
            else:
                print(f"NewsAPI error [{query}]: {data.get('code')} / {data.get('message')}")

        except Exception as e:
            print(f"NewsAPI exception ({query}):", str(e))

    return news


# =========================
# AI 분석 — Global Top3
# =========================

def analyze_global(news_list):

    if not news_list:
        return [{"title": "수집된 뉴스 없음", "summary": "", "url": "", "source": ""}]

    items = "\n".join([
        f"{i+1}. [{n.get('source','')}] {n['title']} | {n['url']}"
        for i, n in enumerate(news_list[:20])
    ])

    prompt = f"""
아래 뉴스 목록에서 현재 글로벌에서 가장 중요하고 영향력 있는 뉴스 3개를 골라 분석해줘.
분야 제한 없이, 많은 미디어가 헤드라인으로 다루고 있을 만큼 중요도가 높은 뉴스를 선택해줘.
반드시 아래 JSON 형식으로만 답해줘. JSON 외에 다른 말은 절대 쓰지 마.
title은 한국어로 번역해줘.
summary는 한국어로 3~4문장, 150자 이내로 작성해줘.
url은 원본 그대로 복사해줘. 절대 바꾸거나 생략하지 마.
source는 원본 그대로 복사해줘.

출력 형식:
[
  {{
    "title": "한국어로 번역한 뉴스 제목",
    "summary": "3~4문장 한국어 요약 (150자 이내)",
    "url": "https://원본URL",
    "source": "매체명"
  }},
  {{"title": "...", "summary": "...", "url": "...", "source": "..."}},
  {{"title": "...", "summary": "...", "url": "...", "source": "..."}}
]

뉴스 목록:
{items}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    raw = response.choices[0].message.content.strip()

    try:
        raw = re.sub(r"```json|```", "", raw).strip()
        return json.loads(raw)
    except Exception:
        return [{"title": "AI 분석 실패", "summary": raw[:200], "url": "", "source": ""}]


# =========================
# AI 분석 — 태국/인도네시아
# =========================

def analyze_regional(news_list, country):
    """
    자동차 애프터마켓 관련성 판단 (윈도우필름/PPF/자동차 시장 전반)
    관련 없으면 None 반환
    """

    if not news_list:
        return None

    items = "\n".join([
        f"{i+1}. [{n.get('source','')}] {n['title']} | {n['url']}"
        for i, n in enumerate(news_list[:15])
    ])

    prompt = f"""
아래는 {country} 관련 뉴스 목록이야.
자동차 산업, 자동차 시장, 자동차 애프터마켓, 윈도우 필름, PPF(페인트 보호 필름), 
썬팅, 차량 관련 정책/규제/트렌드와 관련성이 있는 뉴스가 있으면
가장 관련성 높은 1개를 골라 분석해줘.

관련성이 있는 뉴스가 전혀 없으면 반드시 이것만 답해줘:
{{"relevant": false}}

관련 뉴스가 있으면 반드시 아래 JSON 형식으로만 답해줘. JSON 외에 다른 말은 절대 쓰지 마.
title은 한국어로 번역해줘.
summary는 한국어로 3~4문장, 150자 이내로 작성해줘.
url은 원본 그대로 복사해줘.

출력 형식:
{{
  "relevant": true,
  "title": "한국어로 번역한 제목",
  "summary": "3~4문장 한국어 요약 (150자 이내)",
  "url": "https://원본URL",
  "source": "매체명"
}}

뉴스 목록:
{items}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    raw = response.choices[0].message.content.strip()

    try:
        raw = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(raw)
        if not result.get("relevant", False):
            return None
        return result
    except Exception:
        return None


# =========================
# AI 분석 — 경쟁사
# =========================

def analyze_competitor(news_list):
    """
    경쟁사 실제 비즈니스 뉴스만 필터링
    블로그, shop 리뷰, 중고차 경매 등 제외
    """

    if not news_list:
        return []

    items = "\n".join([
        f"{i+1}. [{n.get('source','')}] {n['title']} | {n['url']}"
        for i, n in enumerate(news_list[:20])
    ])

    prompt = f"""
아래는 윈도우 필름/PPF 경쟁사(XPEL, Llumar, 3M, Suntek, SolarGard) 관련 뉴스 목록이야.
이 중에서 반드시 해당 회사의 신제품 출시, 경영 전략, 실적, 파트너십, 인수합병, 
공시, 시장 확장 등 실제 비즈니스 관련 뉴스만 골라서 중요한 최대 2개를 선택해줘.

아래 항목은 절대 선택하지 마:
- 중고차 경매, 차량 리뷰
- 개인 블로그, shop 후기
- 회사와 직접 관련 없는 뉴스
- 단순 제품 사용 후기

관련성 있는 뉴스가 전혀 없으면 반드시 이것만 답해줘:
{{"relevant": false}}

관련 뉴스가 있으면 반드시 아래 JSON 형식으로만 답해줘. JSON 외에 다른 말은 절대 쓰지 마.
title은 한국어로 번역해줘.
summary는 한국어로 3~4문장, 150자 이내로 작성해줘.
url은 원본 그대로 복사해줘.
찾은 뉴스가 1개면 1개만, 2개면 2개 반환해줘.

출력 형식:
[
  {{
    "title": "한국어로 번역한 제목",
    "summary": "3~4문장 한국어 요약 (150자 이내)",
    "url": "https://원본URL",
    "source": "매체명"
  }}
]

뉴스 목록:
{items}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    raw = response.choices[0].message.content.strip()

    try:
        raw = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(raw)
        if isinstance(result, dict) and not result.get("relevant", True):
            return []
        if isinstance(result, list):
            return result
        return []
    except Exception:
        return []


# =========================
# INSIGHT — 태국/인도네시아/경쟁사 기반
# =========================

def generate_insight(th_item, id_item, comp_items):

    news_parts = []

    if th_item:
        news_parts.append(f"[태국] {th_item.get('title','')}: {th_item.get('summary','')}")
    if id_item:
        news_parts.append(f"[인도네시아] {id_item.get('title','')}: {id_item.get('summary','')}")
    for item in comp_items:
        if item:
            news_parts.append(f"[경쟁사] {item.get('title','')}: {item.get('summary','')}")

    if not news_parts:
        return "태국/인도네시아/경쟁사 관련 뉴스가 없어 인사이트를 생성할 수 없습니다."

    summary_text = "\n".join(news_parts)

    prompt = f"""
다음 태국/인도네시아/경쟁사 관련 뉴스를 보고,
윈도우 필름 및 PPF 자동차 애프터마켓 산업 관점에서
전략 인사이트와 액션 포인트를 3줄로 정리해줘. 한국어로.

{summary_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )

    return response.choices[0].message.content.strip()


# =========================
# NOTION 저장 (requests 직접 호출)
# =========================

def save_to_notion(date_str, usd, kospi, samsung,
                   global_items, th_item, id_item, comp_items, insight):

    def text(val):
        return {"rich_text": [{"text": {"content": str(val or "")[:2000]}}]}

    def url_prop(val):
        return {"url": val if val else None}

    g = global_items[:3]
    while len(g) < 3:
        g.append({"title": "", "summary": "", "url": "", "source": ""})

    c = comp_items[:2] if comp_items else []
    while len(c) < 2:
        c.append({"title": "", "summary": "", "url": ""})

    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    payload = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": f"Daily Briefing {date_str}"}}]},
            "날짜": {"date": {"start": date_str}},
            "USD/KRW": text(usd),
            "KOSPI": text(kospi),
            "Samsung": text(samsung),
            "Global 1 제목": text(g[0].get("title", "")),
            "Global 1 요약": text(g[0].get("summary", "")),
            "Global 1 URL": url_prop(g[0].get("url", "")),
            "Global 2 제목": text(g[1].get("title", "")),
            "Global 2 요약": text(g[1].get("summary", "")),
            "Global 2 URL": url_prop(g[1].get("url", "")),
            "Global 3 제목": text(g[2].get("title", "")),
            "Global 3 요약": text(g[2].get("summary", "")),
            "Global 3 URL": url_prop(g[2].get("url", "")),
            "태국 제목": text(th_item.get("title", "") if th_item else "관련 뉴스 없음"),
            "태국 요약": text(th_item.get("summary", "") if th_item else ""),
            "태국 URL": url_prop(th_item.get("url", "") if th_item else ""),
            "인도네시아 제목": text(id_item.get("title", "") if id_item else "관련 뉴스 없음"),
            "인도네시아 요약": text(id_item.get("summary", "") if id_item else ""),
            "인도네시아 URL": url_prop(id_item.get("url", "") if id_item else ""),
            "경쟁사 1 제목": text(c[0].get("title", "관련 뉴스 없음")),
            "경쟁사 1 요약": text(c[0].get("summary", "")),
            "경쟁사 1 URL": url_prop(c[0].get("url", "")),
            "경쟁사 2 제목": text(c[1].get("title", "관련 뉴스 없음")),
            "경쟁사 2 요약": text(c[1].get("summary", "")),
            "경쟁사 2 URL": url_prop(c[1].get("url", "")),
            "Insight": text(insight),
        }
    }

    try:
        res = requests.post(
            "https://api.notion.com/v1/pages",
            headers=headers,
            json=payload,
            timeout=15
        )
        if res.status_code == 200:
            print("Notion 저장 완료")
        else:
            print("Notion 저장 실패:", res.status_code, res.text[:200])
    except Exception as e:
        print("Notion 저장 실패:", str(e))


# =========================
# TELEGRAM 포맷 헬퍼
# =========================

def format_news_block(item, index=None):

    numbers = ["1️⃣", "2️⃣", "3️⃣"]
    prefix = numbers[index] + " " if index is not None and index < len(numbers) else "• "

    title = item.get("title", "")
    summary = item.get("summary", "")
    url = item.get("url", "")
    source = item.get("source", "")

    block = f"{prefix}<b>{title}</b>\n"
    if source:
        block += f"<i>📰 {source}</i>\n"
    if summary:
        block += f"\n{summary}\n"
    if url:
        block += f'\n🔗 <a href="{url}">Source →</a>'

    return block


def format_single_block(item):

    if item is None:
        return "관련 뉴스 없음 (24h)"

    title = item.get("title", "")
    summary = item.get("summary", "")
    url = item.get("url", "")
    source = item.get("source", "")

    if not title:
        return "관련 뉴스 없음 (24h)"

    block = f"<b>{title}</b>\n"
    if source:
        block += f"<i>📰 {source}</i>\n"
    if summary:
        block += f"\n{summary}\n"
    if url:
        block += f'\n🔗 <a href="{url}">Source →</a>'

    return block


def format_competitor_blocks(comp_items):

    if not comp_items:
        return "관련 뉴스 없음 (24h)"

    blocks = [format_single_block(item) for item in comp_items[:2]]
    return "\n\n─────────────────\n\n".join(blocks)


# =========================
# TELEGRAM 전송
# =========================

def send_telegram(msg):

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    if len(msg) > 4096:
        msg = msg[:4090] + "\n..."

    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    requests.post(url, json=payload)


# =========================
# MAIN FUNCTION
# =========================

def jeremy_briefing(request=None):

    # 시장 데이터
    usd, kospi, samsung = get_market()

    # 캘린더
    calendar_events = get_calendar_events()
    calendar_block = format_calendar(calendar_events)

    # 뉴스 수집
    global_news = get_top_headlines()
    th_news = get_news(TH_QUERIES, page_size=5, sort_by="publishedAt")
    id_news = get_news(ID_QUERIES, page_size=5, sort_by="publishedAt")
    comp_news = get_news(COMPETITOR_QUERIES, page_size=5, sort_by="publishedAt")

    # AI 분석
    try:
        global_items = analyze_global(global_news)
    except Exception as e:
        print("OpenAI error (global):", str(e))
        global_items = [{"title": "AI 분석 실패", "summary": str(e)[:100], "url": "", "source": ""}]

    try:
        th_item = analyze_regional(th_news, "태국")
    except Exception as e:
        print("OpenAI error (thailand):", str(e))
        th_item = None

    try:
        id_item = analyze_regional(id_news, "인도네시아")
    except Exception as e:
        print("OpenAI error (indonesia):", str(e))
        id_item = None

    try:
        comp_items = analyze_competitor(comp_news)
    except Exception as e:
        print("OpenAI error (competitor):", str(e))
        comp_items = []

    try:
        insight = generate_insight(th_item, id_item, comp_items)
    except Exception as e:
        print("OpenAI error (insight):", str(e))
        insight = "인사이트 생성 실패"

    # 날짜
    now_kst = datetime.now(timezone.utc) + timedelta(hours=9)
    date_str = now_kst.strftime("%Y.%m.%d %H:%M")
    date_only = now_kst.strftime("%Y-%m-%d")

    # Notion 저장
    try:
        save_to_notion(
            date_only, usd, kospi, samsung,
            global_items, th_item, id_item, comp_items, insight
        )
    except Exception as e:
        print("Notion error:", str(e))

    # Global Top3 포맷
    global_blocks = "\n\n─────────────────\n\n".join([
        format_news_block(item, i) for i, item in enumerate(global_items[:3])
    ])

    # 최종 메시지
    msg = f"""<b>📋 Daily Briefing</b>  <i>{date_str} KST</i>

<b>📊 Market Data</b>
USD/KRW  {usd}
KOSPI  {kospi}
Samsung  {samsung}

━━━━━━━━━━━━━━━━━━━━
{calendar_block}

━━━━━━━━━━━━━━━━━━━━
<b>🌍 Global Top3</b>

{global_blocks}

━━━━━━━━━━━━━━━━━━━━
<b>🇹🇭 Thailand Automotive</b>

{format_single_block(th_item)}

━━━━━━━━━━━━━━━━━━━━
<b>🇮🇩 Indonesia Automotive</b>

{format_single_block(id_item)}

━━━━━━━━━━━━━━━━━━━━
<b>🏁 Competitor News</b>

{format_competitor_blocks(comp_items)}

━━━━━━━━━━━━━━━━━━━━
<b>💡 Insight & Action</b>

{insight}"""

    send_telegram(msg)

    return "Daily briefing sent"
