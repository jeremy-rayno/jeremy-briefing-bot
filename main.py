import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
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
# NEWS FETCH
# =========================

def get_news(feeds):

    news = []

    for url in feeds:
        feed = feedparser.parse(url)

        for entry in feed.entries:

            title = entry.title
            link = entry.link

            news.append({
                "title": title,
                "url": link
            })

    return news


# =========================
# AI ANALYSIS
# =========================

def analyze_global(news_list):

    titles = "\n".join([n["title"] for n in news_list[:5]])

    prompt = f"""
다음 글로벌 뉴스 제목을 읽고 가장 중요한 3개를 한국어로 요약해줘.

뉴스:
{titles}

형식:
- 핵심 뉴스1
- 핵심 뉴스2
- 핵심 뉴스3
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content


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

    return response.choices[0].message.content


# =========================
# TELEGRAM
# =========================

def send_telegram(msg):

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

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

    usd, kospi, samsung = get_market()

    global_news = get_news(GLOBAL_FEEDS)
    th_news = get_news(TH_FEEDS)
    id_news = get_news(ID_FEEDS)
    comp_news = get_news(COMPETITOR_FEEDS)

    # Thailand fallback
    if th_news:
        th_title = th_news[0]["title"]
        th_url = th_news[0]["url"]
    else:
        th_title = "관련 뉴스 없음 (24h)"
        th_url = ""

    # Indonesia fallback
    if id_news:
        id_title = id_news[0]["title"]
        id_url = id_news[0]["url"]
    else:
        id_title = "관련 뉴스 없음 (24h)"
        id_url = ""

    # Competitor fallback
    comp_titles = []
    comp_urls = []

    for n in comp_news[:2]:
        comp_titles.append(n["title"])
        comp_urls.append(n["url"])

    while len(comp_titles) < 2:
        comp_titles.append("관련 뉴스 없음 (24h)")
        comp_urls.append("")

    # AI analysis
    try:
        global_result = analyze_global(global_news[:10])
    except Exception as e:
        print("OpenAI error:", str(e))
        global_result = "AI 분석 실패 (OpenAI quota 또는 API 오류)"

    insight = generate_insight(global_result)

    msg = f"""
<b>Jeremy Briefing</b>

Market Data
USD/KRW {usd}
KOSPI {kospi}
Samsung {samsung}

<b>Global Top3</b>
{global_result}

<b>Thailand Automotive Aftermarket</b>
{th_title}
{f'<a href="{th_url}">Source →</a>' if th_url else ''}

<b>Indonesia Automotive Aftermarket</b>
{id_title}
{f'<a href="{id_url}">Source →</a>' if id_url else ''}

<b>Tinting Competitor News</b>

{comp_titles[0]}
{f'<a href="{comp_urls[0]}">Source →</a>' if comp_urls[0] else ''}

{comp_titles[1]}
{f'<a href="{comp_urls[1]}">Source →</a>' if comp_urls[1] else ''}

<b>Jeremy Insight & Action</b>
{insight}
"""

    send_telegram(msg)

    return "Jeremy briefing sent"
