import calendar
import feedparser
import html
import re
import requests
from bs4 import BeautifulSoup
import json
import os
import time

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# Avvio automatico del post WhatsApp con le formazioni ufficiali.
# Il token (segreto RN_DISPATCH_TOKEN) deve avere il permesso "Actions: write" sul repository del post.
RN_DISPATCH_TOKEN = os.environ.get('RN_DISPATCH_TOKEN')
WHATSAPP_REPO = 'regginanetwork/rn-whatsapp'
WHATSAPP_WORKFLOW_FORMAZIONI = 'pubblica-formazioni.yml'
WHATSAPP_WORKFLOW_CONVOCATI = 'salva-convocati.yml'
WHATSAPP_REF = 'main'
FORMAZIONI_SOURCE = 'Reggina Ufficiale'
FORMAZIONI_TITLE_RE = re.compile(r',\s*le formazioni ufficiali', re.IGNORECASE)
# "Nissa-Reggina, i convocati di mister Marchionni"
CONVOCATI_TITLE_RE = re.compile(r'^[^,]+-[^,]+,\s*i convocati', re.IGNORECASE)
# Il post parte solo se l'articolo è stato pubblicato da poco (le formazioni escono circa 1 ora prima del fischio)
FORMAZIONI_MAX_AGE_MINUTES = 180
# I convocati escono il giorno prima: li salvo se l'articolo ha meno di 24 ore
CONVOCATI_MAX_AGE_MINUTES = 24 * 60

RSS_FEEDS = [
    {
        'source': 'CityNow',
        'url': 'https://www.citynow.it/tag/reggina/feed/',
        'filter': False
    },
    {
        'source': 'TuttoReggina',
        'url': 'https://www.tuttoreggina.com/rss',
        'filter': False
    },
    {
        'source': 'Il Dispaccio',
        'url': 'https://ildispaccio.it/tag/reggina/feed/',
        'filter': False
    },
    {
        'source': 'Pedullà',
        'url': 'https://www.alfredopedulla.com/squadre/reggina/feed/',
        'filter': False
    },
    {
        'source': 'Il Reggino',
        'url': 'https://www.ilreggino.it/tag/reggina/feed/',
        'filter': False
    },
    {
        'source': 'Il Tifoso Reggino',
        'url': 'https://iltifosoreggino.it/category/calcio/reggina/feed/',
        'filter': False
    },
    {
        'source': 'SerieD24',
        'url': 'https://www.seried24.com/rss',
        'filter': True
    },
    {
        'source': 'Reggina Ufficiale',
        'url': 'https://www.reggina1914.it/feed/',
        'filter': False
    },
    # Nuova fonte: news redazionali LND Serie D
    {
        'source': 'LND Serie D',
        'url': 'https://lnd.it/news/seried/feed/',
        'filter': False
    },
]

KEYWORDS = ['reggina']

SEEN_FILE = 'seen_articles.json'
LND_COMUNICATI_URL = 'https://lnd.it/seried/comunicati/'


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


def is_lineup_article(source, entry):
    """True solo per l'articolo "<partita>, le formazioni ufficiali" del sito ufficiale della Reggina."""
    if source != FORMAZIONI_SOURCE:
        return False
    if 'reggina1914.it' not in entry.get('link', ''):
        return False
    return bool(FORMAZIONI_TITLE_RE.search(entry.get('title', '')))


def is_convocati_article(source, entry):
    """True solo per l'articolo "<partita>, i convocati ..." del sito ufficiale della Reggina."""
    if source != FORMAZIONI_SOURCE:
        return False
    if 'reggina1914.it' not in entry.get('link', ''):
        return False
    return bool(CONVOCATI_TITLE_RE.search(entry.get('title', '')))


def is_recent(entry, max_minutes):
    """True se l'articolo è stato pubblicato negli ultimi max_minutes minuti (data del feed, in UTC)."""
    published = entry.get('published_parsed') or entry.get('updated_parsed')
    if not published:
        return False
    age_seconds = time.time() - calendar.timegm(published)
    # piccola tolleranza (5 minuti) per differenze di orologio
    return -300 <= age_seconds <= max_minutes * 60


