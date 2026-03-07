import os
import requests
import feedparser
from datetime import datetime, timedelta
from urllib.parse import quote
from difflib import SequenceMatcher
from bs4 import BeautifulSoup
from openai import OpenAI

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

client = OpenAI(api_key=OPENAI_API_KEY)

HEADERS = {"User-Agent": "Mozilla/5.0"}

# -----------------------------
# Trusted media whitelist
# -----------------------------

TRUSTED_SOURCES = [
"reuters.com",
"bloomberg.com",
"ft.com",
"cnbc.com",
"nikkei.com",
"scmp.com",
"bangkokpost.com",
"nationthailand.com",
"jakartapost.com",
"straitstimes.com"
]

COMPETITOR_SOURCES = [
"xpel.com",
"3m.com",
"eastman.com",
"llumar.com",
"solargard.com"
]

BLOCKED = [
"blog",
"shop",
"store",
"amazon",
"alibaba",
"prnewswire",
"presswire",
"medium"
]

# -----------------------------
# RSS feeds
# -----------------------------

GLOBAL_FEEDS = [
"https://news.google.com/rss/search?q=global+economy",
"https://news.google.com/rss/search?q=global+business"
]

TH_FEEDS = [
"https://news.google.com/rss/search?q=Thailand+automotive+aftermarket"
]

ID_FEEDS = [
"https://news.google.com/rss/search?q=Indonesia+automotive+aftermarket"
]

COMPETITOR_FEEDS = [
"https://news.google.com/rss/search?q=xpel+window+film",
"https://news.google.com/rss/search?q=3M+window+film",
"https://news.google.com/rss/search?q=llumar+window+film",
"https://news.google.com/rss/search?q=solargard+window+film"
]

# -----------------------------
# Real article URL
# -----------------------------

def get_real_url(url):
    try:
        r = requests.get(url, allow_redirects=True, timeout=5)
        return r.url
    except:
        return url

# -----------------------------
# Duplicate check
# -----------------------------

def is_duplicate(title, titles):
    for t in titles:
        sim = SequenceMatcher(None, title, t).ratio()
        if sim > 0.8:
            return True
    return False

# -----------------------------
# Trusted source check
# -----------------------------

def trusted(url):

    for b in BLOCKED:
        if b in url:
            return False

    for t in TRUSTED_SOURCES:
        if t in url:
            return True

    for c in COMPETITOR_SOURCES:
        if c in url:
            return True

    return False

# -----------------------------
# 24 hour filter
# -----------------------------

def within_24h(entry):

    try:
        published = datetime(*entry.published_parsed[:6])
        now = datetime.utcnow()

        if now - published < timedelta(hours=24):
            return True

    except:
        pass

    return False

# -----------------------------
# Fetch news
# -----------------------------

def get_news(feed_urls):

    news=[]
    titles=[]

    for url in feed_urls:

        feed=feedparser.parse(url)

        for e in feed.entries:

            if not within_24h(e):
                continue

            link=get_real_url(e.link)

            if not trusted(link):
                continue

            if is_duplicate(e.title,titles):
                continue

            titles.append(e.title)

            news.append({
                "title":e.title,
                "url":link
            })

    return news

# -----------------------------
# AI analyze news
# -----------------------------

def analyze_global(news):

    prompt=f"""
다음 뉴스 제목 목록에서

1️⃣ 산업 영향이 있는 뉴스만 선택
2️⃣ 중요도 평가
3️⃣ 상위 3개 뉴스 선정
4️⃣ 한국어 요약 작성

뉴스:
{news}

출력 형식:

1. 제목
요약
Source
"""

    r=client.responses.create(
        model="gpt-5-mini",
        input=prompt
    )

    return r.output_text

# -----------------------------
# Insight + Action
# -----------------------------

def generate_insight(text):

    prompt=f"""
다음 뉴스들을 기반으로

1️⃣ Jeremy Insight
2️⃣ Action Point

한국어로 작성

뉴스:
{text}
"""

    r=client.responses.create(
        model="gpt-5-mini",
        input=prompt
    )

    return r.output_text

# -----------------------------
# Market data
# -----------------------------

def get_market():

    r=requests.get("https://finance.naver.com/marketindex/",headers=HEADERS)
    soup=BeautifulSoup(r.text,"html.parser")
    usd=soup.select_one("span.value").text

    r=requests.get("https://finance.naver.com/sise/",headers=HEADERS)
    soup=BeautifulSoup(r.text,"html.parser")
    kospi=soup.select_one("#KOSPI_now").text

    r=requests.get("https://finance.naver.com/item/main.naver?code=005930",headers=HEADERS)
    soup=BeautifulSoup(r.text,"html.parser")
    samsung=soup.select_one("p.no_today span.blind").text

    return usd,kospi,samsung

# -----------------------------
# Telegram
# -----------------------------

def send_telegram(msg):

    url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload={
        "chat_id":CHAT_ID,
        "text":msg,
        "parse_mode":"HTML"
    }

    requests.post(url,json=payload)

# -----------------------------
# MAIN ENTRY (Cloud Run HTTP)
# -----------------------------

def jeremy_briefing(request=None):
    
    usd,kospi,samsung=get_market()

    global_news=get_news(GLOBAL_FEEDS)
    th_news=get_news(TH_FEEDS)
    id_news=get_news(ID_FEEDS)
    comp_news=get_news(COMPETITOR_FEEDS)

    global_result=analyze_global(global_news[:10])

    insight=generate_insight(global_result)

    msg=f"""
<b>Jeremy Briefing</b>

Market Data
USD/KRW {usd}
KOSPI {kospi}
Samsung {samsung}

<b>Global Top3</b>
{global_result}

<b>Thailand Automotive Aftermarket</b>
{th_news[0]["title"]}
<a href="{th_news[0]["url"]}">Source →</a>

<b>Indonesia Automotive Aftermarket</b>
{id_news[0]["title"]}
<a href="{id_news[0]["url"]}">Source →</a>

<b>Tinting Competitor News</b>

{comp_news[0]["title"]}
<a href="{comp_news[0]["url"]}">Source →</a>

{comp_news[1]["title"]}
<a href="{comp_news[1]["url"]}">Source →</a>

<b>Jeremy Insight & Action</b>
{insight}
"""

    send_telegram(msg)

    return "Jeremy briefing sent"
