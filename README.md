# MB Miner Bot — Auto Claim Music Mining (Telegram)

Bot Telegram untuk auto-claim mining di game Telegram **@MusicMiningMB_Bot** (web app `musicmb.site`, API `api.musicmb.site`).
Bot ini meng-*claim* mining secara otomatis untuk **banyak akun** sekaligus.

> ⚠️ **Keamanan:** Jangan pernah commit/share `accounts.json`, `proxies.txt`, atau file `*.session`.
> Semua data sensitif ada di file lokal atau lewat **environment variable** (GitHub Secrets).
> Repo ini sudah dikosongkan isinya (accounts.json = `[]`, proxies.txt = kosong).

---

## Daftar Isi

- [1. Fitur](#1-fitur)
- [2. Kebutuhan (Prerequisites)](#2-kebutuhan-prerequisites)
- [3. Struktur File](#3-struktur-file)
- [4. Cara Jalankan di VPS (Ubuntu/Debian)](#4-cara-jalankan-di-vps-ubuntudebian)
- [4-B. Cara Jalankan di Termux (Android/HP)](#4-b-cara-jalankan-di-termux-androidhp)
- [5. Cara Jalankan di GitHub Actions (Cloud / Otomatis 24 jam)](#5-cara-jalankan-di-github-actions-cloud--otomatis-24-jam)

---

## 1. Fitur

- **Multi-account**: jalankan banyak akun Telegram sekaligus (paralel / concurrently).
- **Auto-claim mining**: auth → start mining → claim, berulang otomatis.
- **Captcha Turnstile**: otomatis solve Cloudflare Turnstile via layanan 2captcha.
- **Proxy support**: tiap akun dapat 2 proxy (utama + cadangan), rotasi otomatis saat gagal.
- **Anti-rate-limit**: claim lock serialisasi, staggered start, jitter, backoff 429.
- Bisa jalan di **VPS**, **Termux (HP)**, atau **GitHub Actions (cloud 24 jam)**.

### Alur kerja per akun
```
generate initData (Telegram) -> solve Turnstile (2captcha) -> auth ke API -> start mining -> claim
```
- Re-auth otomatis tiap 7 jam.
- Claim otomatis tiap 30 menit (konfigurasikan `CLAIM_INTERVAL` di atas file).

---

## 2. Kebutuhan (Prerequisites)

- **Telegram API ID & API Hash** — buat di https://my.telegram.org → *API development tools*.
- **Nomor telepon** akun-akun Telegram yang mau dipakai (untuk login/OTP).
- **2Captcha API Key** (`CAPTCHA_KEY`) — dari https://2captcha.com (untuk solve Turnstile).
- **Python 3.8+** (recommended 3.10).
- Library: `telethon`, `aiohttp` (lihat `requirements.txt`).
- (Opsional) Daftar **proxy** `user:pass@host:port`.

---

## 3. Struktur File

```
mb-bot/
├── runner.py       # Bot utama: auto-claim mining multi-account
├── session.py      # Generator session (auto-save ke accounts.json)
├── requirements.txt
├── accounts.json   # Data akun (JANGAN di-share) — dikosongkan di repo
└── proxies.txt     # Daftar proxy (JANGAN di-share) — dikosongkan di repo
```

---

## 4. Cara Jalankan di VPS (Ubuntu/Debian)

> VPS = server Linux yang jalan 24 jam. Pakai `tmux`/`screen` supaya bot tetap jalan walau SSH logout.
> Kalau kamu di HP Android, gunakan [bagian 4-B (Termux)](#4-b-cara-jalankan-di-termux-androidhp).

### 4a. Setup env (VPS)

```bash
cd mb-bot

# Update & install Python + venv + build tools
sudo apt update
sudo apt install -y python3 python3-venv python3-pip build-essential

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4b. Buat session & isi accounts.json (VPS)

Jalankan generator session (sekali) — session otomatis tersimpan ke `accounts.json`:

```bash
cd mb-bot
source .venv/bin/activate
python session.py
```

Isi setiap prompt: **Nama akun → Nomor telepon → OTP → (2FA bila aktif)**. Ketik `q` di prompt nama untuk selesai.

> `API_ID`/`API_HASH` dibaca dari env `TG_API_ID`/`TG_API_HASH` atau file `TG_API_ID.txt`/`TG_API_HASH.txt` kalau ada; kalau tidak, diminta manual.

Hasil `accounts.json` (contoh):
```json
[
  { "name": "AL (main)", "session": "1AZWarzs..." }
]
```

Isi `proxies.txt` kalau pakai proxy (satu baris per proxy, `user:pass@host:port`, awalan `http://` otomatis).

### 4c. Set credential env (VPS)

Bot butuh `TG_API_ID`, `TG_API_HASH`, dan `CAPTCHA_KEY`. Set sebelum jalan:

```bash
export TG_API_ID=1234567
export TG_API_HASH="xxxx"
export CAPTCHA_KEY="xxxx"
```

### 4d. Jalankan bot di VPS (biar tetap jalan walau SSH logout)

Gunakan `tmux`:

```bash
tmux new -s mb

# di dalam tmux:
source .venv/bin/activate
python runner.py

# Detach (bot tetap jalan):   Ctrl+B lalu D
# Lihat log lagi:             tmux attach -t mb
# Stop bot:                   Ctrl+C
# Cek session:                tmux ls
# Kill session:               tmux kill-session -t mb
```

---

## 4-B. Cara Jalankan di Termux (Android/HP)

Termux di HP Android — perangkat harus tetap menyala (screen timeout panjang / "never") saat bot jalan.

### 4a. Install Termux + tools

```bash
pkg update && pkg upgrade -y
pkg install -y python python-pip openssl git binutils build-essential
```

### 4b. Clone & setup

```bash
git clone <URL-REPO-MB> mb-bot
cd mb-bot

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Di Termux, executable-nya `python` (bukan `python3`).

### 4c. Buat session & set env

```bash
source .venv/bin/activate
python session.py        # isi akun, auto-save ke accounts.json
```

Set credential:
```bash
export TG_API_ID=1234567
export TG_API_HASH="xxxx"
export CAPTCHA_KEY="xxxx"
```

### 4d. Jalankan bot di Termux

```bash
source .venv/bin/activate
python runner.py
```

> **PENTING Termux:** agar tidak dimatikan Android (doze):
> 1. `termux-wake-lock` agar CPU tetap jalan.
> 2. Layar jangan dimatikan penuh (screen timeout lama/"never").
> 3. Jangan swipe-close aplikasi Termux dari recent apps.
> 4. Setelah stop bot: `termux-wake-unlock`.

---

## 5. Cara Jalankan di GitHub Actions (Cloud / Otomatis 24 jam)

> Catatan: Repo ini TIDAK menyertakan workflow `.github/workflows/`. Kalau ingin jalan otomatis di GitHub Actions, buat sendiri filenya (lihat contoh untuk bot lain) atau jalankan manual di VPS/Termux.

Cara cepat (kurang disarankan untuk repo publik karena env/Secret):
1. Push repo ke GitHub (pastikan `accounts.json`/`proxies.txt` di-ignore — tambahkan ke `.gitignore`).
2. Di **Settings → Secrets and variables → Actions**, buat secret:
   - `ACCOUNTS_JSON` — isi penuh accounts.json (satu baris JSON).
   - `TG_API_ID`, `TG_API_HASH`.
   - `CAPTCHA_KEY`.
   - `PROXIES` *(opsional)*.
3. Buat workflow yang menjalankan `python runner.py`.

**Rekomendasi:** untuk auto-claim 24 jam paling mudah pakai VPS + `tmux`, atau GitHub Actions bila mau gratis/managed.

---

## Catatan Teknis

- **2Captcha** (`http://2captcha.com/in.php`): dipakai untuk menyelesaikan Turnstile sebelum login. Butuh `CAPTCHA_KEY` yang valid & saldo di akun 2captcha.
- **Re-auth 7 jam**: token API di-re-auth tiap 7 jam (di bawah batas 8 jam) agar tidak kadaluarsa.
- **429 handling**: bila server rate-limit, script backoff (membaca `Retry-After` / acak 30–60s).
- **456 / token invalid**: jika claim mengembalikan 401, bot force re-auth di siklus berikutnya.

---

## Disclaimer

Gunakan dengan bijak dan patuhi ketentuan layanan (Telegram, MB/MusicMining, 2captcha). Penggunaan otomatisasi di luar ketentuan dapat berisiko pada akun Anda. Script disediakan apa adanya, tanpa jaminan.

## Lisensi

Tidak ditentukan (penggunaan pribadi).