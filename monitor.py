import feedparser
import requests
import json
import os

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

RSS_FEEDS = [
    {
        'source': 'CityNow',
        'url': 'https://www.citynow.it/tag/reggina/feed/',
        'filter': False
    },
    {
        'source': 'TuttoReggina',
        'url': 'https://www.tuttoreggina.com/reggina/feed/',
        'filter': False
    },
    {
        'source': 'Il Dispaccio',
        'url': 'https://ildispaccio.it/feed/',
        'filter': True
    },
]

KEYWORDS = [
    'reggina', 'amaranto', 'granillo', "sant'agata",
    'sant agata', 'rhegium', 'regium', 'lotito reggina',
    'marchionni', 'romairone', 'coinu', 'calveri'
]

SEEN_FILE = 'seen_articles.json'

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, 'w') as f:
        json.dump(list(seen), f, indent=2)

def is_relevant(entry):
    text = (
        entry.get('title', '') + ' ' +
        entry.get('summary', '') + ' ' +
        entry.get('link', '')
    ).lower()
    return any(kw in text for kw in KEYWORDS)

def send_telegram(message):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    try:
        requests.post(url, data={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': False
        })
    except Exception as e:
        print(f"Errore Telegram: {e}")

def check_feeds():
    seen = load_seen()
    new_seen = set(seen)
    is_first_run = len(seen) == 0

    if is_first_run:
        print("Primo avvio: salvo gli articoli esistenti senza inviarli.")

    for feed_config in RSS_FEEDS:
        source = feed_config['source']
        url = feed_config['url']
        do_filter = feed_config['filter']

        try:
            feed = feedparser.parse(url)
            print(f"{source}: trovati {len(feed.entries)} articoli nel feed")

            for entry in feed.entries[:15]:
                article_id = entry.get('id') or entry.get('link')
                if not article_id:
                    continue

                if article_id in seen:
                    continue

                if do_filter and not is_relevant(entry):
                    new_seen.add(article_id)
                    continue

                new_seen.add(article_id)

                if not is_first_run:
                    title = entry.get('title', 'Nessun titolo')
                    link = entry.get('link', '')
                    message = f"📰 <b>{source}</b>\n\n{title}\n\n{link}"
                    send_telegram(message)
                    print(f"Inviato: {title}")

        except Exception as e:
            print(f"Errore con {source}: {e}")

    save_seen(new_seen)
    print(f"Articoli totali tracciati: {len(new_seen)}")

if __name__ == '__main__':
    check_feeds()
