import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from openai import OpenAI
import os

# =========================
# ENV
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# RSS FEEDS
# =========================

GLOBAL_FEEDS = [
    "https://news.google.com/rss/search?q=global+economy&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=global+automotive&hl=en-US&gl=US&ceid=US:en"
]

TH_FEEDS = [
    "https://news.google.com/rss/search?q=Thailand+automotive&hl=en-US&gl=US&ceid=US:en"
]

ID_FEEDS = [
    "https://news.google.com/rss/search?q=Indonesia+automotive&hl=en-US&gl=US&ceid=US:en"
]

COMPETITOR_FEEDS = [
    "https://news.google.com/rss/search?q=XPEL+window+film&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=3M+window+film&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Llumar+window+film&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=SolarGard+window+film&hl=en-US&gl=US&ceid=US:en"
]

# =========================
# MARKET DATA
# =========================

def get_market():

    headers = {"User-Agent": "Mozilla/5.0"}

    # USD/KRW
    fx_url = "https://finance.naver.com/marketindex/"
    res = requests.get(fx_url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    usd = soup.select_one("span.value").text

    # KOSPI
    kospi_url = "https://finance.naver.com/sise/"
    res = requests.get(kospi_url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    kospi = soup.select_one("#KOSPI_now").text

    # Samsung
    samsung_url = "https://finance.naver.com/item/main.naver?code=005930"
    res = requests.get(samsung_url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    samsung = soup.select_one("p.no_today span.blind").text

    return usd, kospi, samsung


# =========================
# NEWS FETCH (24h 필터 포함)
# =========================

def get_news(feeds, hours=24):

    news = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    for url in feeds:
        feed = feedparser.parse(url)

        for entry in feed.entries:
            published = entry.get("published_parsed")
            if published:
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue

            news.append({
                "title": entry.title,
                "url": entry.link
            })

    return news


# =========================
# AI ANALYSIS — Global Top3 (URL 포함)
# =========================

def analyze_global(news_list):

    # 제목 + URL 함께 전달
    items = "\n".join([
        f"{i+1}. {n['title']} | {n['url']}"
        for i, n in enumerate(news_list[:10])
    ])

    prompt = f"""
다음 글로벌 뉴스 목록을 읽고 가장 중요한 3개를 골라 한국어로 요약해줘.
각 항목에 원문 URL도 함께 포함해줘.

뉴스 목록 (제목 | URL):
{items}

반드시 아래 형식으로만 답해줘 (다른 말 없이):
1. [한국어 요약 제목] | [URL]
2. [한국어 요약 제목] | [URL]
3. [한국어 요약 제목] | [URL]
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content.strip()


# =========================
# 번역 — 태국/인도네시아 뉴스
# =========================

def translate_title(title):

    if not title or title == "관련 뉴스 없음 (24h)":
        return title

    prompt = f"""
다음 영어 뉴스 제목을 자연스러운 한국어로 번역해줘. 번역문만 출력해줘.

{title}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content.strip()


# =========================
# INSIGHT
# =========================

def generate_insight(text):

    prompt = f"""
다음 뉴스 요약을 보고 자동차 애프터마켓 산업 관점에서
전략 인사이트와 액션 포인트를 3줄로 정리해줘.

{text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content.strip()


# =========================
# Global Top3 파싱 → Telegram HTML 변환
# =========================

def format_global_top3(raw_text):
    """
    AI가 반환한 텍스트:
    1. 요약 제목 | https://...
    2. 요약 제목 | https://...
    3. 요약 제목 | https://...
    → Telegram HTML 포맷으로 변환
    """
    lines = []
    for line in raw_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            parts = line.split("|", 1)
            title_part = parts[0].strip().lstrip("123. ").strip()
            url_part = parts[1].strip()
            if url_part.startswith("http"):
                lines.append(f"• {title_part}\n  <a href=\"{url_part}\">Source →</a>")
            else:
                lines.append(f"• {title_part}")
        else:
            lines.append(f"• {line.lstrip('123. ').strip()}")
    return "\n\n".join(lines)


# =========================
# TELEGRAM
# =========================

def send_telegram(msg):

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # Telegram 4096자 제한 대응
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

    # 뉴스 수집
    global_news = get_news(GLOBAL_FEEDS)
    th_news = get_news(TH_FEEDS)
    id_news = get_news(ID_FEEDS)
    comp_news = get_news(COMPETITOR_FEEDS)

    # Thailand
    if th_news:
        th_title_raw = th_news[0]["title"]
        th_url = th_news[0]["url"]
        try:
            th_title = translate_title(th_title_raw)
        except Exception:
            th_title = th_title_raw
    else:
        th_title = "관련 뉴스 없음 (24h)"
        th_url = ""

    # Indonesia
    if id_news:
        id_title_raw = id_news[0]["title"]
        id_url = id_news[0]["url"]
        try:
            id_title = translate_title(id_title_raw)
        except Exception:
            id_title = id_title_raw
    else:
        id_title = "관련 뉴스 없음 (24h)"
        id_url = ""

    # Competitor
    comp_titles = []
    comp_urls = []

    for n in comp_news[:2]:
        try:
            translated = translate_title(n["title"])
        except Exception:
            translated = n["title"]
        comp_titles.append(translated)
        comp_urls.append(n["url"])

    while len(comp_titles) < 2:
        comp_titles.append("관련 뉴스 없음 (24h)")
        comp_urls.append("")

    # AI 분석
    try:
        global_raw = analyze_global(global_news)
        global_formatted = format_global_top3(global_raw)
    except Exception as e:
        print("OpenAI error (global):", str(e))
        global_raw = "AI 분석 실패 (OpenAI quota 또는 API 오류)"
        global_formatted = global_raw

    try:
        insight = generate_insight(global_raw)
    except Exception as e:
        print("OpenAI error (insight):", str(e))
        insight = "인사이트 생성 실패"

    # 메시지 조합
    msg = f"""<b>📋 Jeremy Briefing</b>

<b>📊 Market Data</b>
USD/KRW {usd}
KOSPI {kospi}
Samsung {samsung}

<b>🌍 Global Top3</b>
{global_formatted}

<b>🇹🇭 Thailand Automotive Aftermarket</b>
{th_title}
{f'<a href="{th_url}">Source →</a>' if th_url else ''}

<b>🇮🇩 Indonesia Automotive Aftermarket</b>
{id_title}
{f'<a href="{id_url}">Source →</a>' if id_url else ''}

<b>🏁 Tinting Competitor News</b>

{comp_titles[0]}
{f'<a href="{comp_urls[0]}">Source →</a>' if comp_urls[0] else ''}

{comp_titles[1]}
{f'<a href="{comp_urls[1]}">Source →</a>' if comp_urls[1] else ''}

<b>💡 Jeremy Insight & Action</b>
{insight}"""

    send_telegram(msg)

    return "Jeremy briefing sent"
