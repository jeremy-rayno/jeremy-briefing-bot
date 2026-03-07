import os
import requests
import feedparser
from flask import Flask, request
from datetime import datetime, timedelta
from urllib.parse import quote
from difflib import SequenceMatcher
from bs4 import BeautifulSoup
from openai import OpenAI

app = Flask(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

client = OpenAI(api_key=OPENAI_API_KEY)

HEADERS = {"User-Agent": "Mozilla/5.0"}

# -------------------------
# trusted sources
# -------------------------

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

BLOCKED_SOURCES = [
"blog",
"shop",
"store",
"amazon",
"alibaba",
"prnewswire",
"presswire",
"medium"
]

# -------------------------
# google news feeds
# -------------------------

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
"https://news.google.com/rss/search?q=xpel+automotive+film",
"https://news.google.com/rss/search?q=3M+automotive+film",
"https://news.google.com/rss/search?q=llumar+window+film",
"https://news.google.com/rss/search?q=solargard+window+film"
]

# -------------------------
# get real url
# -------------------------

def get_real_url(url):
    try:
        r = requests.get(url, allow_redirects=True, timeout=5)
        return r.url
    except:
        return url

# -------------------------
# duplicate check
# -------------------------

def is_duplicate(title, titles):
    for t in titles:
        sim = SequenceMatcher(None, title, t).ratio()
        if sim > 0.8:
            return True
    return False

# -------------------------
# trusted media filter
# -------------------------

def is_trusted(url):

    for b in BLOCKED_SOURCES:
        if b in url:
            return False

    for t in TRUSTED_SOURCES:
        if t in url:
            return True

    for c in COMPETITOR_SOURCES:
        if c in url:
            return True

    return False

# -------------------------
# 24h filter
# -------------------------

def within_24h(entry):

    try:
        published = datetime(*entry.published_parsed[:6])
        now = datetime.utcnow()
        return now - published < timedelta(hours=24)
    except:
        return False

# -------------------------
# get rss news
# -------------------------

def get_news(feed_urls):

    news = []
    titles = []

    for url in feed_urls:

        feed = feedparser.parse(url)

        for entry in feed.entries:

            if not within_24h(entry):
                continue

            link = get_real_url(entry.link)

            if not is_trusted(link):
                continue

            if is_duplicate(entry.title, titles):
                continue

            titles.append(entry.title)

            news.append({
                "title": entry.title,
                "url": link
            })

    return news

# -------------------------
# AI summarize + score
# -------------------------

def analyze_news(news):

    prompt = f"""
    다음 뉴스 제목 목록을 분석하라.

    각 뉴스에 대해:
    1. 한국어 2줄 요약
    2. 중요도 점수 (1~10)

    뉴스:
    {news}
    """

    r = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role":"user","content":prompt}]
    )

    return r.choices[0].message.content

# -------------------------
# market data
# -------------------------

def get_market():

    r = requests.get("https://finance.naver.com/marketindex/",headers=HEADERS)
    soup = BeautifulSoup(r.text,"html.parser")
    usd = soup.select_one("span.value").text

    r = requests.get("https://finance.naver.com/sise/",headers=HEADERS)
    soup = BeautifulSoup(r.text,"html.parser")
    kospi = soup.select_one("#KOSPI_now").text

    r = requests.get("https://finance.naver.com/item/main.naver?code=005930",headers=HEADERS)
    soup = BeautifulSoup(r.text,"html.parser")
    samsung = soup.select_one("p.no_today span.blind").text

    return usd,kospi,samsung

# -------------------------
# telegram send
# -------------------------

def send_telegram(msg):

    url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload={
        "chat_id":CHAT_ID,
        "text":msg,
        "parse_mode":"HTML"
    }

    requests.post(url,json=payload)

# -------------------------
# briefing
# -------------------------

@app.route("/")
def jeremy_briefing():

    usd,kospi,samsung=get_market()

    global_news=get_news(GLOBAL_FEEDS)
    th_news=get_news(TH_FEEDS)
    id_news=get_news(ID_FEEDS)
    comp_news=get_news(COMPETITOR_FEEDS)

    global_analysis=analyze_news(global_news[:10])

    msg=f"""
<b>Jeremy Briefing</b>

Market Data
USD/KRW {usd}
KOSPI {kospi}
Samsung {samsung}

<b>Global Top3</b>
{global_analysis}

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
"""

    send_telegram(msg)

    return "Jeremy briefing sent"
