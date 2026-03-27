"""
IFIC / IA nas PME - Beneficiary Results Monitor
Checks two Portuguese government portals daily for publication of approved
beneficiaries under grant notice 03/C05-i14-01/2025.
Auto-disables itself via GitHub API after sending a successful alert.
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

# --- Configuration ---

TARGETS = [
    {
        "name": "Recuperar Portugal - IA nas PME candidatura page",
        "url": "https://recuperarportugal.gov.pt/candidatura/03-linha-ia-nas-pme-aviso-n-o-03-c05-i14-01-2025/",
        "positive_keywords": [
            "resultados", "aprovados", "lista de beneficiarios",
            "decisao final", "selecionados", "homologacao",
            "aprovacao", "financiamento aprovado",
        ],
        "negative_keywords": ["fechado", "suspensao", "suspensa"],
    },
    {
        "name": "Transparencia.gov.pt - PRR Beneficiarios (BPF / C05-i14)",
        "url": "https://transparencia.gov.pt/pt/fundos-europeus/prr/pesquisar/beneficiario/?investments=C05-i14",
        "positive_keywords": [
            "C05-i14", "IA nas PME", "inovacao empresarial",
            "beneficiario final", "aprovado",
        ],
        "negative_keywords": [],
    },
]

STATE_FILE = Path("data/state.json")

# --- GitHub self-disable ---

def disable_workflow():
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF", "")

    if not token or not repo:
        print("WARNING: Cannot self-disable - GITHUB_TOKEN or GITHUB_REPOSITORY not set.")
        return

    workflow_file = "monitor.yml"
    if workflow_ref:
        part = workflow_ref.split("/")[-1]
        workflow_file = part.split("@")[0]

    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/disable"
    req = urllib.request.Request(
        url,
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"Workflow disabled via GitHub API (status {resp.status}). Will not run again.")
    except urllib.error.HTTPError as e:
        print(f"Failed to disable workflow: HTTP {e.code} - {e.reason}")
        print("The alert email was still sent. Please disable the workflow manually.")

# --- Helpers ---

def fetch_page(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; IFIC-Monitor/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        print(f"Fetch error for {url}: {e}")
        return ""

def content_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

def check_keywords(text, keywords):
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]

def analyse_target(target, state):
    name = target["name"]
    url = target["url"]
    print(f"\nChecking: {name}")
    print(f"   URL: {url}")

    html = fetch_page(url)
    if not html:
        return {"name": name, "url": url, "status": "fetch_error", "alert": False}

    current_hash = content_hash(html)
    prev = state.get(url, {})
    prev_hash = prev.get("hash", "")

    positive_found = check_keywords(html, target["positive_keywords"])
    negative_found = check_keywords(html, target["negative_keywords"])

    results_likely = len(positive_found) >= 2 and len(negative_found) == 0
    changed = current_hash != prev_hash and bool(prev_hash)
    new_entry = not bool(prev_hash)

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

    state[url] = {
        "hash": current_hash,
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "last_status": status,
        "positive_keywords_found": positive_found,
        "negative_keywords_found": negative_found,
    }

    return {
        "name": name, "url": url, "status": status,
        "alert": alert, "changed": changed,
        "positive_found": positive_found, "negative_found": negative_found,
    }

# --- Email ---


def send_email(results):
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    notify_to = os.environ.get("NOTIFY_EMAIL", smtp_user)

    if not smtp_user or not smtp_pass:
        print("\nNo SMTP credentials - skipping email.")
        return

    alerts = [r for r in results if r.get("alert")]
    if not alerts:
        print("\nNo alerts triggered - no email sent.")
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = "IFIC IA nas PME - Resultados possivelmente publicados!"

    lines = [
        "<h2>IFIC / IA nas PME - Monitor de Resultados</h2>",
        f"<p><strong>Verificacao:</strong> {now}</p>",
        "<p><strong>O monitor detectou sinais de que os resultados foram publicados. "
        "Verifique os links abaixo imediatamente.</strong></p>",
        "<hr>",
    ]
    for r in results:
        icon = "ALERTA" if r.get("alert") else "OK"
        lines.append(f"<h3>[{icon}] {r['name']}</h3>")
        lines.append(f"<p><strong>Status:</strong> {r['status']}</p>")
        lines.append(f"<p><strong>URL:</strong> <a href=\"{r['url']}\">{r['url']}</a></p>")
        if r.get("positive_found"):
            lines.append(f"<p><strong>Palavras-chave encontradas:</strong> {', '.join(r['positive_found'])}</p>")
        lines.append("<hr>")

    lines += [
        "<h3>O que fazer agora</h3>",
        "<ol>",
        "<li><strong>Abra os links acima</strong> e confirme que a lista de beneficiários está publicada.</li>",
        "<li><strong>Descarregue a lista completa</strong> em formato CSV aqui:<br>",
        "<a href=\"https://transparencia.gov.pt/pt/fundos-europeus/prr/pesquisar/beneficiario/?investments=C05-i14\">",
        "transparencia.gov.pt → Beneficiários PRR → filtrar C05-i14</a><br>",
        "Clique no botão <em>\"Descarregar dados abertos\"</em> no fundo da página.</li>",
        "<li><strong>Filtre por componente C05-i14</strong> para ver apenas as empresas do IA nas PME.</li>",
        "<li>O CSV terá: nome da empresa, NIF, montante aprovado, região — a sua lista de prospects.</li>",
        "</ol>",
        "<hr>",
        "<p><em>Este monitor desactivou-se automaticamente. "
        "Nao recebera mais emails desta ferramenta.</em></p>",
    ]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = notify_to
    msg.attach(MIMEText("\n".join(lines), "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, notify_to, msg.as_string())
        print(f"\nAlert email sent to {notify_to}")
    except Exception as e:
        print(f"\nEmail failed: {e}")

# --- Main ---

def main():
    print("=" * 60)
    print("IFIC / IA nas PME - Results Monitor")
    print(f"Run time: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    test_mode = os.environ.get("TEST_MODE", "").lower() == "true"

    if test_mode:
        print("\nTEST MODE - forcing alert to verify email delivery")
        results = [
            {
                "name": "TEST - Recuperar Portugal",
                "url": "https://recuperarportugal.gov.pt/candidatura/03-linha-ia-nas-pme-aviso-n-o-03-c05-i14-01-2025/",
                "status": "RESULTS_LIKELY_PUBLISHED (TEST)",
                "alert": True,
                "changed": True,
                "positive_found": ["resultados", "aprovados"],
                "negative_found": [],
            }
        ]
        send_email(results)
        print("\nTest complete. Check your inbox.")
        return

    state = load_state()
    results = [analyse_target(t, state) for t in TARGETS]
    save_state(state)

    any_alert = any(r.get("alert") for r in results)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        icon = "ALERT" if r.get("alert") else ("CHANGED" if r.get("changed") else "OK")
        print(f"  [{icon}]  {r['name']}")
        print(f"           {r['status']}")

    if any_alert:
        print("\nALERT: Results may be published!")
        send_email(results)
        print("\nDisabling workflow so it does not run again...")
        disable_workflow()
    else:
        print("\nNo results published yet. Will check again tomorrow.")

if __name__ == "__main__":
    main()
