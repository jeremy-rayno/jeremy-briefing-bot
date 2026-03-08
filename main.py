import requests
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
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# =========================
# NEWS QUERIES
# =========================

GLOBAL_QUERIES = [
    "global economy",
    "global automotive"
]

TH_QUERIES = [
    "Thailand automotive"
]

ID_QUERIES = [
    "Indonesia automotive"
]

COMPETITOR_QUERIES = [
    "XPEL window film",
    "3M window film",
    "Llumar window film",
    "SolarGard window film"
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
# NEWS FETCH — NewsAPI (무료플랜 호환)
# =========================

def get_news(queries, page_size=5):
    """
    NewsAPI로 최신 뉴스 수집
    - 무료플랜: from 파라미터 제거, sortBy=publishedAt 사용
    - 실제 기사 URL 반환
    """

    news = []

    for query in queries:
        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": query,
                "sortBy": "publishedAt",   # 최신순 정렬
                "pageSize": page_size,
                "language": "en",
                "apiKey": NEWS_API_KEY
            }
            res = requests.get(url, params=params, timeout=10)
            data = res.json()

            # 디버깅용 로그
            print(f"NewsAPI [{query}] status: {data.get('status')} / totalResults: {data.get('totalResults', 0)}")

            if data.get("status") == "ok":
                for article in data.get("articles", []):
                    title = article.get("title", "")
                    article_url = article.get("url", "")
                    source = article.get("source", {}).get("name", "")

                    # 삭제되거나 빈 기사 제외
                    if not title or title == "[Removed]":
                        continue
                    if not article_url:
                        continue

                    news.append({
                        "title": title,
                        "url": article_url,
                        "source": source
                    })
            else:
                # API 에러 상세 로그
                print(f"NewsAPI error [{query}]: {data.get('code')} / {data.get('message')}")

        except Exception as e:
            print(f"NewsAPI exception ({query}):", str(e))

    return news


# =========================
# AI 분석 — Global Top3 (JSON 반환)
# =========================

def analyze_global(news_list):
    """
    JSON 형식으로 받아서 파싱 실패 원천 차단
    반환: [{"title": ..., "summary": ..., "url": ..., "source": ...}, ...]
    """

    if not news_list:
        return [{"title": "수집된 뉴스 없음", "summary": "", "url": "", "source": ""}]

    items = "\n".join([
        f"{i+1}. [{n.get('source','')}] {n['title']} | {n['url']}"
        for i, n in enumerate(news_list[:10])
    ])

    prompt = f"""
아래 뉴스 목록에서 자동차 산업 및 글로벌 경제 관점에서 가장 중요한 3개를 골라 분석해줘.
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
  {{
    "title": "...",
    "summary": "...",
    "url": "...",
    "source": "..."
  }},
  {{
    "title": "...",
    "summary": "...",
    "url": "...",
    "source": "..."
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
        return [{"title": "AI 분석 실패", "summary": raw[:200], "url": "", "source": ""}]


# =========================
# AI 분석 — 단일 뉴스 (번역 + 요약)
# =========================

def analyze_single(title, url, source=""):
    """
    태국/인도네시아/경쟁사 뉴스 한국어 번역 + 요약
    반환: {"title": ..., "summary": ..., "url": ..., "source": ...}
    """

    if not title or title == "관련 뉴스 없음 (24h)":
        return {"title": "관련 뉴스 없음 (24h)", "summary": "", "url": "", "source": ""}

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
        result["source"] = source
        return result
    except Exception:
        return {"title": title, "summary": "", "url": url, "source": source}


# =========================
# INSIGHT
# =========================

def generate_insight(news_items):

    summary_text = "\n".join([
        f"- {n['title']}: {n['summary']}"
        for n in news_items
        if isinstance(n, dict) and n.get('title')
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

    title = item.get("title", "관련 뉴스 없음 (24h)")
    summary = item.get("summary", "")
    url = item.get("url", "")
    source = item.get("source", "")

    if title == "관련 뉴스 없음 (24h)":
        return "관련 뉴스 없음 (24h)"

    block = f"<b>{title}</b>\n"
    if source:
        block += f"<i>📰 {source}</i>\n"
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

    # 뉴스 수집 (NewsAPI)
    global_news = get_news(GLOBAL_QUERIES, page_size=5)
    th_news = get_news(TH_QUERIES, page_size=3)
    id_news = get_news(ID_QUERIES, page_size=3)
    comp_news = get_news(COMPETITOR_QUERIES, page_size=2)

    # Global Top3 AI 분석
    try:
        global_items = analyze_global(global_news)
    except Exception as e:
        print("OpenAI error (global):", str(e))
        global_items = [{"title": "AI 분석 실패", "summary": str(e)[:100], "url": "", "source": ""}]

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
            th_news[0]["url"] if th_news else "",
            th_news[0].get("source", "") if th_news else ""
        )
    except Exception:
        th_item = {
            "title": th_news[0]["title"] if th_news else "관련 뉴스 없음 (24h)",
            "summary": "",
            "url": th_news[0]["url"] if th_news else "",
            "source": th_news[0].get("source", "") if th_news else ""
        }

    # 인도네시아 뉴스
    try:
        id_item = analyze_single(
            id_news[0]["title"] if id_news else "관련 뉴스 없음 (24h)",
            id_news[0]["url"] if id_news else "",
            id_news[0].get("source", "") if id_news else ""
        )
    except Exception:
        id_item = {
            "title": id_news[0]["title"] if id_news else "관련 뉴스 없음 (24h)",
            "summary": "",
            "url": id_news[0]["url"] if id_news else "",
            "source": id_news[0].get("source", "") if id_news else ""
        }

    # 경쟁사 뉴스 (2개)
    comp_items = []
    for n in comp_news[:2]:
        try:
            item = analyze_single(n["title"], n["url"], n.get("source", ""))
        except Exception:
            item = {"title": n["title"], "summary": "", "url": n["url"], "source": n.get("source", "")}
        comp_items.append(item)

    while len(comp_items) < 2:
        comp_items.append({"title": "관련 뉴스 없음 (24h)", "summary": "", "url": "", "source": ""})

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
