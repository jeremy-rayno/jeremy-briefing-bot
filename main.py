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
    "global economy automotive",
    "window film PPF paint protection film market"
]

TH_QUERIES = [
    "Thailand window film OR PPF OR car tinting OR automotive aftermarket"
]

ID_QUERIES = [
    "Indonesia window film OR PPF OR car tinting OR automotive aftermarket"
]

COMPETITOR_QUERIES = [
    "XPEL window film OR paint protection film",
    "Llumar window film OR solar control film",
    "3M window film OR paint protection film",
    "Suntek window film OR PPF",
    "SolarGard window film OR solar control"
]

# 경쟁사 뉴스 신뢰 소스 도메인 화이트리스트
TRUSTED_DOMAINS = (
    "reuters.com,bloomberg.com,apnews.com,"
    "businesswire.com,prnewswire.com,globenewswire.com,"
    "automotiveworld.com,just-auto.com,wardsauto.com,"
    "xpel.com,llumar.com,3m.com,solargard.com,suntek.com"
)

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
# NEWS FETCH — NewsAPI
# =========================

def get_news(queries, page_size=5, trusted_only=False):

    news = []

    for query in queries:
        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": query,
                "sortBy": "publishedAt",
                "pageSize": page_size,
                "language": "en",
                "apiKey": NEWS_API_KEY
            }

            if trusted_only:
                params["domains"] = TRUSTED_DOMAINS

            res = requests.get(url, params=params, timeout=10)
            data = res.json()

            print(f"NewsAPI [{query[:40]}] status: {data.get('status')} / total: {data.get('totalResults', 0)}")

            if data.get("status") == "ok":
                for article in data.get("articles", []):
                    title = article.get("title", "")
                    article_url = article.get("url", "")
                    source = article.get("source", {}).get("name", "")

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
                print(f"NewsAPI error [{query[:40]}]: {data.get('code')} / {data.get('message')}")

        except Exception as e:
            print(f"NewsAPI exception ({query[:40]}):", str(e))

    return news


# =========================
# AI 분석 — Global Top3
# =========================

def analyze_global(news_list):

    if not news_list:
        return [{"title": "수집된 뉴스 없음", "summary": "", "url": "", "source": ""}]

    items = "\n".join([
        f"{i+1}. [{n.get('source','')}] {n['title']} | {n['url']}"
        for i, n in enumerate(news_list[:10])
    ])

    prompt = f"""
아래 뉴스 목록에서 글로벌 자동차 산업, 윈도우 필름, PPF(페인트 보호 필름),
자동차 애프터마켓 관점에서 가장 중요한 3개를 골라 분석해줘.
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
# AI 분석 — 태국/인도네시아 관련성 필터 + 번역
# =========================

def analyze_regional(news_list, country):
    """
    윈도우 필름/PPF/자동차 애프터마켓 관련성 높은 뉴스 1개 선택
    관련 뉴스 없으면 None 반환
    """

    if not news_list:
        return None

    items = "\n".join([
        f"{i+1}. [{n.get('source','')}] {n['title']} | {n['url']}"
        for i, n in enumerate(news_list[:10])
    ])

    prompt = f"""
아래는 {country} 관련 뉴스 목록이야.
윈도우 필름, PPF(페인트 보호 필름), 썬팅, 자동차 애프터마켓과 관련성이 높은 뉴스가 있으면
가장 관련성 높은 1개를 골라 분석해줘.

관련성이 있는 뉴스가 전혀 없으면 반드시 이것만 답해줘:
{{"relevant": false}}

관련 뉴스가 있으면 반드시 아래 JSON 형식으로만 답해줘. JSON 외에 다른 말은 절대 쓰지 마.
title은 한국어로 번역해줘.
summary는 한국어로 3~4문장, 150자 이내로 작성해줘.
url은 원본 그대로 복사해줘.

출력 형식 (관련 뉴스 있을 때):
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
# AI 분석 — 경쟁사 뉴스 관련성 필터 + 번역
# =========================

def analyze_competitor(news_list):
    """
    실제 회사 소식(신제품, 공시, 전략 등)만 필터링
    무관한 뉴스(중고차 경매, 차량 리뷰 등) 제외
    관련 없으면 빈 리스트 반환
    """

    if not news_list:
        return []

    items = "\n".join([
        f"{i+1}. [{n.get('source','')}] {n['title']} | {n['url']}"
        for i, n in enumerate(news_list[:15])
    ])

    prompt = f"""
아래는 윈도우 필름/PPF 경쟁사(XPEL, Llumar, 3M, Suntek, SolarGard) 관련 뉴스 목록이야.
이 중에서 반드시 해당 회사의 신제품 출시, 경영 전략, 실적, 파트너십, 공시 등
실제 비즈니스 관련 뉴스만 골라서 중요한 최대 2개를 선택해줘.

중고차 경매, 차량 리뷰, 회사와 무관한 뉴스는 절대 선택하지 마.

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
# INSIGHT — 태국/인도네시아/경쟁사 뉴스 기반
# =========================

def generate_insight(th_item, id_item, comp_items):
    """
    태국/인도네시아/경쟁사 뉴스만을 기반으로 인사이트 생성
    """

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

    blocks = []
    for item in comp_items[:2]:
        blocks.append(format_single_block(item))

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

    # 뉴스 수집
    global_news = get_news(GLOBAL_QUERIES, page_size=5)
    th_news = get_news(TH_QUERIES, page_size=10)
    id_news = get_news(ID_QUERIES, page_size=10)
    comp_news = get_news(COMPETITOR_QUERIES, page_size=5, trusted_only=True)

    # Global Top3 AI 분석
    try:
        global_items = analyze_global(global_news)
    except Exception as e:
        print("OpenAI error (global):", str(e))
        global_items = [{"title": "AI 분석 실패", "summary": str(e)[:100], "url": "", "source": ""}]

    # 태국 뉴스 — 관련성 필터
    try:
        th_item = analyze_regional(th_news, "태국")
    except Exception as e:
        print("OpenAI error (thailand):", str(e))
        th_item = None

    # 인도네시아 뉴스 — 관련성 필터
    try:
        id_item = analyze_regional(id_news, "인도네시아")
    except Exception as e:
        print("OpenAI error (indonesia):", str(e))
        id_item = None

    # 경쟁사 뉴스 — 관련성 필터
    try:
        comp_items = analyze_competitor(comp_news)
    except Exception as e:
        print("OpenAI error (competitor):", str(e))
        comp_items = []

    # Insight — 태국/인도네시아/경쟁사 뉴스 기반
    try:
        insight = generate_insight(th_item, id_item, comp_items)
    except Exception as e:
        print("OpenAI error (insight):", str(e))
        insight = "인사이트 생성 실패"

    # Global Top3 포맷
    global_blocks = "\n\n─────────────────\n\n".join([
        format_news_block(item, i) for i, item in enumerate(global_items[:3])
    ])

    # 날짜
    now_kst = datetime.now(timezone.utc) + timedelta(hours=9)
    date_str = now_kst.strftime("%Y.%m.%d %H:%M")

    # 최종 메시지
    msg = f"""<b>📋 Daily Briefing</b>  <i>{date_str} KST</i>

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

{format_competitor_blocks(comp_items)}

━━━━━━━━━━━━━━━━━━━━
<b>💡 Insight & Action</b>

{insight}"""

    send_telegram(msg)

    return "Daily briefing sent"