def trigger_workflow(workflow, input_name, link, title, label):
    """Avvia su GitHub un workflow del repository del post WhatsApp, passandogli l'indirizzo dell'articolo.
    In caso di problemi avvisa su Telegram."""
    safe_title = html.escape(title)
    if not RN_DISPATCH_TOKEN:
        print("RN_DISPATCH_TOKEN non impostato: " + label + " non avviato.")
        send_telegram(
            f"⚠️ <b>{label} non avviato</b>\n\n{safe_title}\n\n"
            "Manca il token per avviare il workflow su GitHub."
        )
        return False

    url = (
        f'https://api.github.com/repos/{WHATSAPP_REPO}'
        f'/actions/workflows/{workflow}/dispatches'
    )
    try:
        response = requests.post(
            url,
            headers={
                'Accept': 'application/vnd.github+json',
                'Authorization': f'Bearer {RN_DISPATCH_TOKEN}',
                'X-GitHub-Api-Version': '2022-11-28',
            },
            json={'ref': WHATSAPP_REF, 'inputs': {input_name: link}},
            timeout=20,
        )
        if 200 <= response.status_code < 300:
            print(f"{label} avviato per: {title}")
            return True
        print(f"Avvio di '{label}' fallito (HTTP {response.status_code}).")
        send_telegram(
            f"⚠️ <b>{label} non avviato</b>\n\n{safe_title}\n\n"
            f"GitHub ha risposto con errore {response.status_code}."
        )
    except Exception as e:
        print(f"Errore avvio '{label}': {e}")
        send_telegram(
            f"⚠️ <b>{label} non avviato</b>\n\n{safe_title}\n\n"
            "Errore di connessione a GitHub."
        )
    return False


def check_feeds(seen, is_first_run):
    new_seen = set()

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

                new_seen.add(article_id)

                if is_first_run:
                    continue

                if do_filter and not is_relevant(entry):
                    continue

                title = entry.get('title', 'Nessun titolo')
                link = entry.get('link', '')
                message = f"📰 <b>{source}</b>\n\n{title}\n\n{link}"
                send_telegram(message)
                print(f"Inviato: {title}")

                # Formazioni ufficiali: avvia il post sul canale WhatsApp
                if is_lineup_article(source, entry):
                    if is_recent(entry, FORMAZIONI_MAX_AGE_MINUTES):
                        trigger_workflow(
                            WHATSAPP_WORKFLOW_FORMAZIONI, 'url_formazioni', link, title, 'Post WhatsApp'
                        )
                    else:
                        print(f"Formazioni non recenti, post WhatsApp non avviato: {title}")
                # Convocati: avvia il salvataggio dell'elenco, che servirà al post delle formazioni
                elif is_convocati_article(source, entry):
                    if is_recent(entry, CONVOCATI_MAX_AGE_MINUTES):
                        trigger_workflow(
                            WHATSAPP_WORKFLOW_CONVOCATI, 'url_convocati', link, title, 'Salvataggio dei convocati'
                        )
                    else:
                        print(f"Convocati non recenti, salvataggio non avviato: {title}")

        except Exception as e:
            print(f"Errore con {source}: {e}")

    return new_seen


def check_lnd_comunicati(seen, is_first_run):
    """
    Monitora i comunicati ufficiali LND Serie D.
    Non hanno feed RSS: la pagina viene scaricata e analizzata per estrarre
    titolo, numero C.U. e link al PDF di ogni comunicato.
    L'ID usato per il tracciamento è il link diretto al PDF.
    """
    new_seen = set()

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; RegginaNewsMonitor/1.0)'}
        response = requests.get(LND_COMUNICATI_URL, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # I comunicati sono link diretti a PDF su comunicati.lnd.it
        comunicati = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if 'comunicati.lnd.it' in href and href.endswith('.pdf'):
                # Il testo del titolo è nel nodo adiacente, cerchiamo il
                # contenitore più vicino che includa sia il link che il titolo
                container = a.find_parent()
                title_text = ''
                if container:
                    # Cerca testo nel contenitore escludendo il testo del link
                    siblings = list(container.strings)
                    title_text = ' '.join(s.strip() for s in siblings if s.strip())
                    # Rimuove "Scarica" che è il testo del link stesso
                    title_text = title_text.replace('Scarica', '').strip()

                comunicati.append({
                    'id': href,
                    'title': title_text if title_text else 'Comunicato ufficiale LND',
                    'link': href
                })

        print(f"LND Comunicati: trovati {len(comunicati)} comunicati")

        for comunicato in comunicati:
            doc_id = comunicato['id']
            if doc_id in seen:
                continue

            new_seen.add(doc_id)

            if is_first_run:
                continue

            # Prova a estrarre il numero C.U. dal nome del file o dal titolo
            title = comunicato['title']
            link = comunicato['link']
            message = f"📋 <b>LND Comunicati Ufficiali</b>\n\n{title}\n\n{link}"
            send_telegram(message)
            print(f"Inviato comunicato: {title}")

    except Exception as e:
        print(f"Errore LND Comunicati: {e}")

    return new_seen


def check_all():
    seen = load_seen()
    is_first_run = len(seen) == 0

    if is_first_run:
        print("Primo avvio: salvo gli articoli esistenti senza inviarli.")

    new_seen = set(seen)

    new_seen |= check_feeds(seen, is_first_run)
    new_seen |= check_lnd_comunicati(seen, is_first_run)

    save_seen(new_seen)
    print(f"Articoli/comunicati totali tracciati: {len(new_seen)}")


if __name__ == '__main__':
    check_all()
