import requests
import feedparser
import json
import re
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
# NEWS FETCH (24h 필터)
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
# AI 분석 — Global Top3 (JSON 반환)
# =========================

def analyze_global(news_list):
    """
    JSON 형식으로 받아서 파싱 실패 원천 차단
    반환: [{"title": ..., "summary": ..., "url": ...}, ...]
    """

    items = "\n".join([
        f"{i+1}. {n['title']} | {n['url']}"
        for i, n in enumerate(news_list[:10])
    ])

    prompt = f"""
아래 뉴스 목록에서 가장 중요한 3개를 골라 분석해줘.
반드시 아래 JSON 형식으로만 답해줘. JSON 외에 다른 말은 절대 쓰지 마.
title은 한국어로 번역해줘.
summary는 한국어로 3~4문장, 150자 이내로 작성해줘.
url은 원본 그대로 복사해줘. 절대 바꾸거나 생략하지 마.

출력 형식:
[
  {{
    "title": "한국어로 번역한 뉴스 제목",
    "summary": "3~4문장 한국어 요약 (150자 이내)",
    "url": "https://원본URL"
  }},
  {{
    "title": "...",
    "summary": "...",
    "url": "..."
  }},
  {{
    "title": "...",
    "summary": "...",
    "url": "..."
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
        return json.loads(raw)
    except Exception:
        return [{"title": "AI 분석 실패", "summary": raw[:200], "url": ""}]


# =========================
# AI 분석 — 단일 뉴스 (번역 + 요약)
# =========================

def analyze_single(title, url):
    """
    태국/인도네시아/경쟁사 뉴스 한국어 번역 + 요약
    반환: {"title": ..., "summary": ..., "url": ...}
    """

    if not title or title == "관련 뉴스 없음 (24h)":
        return {"title": "관련 뉴스 없음 (24h)", "summary": "", "url": ""}

    prompt = f"""
아래 영어 뉴스 제목을 한국어로 번역하고 3~4문장으로 요약해줘.
반드시 아래 JSON 형식으로만 답해줘. JSON 외에 다른 말은 절대 쓰지 마.
summary는 150자 이내로 작성해줘.

뉴스 제목: {title}

출력 형식:
{{
  "title": "한국어로 번역한 제목",
  "summary": "3~4문장 한국어 요약 (150자 이내)"
}}
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
        result["url"] = url
        return result
    except Exception:
        return {"title": title, "summary": "", "url": url}


# =========================
# INSIGHT
# =========================

def generate_insight(news_items):

    summary_text = "\n".join([
        f"- {n['title']}: {n['summary']}"
        for n in news_items
        if isinstance(n, dict)
    ])

    prompt = f"""
다음 글로벌 뉴스 요약을 보고 자동차 애프터마켓 산업 관점에서
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
# TELEGRAM 포맷 헬퍼
# =========================

def format_news_block(item, index=None):
    """
    뉴스 하나를 Telegram HTML 블록으로 변환 (번호 포함)
    """
    numbers = ["1️⃣", "2️⃣", "3️⃣"]
    prefix = numbers[index] + " " if index is not None and index < len(numbers) else "• "

    title = item.get("title", "")
    summary = item.get("summary", "")
    url = item.get("url", "")

    block = f"{prefix}<b>{title}</b>\n"
    if summary:
        block += f"\n{summary}\n"
    if url:
        block += f'\n🔗 <a href="{url}">Source →</a>'

    return block


def format_single_block(item):
    """
    태국/인도네시아/경쟁사 단일 뉴스 블록
    """
    title = item.get("title", "관련 뉴스 없음 (24h)")
    summary = item.get("summary", "")
    url = item.get("url", "")

    if title == "관련 뉴스 없음 (24h)":
        return "관련 뉴스 없음 (24h)"

    block = f"<b>{title}</b>\n"
    if summary:
        block += f"\n{summary}\n"
    if url:
        block += f'\n🔗 <a href="{url}">Source →</a>'

    return block


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

    # 뉴스 수집
    global_news = get_news(GLOBAL_FEEDS)
    th_news = get_news(TH_FEEDS)
    id_news = get_news(ID_FEEDS)
    comp_news = get_news(COMPETITOR_FEEDS)

    # Global Top3 AI 분석
    try:
        global_items = analyze_global(global_news)
    except Exception as e:
        print("OpenAI error (global):", str(e))
        global_items = [{"title": "AI 분석 실패", "summary": str(e)[:100], "url": ""}]

    # Insight 생성
    try:
        insight = generate_insight(global_items)
    except Exception as e:
        print("OpenAI error (insight):", str(e))
        insight = "인사이트 생성 실패"

    # 태국 뉴스
    try:
        th_item = analyze_single(
            th_news[0]["title"] if th_news else "관련 뉴스 없음 (24h)",
            th_news[0]["url"] if th_news else ""
        )
    except Exception:
        th_item = {
            "title": th_news[0]["title"] if th_news else "관련 뉴스 없음 (24h)",
            "summary": "",
            "url": th_news[0]["url"] if th_news else ""
        }

    # 인도네시아 뉴스
    try:
        id_item = analyze_single(
            id_news[0]["title"] if id_news else "관련 뉴스 없음 (24h)",
            id_news[0]["url"] if id_news else ""
        )
    except Exception:
        id_item = {
            "title": id_news[0]["title"] if id_news else "관련 뉴스 없음 (24h)",
            "summary": "",
            "url": id_news[0]["url"] if id_news else ""
        }

    # 경쟁사 뉴스 (2개)
    comp_items = []
    for n in comp_news[:2]:
        try:
            item = analyze_single(n["title"], n["url"])
        except Exception:
            item = {"title": n["title"], "summary": "", "url": n["url"]}
        comp_items.append(item)

    while len(comp_items) < 2:
        comp_items.append({"title": "관련 뉴스 없음 (24h)", "summary": "", "url": ""})

    # Global Top3 포맷
    global_blocks = "\n\n─────────────────\n\n".join([
        format_news_block(item, i) for i, item in enumerate(global_items[:3])
    ])

    # 날짜
    now_kst = datetime.now(timezone.utc) + timedelta(hours=9)
    date_str = now_kst.strftime("%Y.%m.%d %H:%M")

    # 최종 메시지
    msg = f"""<b>📋 Jeremy Briefing</b>  <i>{date_str} KST</i>

<b>📊 Market Data</b>
USD/KRW  {usd}
KOSPI  {kospi}
Samsung  {samsung}

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

{format_single_block(comp_items[0])}

─────────────────

{format_single_block(comp_items[1])}

━━━━━━━━━━━━━━━━━━━━
<b>💡 Jeremy Insight & Action</b>

{insight}"""

    send_telegram(msg)

    return "Jeremy briefing sent"
