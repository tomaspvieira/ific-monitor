"""
IFIC / IA nas PME — Beneficiary Results Monitor
Checks two Portuguese government portals daily for publication of approved
beneficiaries under grant notice 03/C05-i14-01/2025.
"""

import os
import json
import hashlib
import smtplib
import urllib.request
import urllib.error
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

# ─── Configuration ────────────────────────────────────────────────────────────

TARGETS = [
    {
        "name": "Recuperar Portugal — IA nas PME candidatura page",
        "url": "https://recuperarportugal.gov.pt/candidatura/03-linha-ia-nas-pme-aviso-n-o-03-c05-i14-01-2025/",
        # Positive signals: words that would appear when results are published
        "positive_keywords": [
            "resultados", "aprovados", "lista de beneficiários",
            "decisão final", "selecionados", "homologação",
            "aprovação", "financiamento aprovado",
        ],
        # Negative signals: words currently on page confirming no results yet
        "negative_keywords": ["fechado", "suspensão", "suspensa"],
    },
    {
        "name": "Transparência.gov.pt — PRR Beneficiários (BPF / C05-i14)",
        "url": "https://transparencia.gov.pt/pt/fundos-europeus/prr/pesquisar/beneficiario/?investments=C05-i14",
        "positive_keywords": [
            "C05-i14", "IA nas PME", "inovação empresarial",
            "beneficiário final", "aprovado",
        ],
        "negative_keywords": [],
    },
]

STATE_FILE = Path("data/state.json")
RESULTS_THRESHOLD = 50  # min chars of new content to be considered meaningful


# ─── Helpers ──────────────────────────────────────────────────────────────────

def fetch_page(url: str) -> str:
    """Fetch page text, return empty string on error."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; IFIC-Monitor/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        print(f"  ⚠️  Fetch error for {url}: {e}")
        return ""


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def check_keywords(text: str, keywords: list[str]) -> list[str]:
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


def analyse_target(target: dict, state: dict) -> dict:
    """
    Fetch a target URL and compare against previous state.
    Returns a result dict with change analysis.
    """
    name = target["name"]
    url = target["url"]
    print(f"\n🔍 Checking: {name}")
    print(f"   URL: {url}")

    html = fetch_page(url)
    if not html:
        return {"name": name, "url": url, "status": "fetch_error", "alert": False}

    current_hash = content_hash(html)
    prev = state.get(url, {})
    prev_hash = prev.get("hash", "")

    # Keyword analysis
    positive_found = check_keywords(html, target["positive_keywords"])
    negative_found = check_keywords(html, target["negative_keywords"])

    # Determine if this looks like results have been published
    results_likely = len(positive_found) >= 2 and len(negative_found) == 0

    # Detect content change
    changed = current_hash != prev_hash and bool(prev_hash)
    new_entry = not bool(prev_hash)

    # Build status
    if new_entry:
        status = "first_run"
        alert = False
    elif results_likely and changed:
        status = "RESULTS_LIKELY_PUBLISHED"
        alert = True
    elif results_likely and not changed:
        status = "results_signals_stable"
        alert = False
    elif changed:
        status = "content_changed_no_results_yet"
        alert = False
    else:
        status = "no_change"
        alert = False

    print(f"   Status     : {status}")
    print(f"   Hash change: {changed}")
    print(f"   +Keywords  : {positive_found or 'none'}")
    print(f"   -Keywords  : {negative_found or 'none'}")

    # Update state
    state[url] = {
        "hash": current_hash,
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "last_status": status,
        "positive_keywords_found": positive_found,
        "negative_keywords_found": negative_found,
    }

    return {
        "name": name,
        "url": url,
        "status": status,
        "alert": alert,
        "changed": changed,
        "positive_found": positive_found,
        "negative_found": negative_found,
    }


# ─── Email ────────────────────────────────────────────────────────────────────

def send_email(results: list[dict], always_send: bool = False):
    """Send notification email. Requires env vars to be set."""
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    notify_to = os.environ.get("NOTIFY_EMAIL", smtp_user)

    if not smtp_user or not smtp_pass:
        print("\n⚠️  No SMTP credentials set — skipping email.")
        return

    alerts = [r for r in results if r.get("alert")]
    changes = [r for r in results if r.get("changed") and not r.get("alert")]

    if not alerts and not always_send:
        print("\n📭 No alerts triggered — no email sent.")
        return

    # Build email body
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = (
        "🚨 IFIC IA nas PME — Resultados possivelmente publicados!"
        if alerts
        else f"ℹ️ IFIC Monitor — Daily check {now}"
    )

    lines = [
        "<h2>IFIC / IA nas PME — Monitor de Resultados</h2>",
        f"<p><strong>Verificação:</strong> {now}</p>",
        "<hr>",
    ]

    for r in results:
        icon = "🚨" if r.get("alert") else ("🔄" if r.get("changed") else "✅")
        lines.append(f"<h3>{icon} {r['name']}</h3>")
        lines.append(f"<p><strong>Status:</strong> {r['status']}</p>")
        lines.append(f"<p><strong>URL:</strong> <a href=\"{r['url']}\">{r['url']}</a></p>")
        if r.get("positive_found"):
            lines.append(f"<p><strong>Palavras-chave encontradas:</strong> {', '.join(r['positive_found'])}</p>")
        lines.append("<hr>")

    if alerts:
        lines.append(
            "<p><strong>Recomendação:</strong> Abra os links acima — "
            "os resultados dos beneficiários aprovados podem estar disponíveis!</p>"
        )

    html_body = "\n".join(lines)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = notify_to
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, notify_to, msg.as_string())
        print(f"\n📧 Email sent to {notify_to}")
    except Exception as e:
        print(f"\n❌ Email failed: {e}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("IFIC / IA nas PME — Results Monitor")
    print(f"Run time: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    state = load_state()
    results = [analyse_target(t, state) for t in TARGETS]
    save_state(state)

    any_alert = any(r.get("alert") for r in results)
    any_change = any(r.get("changed") for r in results)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        icon = "🚨" if r["alert"] else ("🔄" if r.get("changed") else "✅")
        print(f"  {icon}  {r['name']}")
        print(f"       {r['status']}")

    send_email(results, always_send=False)

    if any_alert:
        print("\n🚨 ALERT: Results may be published! Check the URLs above.")
        exit(1)  # Non-zero exit so GitHub Actions marks the run visibly
    else:
        print("\n✅ No results published yet. Will check again tomorrow.")


if __name__ == "__main__":
    main()
