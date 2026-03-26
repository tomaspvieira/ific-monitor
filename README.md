# IFIC / IA nas PME — Results Monitor

Monitors two Portuguese government portals daily and sends an email alert
when the list of approved beneficiaries under grant notice
**03/C05-i14-01/2025** ("Linha IA nas PME") is published.

## Portals monitored

| # | Portal | URL |
|---|--------|-----|
| 1 | Recuperar Portugal — IA nas PME page | https://recuperarportugal.gov.pt/candidatura/03-linha-ia-nas-pme-aviso-n-o-03-c05-i14-01-2025/ |
| 2 | Transparência.gov.pt — PRR Beneficiários | https://transparencia.gov.pt/pt/fundos-europeus/prr/pesquisar/beneficiario/ |

Runs automatically every day at **09:00 Lisbon time** via GitHub Actions.

---

## Setup (one-time, ~5 minutes)

### 1. Create a GitHub repository

- Go to https://github.com/new
- Name it `ific-monitor` (or anything you like)
- Set it to **Private**
- Click **Create repository**

### 2. Upload these files

Upload all files from this folder to the repository root, preserving the
folder structure (`.github/workflows/monitor.yml`, `monitor.py`, etc.).

The easiest way is to drag-and-drop all files into the GitHub web interface,
or use Git:

```bash
cd ific-monitor
git init
git remote add origin https://github.com/YOUR_USERNAME/ific-monitor.git
git add .
git commit -m "Initial commit"
git push -u origin main
```

### 3. Add email secrets

The monitor uses Gmail (or any SMTP provider) to send alerts.

**If using Gmail:**
1. Enable 2-factor authentication on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Create an App Password named "IFIC Monitor"
4. Copy the 16-character password shown

**In your GitHub repository:**
1. Go to **Settings → Secrets and variables → Actions**
2. Add these three secrets:

| Secret name | Value |
|-------------|-------|
| `SMTP_USER` | your Gmail address (e.g. `you@gmail.com`) |
| `SMTP_PASS` | the App Password from step above |
| `NOTIFY_EMAIL` | email address to send alerts to (can be the same) |

### 4. Test it manually

- Go to the **Actions** tab in your repository
- Click **IFIC IA nas PME — Daily Monitor**
- Click **Run workflow → Run workflow**
- Watch the logs — you should see both URLs checked and (if credentials
  are correct) a daily summary email

---

## How it works

- **Every day at 09:00 Lisbon time**, GitHub runs `monitor.py`
- The script fetches both portal pages and compares them against the
  previous day's content (stored in `data/state.json`)
- It looks for keywords that would appear if results are published
  (e.g. "aprovados", "lista de beneficiários", "decisão final")
- If results are detected: sends a **🚨 alert email** immediately
- Either way, the updated state is committed back to the repo
- You can also check the **Actions** tab any time to see the run history

---

## What triggers an alert

The script flags a result as likely published when:
- The page content has changed since yesterday, **AND**
- At least 2 positive keywords are found (e.g. "aprovados", "lista de
  beneficiários"), **AND**
- No "negative" keywords are present (e.g. "fechado", "suspensa")

This avoids false positives from minor page updates.

---

## Files

```
ific-monitor/
├── .github/
│   └── workflows/
│       └── monitor.yml     # GitHub Actions schedule
├── data/
│   └── state.json          # Persisted page hashes (auto-updated)
├── monitor.py              # Main monitoring script
├── .gitignore
└── README.md
```
