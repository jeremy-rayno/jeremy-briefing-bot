import requests
from bs4 import BeautifulSoup
import feedparser
import os

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

headers = {"User-Agent":"Mozilla/5.0"}

def get_market():

    r = requests.get("https://finance.naver.com/marketindex/", headers=headers)
    soup = BeautifulSoup(r.text,"html.parser")
    usdkrw = soup.select_one("span.value").text

    r = requests.get("https://finance.naver.com/sise/", headers=headers)
    soup = BeautifulSoup(r.text,"html.parser")
    kospi = soup.select_one("#KOSPI_now").text

    r = requests.get("https://finance.naver.com/item/main.naver?code=005930", headers=headers)
    soup = BeautifulSoup(r.text,"html.parser")
    samsung = soup.select_one("p.no_today span.blind").text

    return usdkrw, kospi, samsung


def get_news(query):

    url = f"https://news.google.com/rss/search?q={query}"
    feed = feedparser.parse(url)

    result = []

    for e in feed.entries[:3]:
        result.append(f"{e.title}\n{e.link}")

    return "\n\n".join(result)


def send_telegram(msg):

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": msg
    }

    requests.post(url, json=payload)


def jeremy_briefing(request):

    usdkrw, kospi, samsung = get_market()

    thai = get_news("Thailand automotive")
    indo = get_news("Indonesia automotive")

    message = f"""
제레미 브리핑

USD/KRW {usdkrw}
KOSPI {kospi}
Samsung {samsung}

Thailand Automotive
{thai}

Indonesia Automotive
{indo}
"""

    send_telegram(message)

    return "OK"
