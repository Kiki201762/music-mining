"""
MB Miner Multi-Account Auto Claim (pola atf_run)
- accounts.json  : daftar akun (session string)
- proxies.txt    : proxy, format user:pass@host:port
- Tiap akun: generate initData -> solve Turnstile (2captcha) -> auth -> start mining -> claim
- Proxy rotasi, claim lock serialisasi, staggered start, jitter, backoff 429.
"""
import os
import json
import asyncio
import time
import random
import urllib.parse
import aiohttp
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import RequestWebViewRequest

API_ID = 0  # (isi via env: TG_API_ID)
API_HASH = ""  # (isi via env: TG_API_HASH)
BOT_USERNAME = "MusicMiningMB_Bot"
WEBAPP_URL = "https://musicmb.site/"
API_BASE = "https://api.musicmb.site/api"
MINING_RESET_ENDPOINT = "/mining/reset"

CAPTCHA_KEY = ""  # (isi via env: CAPTCHA_KEY)
TURNSTILE_SITEKEY = ""  # (isi via env: TURNSTILE_SITEKEY)

# Interval claim per akun (detik). Tiap 30 menit.
CLAIM_INTERVAL = 1800

# Lock global: serialisasi request antar akun biar nggak nembak server barengan.
CLAIM_LOCK = asyncio.Lock()

# ---- Accounts ----
RAW_ACCOUNTS = os.getenv("ACCOUNTS_JSON")
if RAW_ACCOUNTS:
    try:
        ACCOUNTS = json.loads(RAW_ACCOUNTS)
    except Exception as e:
        print(f"Error parsing ACCOUNTS_JSON from env: {e}")
        ACCOUNTS = []
elif os.path.exists("accounts.json"):
    try:
        with open("accounts.json", "r", encoding="utf-8") as f:
            ACCOUNTS = json.load(f)
    except Exception as e:
        print(f"Error reading local accounts.json: {e}")
        ACCOUNTS = []
else:
    ACCOUNTS = []


# ---- Proxy ----
def load_proxies():
    raw = os.getenv("PROXIES")
    lines = []
    if raw:
        lines = raw.splitlines()
    elif os.path.exists("proxies.txt"):
        try:
            with open("proxies.txt", "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"Error reading proxies.txt: {e}")
            lines = []
    proxies = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if not ln.startswith("http://") and not ln.startswith("https://"):
            ln = "http://" + ln
        proxies.append(ln)
    return proxies


PROXIES = load_proxies()


class ProxyRotator:
    """Pegang daftar proxy satu akun (utama + cadangan), rotasi saat gagal."""
    def __init__(self, proxies, acc_name=""):
        self.proxies = proxies or []
        self.idx = 0
        self.acc_name = acc_name

    def current(self):
        if not self.proxies:
            return None
        return self.proxies[self.idx % len(self.proxies)]

    def rotate(self):
        if not self.proxies:
            return None
        self.idx = (self.idx + 1) % len(self.proxies)
        cur = self.current()
        print(f"[{self.acc_name}] Proxy rotate -> {self._mask(cur)}")
        return cur

    @staticmethod
    def _mask(url):
        if not url:
            return "DIRECT"
        try:
            return url.split("@", 1)[1]
        except IndexError:
            return url


def log(label, msg):
    print(f"[{label}] {msg}", flush=True)


async def fetch_init_data(session_str, acc_name):
    """Generate initData dari Telegram via RequestWebViewRequest.
    session_str bisa berupa StringSession (diawali '1') atau path file session.
    """
    if session_str.startswith("1") and len(session_str) > 100:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    else:
        # File session path (tanpa .session extension)
        client = TelegramClient(session_str, API_ID, API_HASH)
    await client.connect()
    try:
        bot_peer = await client.get_input_entity(BOT_USERNAME)
        web_view = await client(RequestWebViewRequest(
            peer=bot_peer,
            bot=bot_peer,
            platform="android",
            from_bot_menu=True,
            url=WEBAPP_URL
        ))
        parsed = urllib.parse.urlparse(web_view.url)
        params = urllib.parse.parse_qs(parsed.fragment)
        init_data = params.get("tgWebAppData", [""])[0]
        if not init_data:
            for part in web_view.url.split("#"):
                if "tgWebAppData" in part:
                    init_data = part.split("tgWebAppData=")[-1].split("&")[0]
                    break
        return init_data
    finally:
        await client.disconnect()


async def solve_turnstile(session, acc_name):
    """Solve Cloudflare Turnstile via 2captcha."""
    log(acc_name, "Solving Turnstile...")
    async with session.post("http://2captcha.com/in.php", data={
        "key": CAPTCHA_KEY,
        "method": "turnstile",
        "sitekey": TURNSTILE_SITEKEY,
        "pageurl": WEBAPP_URL,
        "action": "telegram_auth",
        "json": "1"
    }) as resp:
        result = await resp.json()
        if result.get("status") != 1:
            log(acc_name, f"2captcha submit error: {result}")
            return None
        task_id = result["request"]

    for attempt in range(60):
        await asyncio.sleep(5)
        async with session.get("http://2captcha.com/res.php", params={
            "key": CAPTCHA_KEY, "action": "get", "id": task_id, "json": "1"
        }) as resp:
            result = await resp.json()
            if result.get("status") == 1:
                log(acc_name, "Captcha solved!")
                return result["request"]
            elif "CAPCHA_NOT_READY" in str(result.get("request", "")):
                continue
            else:
                log(acc_name, f"2captcha error: {result}")
                return None
    log(acc_name, "Captcha timeout")
    return None


async def do_auth(session, init_data, turnstile_token, acc_name, rotator):
    """Auth ke API, return bearer token."""
    payload = {"init_data": init_data}
    if turnstile_token:
        payload["turnstile_token"] = turnstile_token

    for attempt in range(3):
        try:
            async with CLAIM_LOCK:
                await asyncio.sleep(random.uniform(0.5, 2.0))
                async with session.post(
                    f"{API_BASE}/auth/telegram",
                    json=payload,
                    proxy=rotator.current(),
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    status = resp.status
                    body = await resp.json(content_type=None)
                    if status == 200:
                        token = body.get("token") or body.get("access_token")
                        if not token and isinstance(body.get("data"), dict):
                            token = body["data"].get("token")
                        if token:
                            return token
                        log(acc_name, f"Auth 200 tapi token kosong: {body}")
                        return None
                    elif status == 428:
                        log(acc_name, "Auth 428: captcha required (token expired/invalid)")
                        return None
                    elif status == 429:
                        retry_after = resp.headers.get("Retry-After", "")
                        try:
                            backoff = max(float(retry_after), 30.0)
                        except ValueError:
                            backoff = random.uniform(30.0, 60.0)
                        log(acc_name, f"Auth 429, backoff {backoff:.0f}s")
                        await asyncio.sleep(backoff)
                        continue
                    else:
                        log(acc_name, f"Auth failed ({status}): {body}")
                        return None
        except Exception as ex:
            log(acc_name, f"Auth network error (attempt {attempt+1}): {ex}")
            rotator.rotate()
            await asyncio.sleep(5)
    return None


async def do_claim(session, token, acc_name, rotator):
    """Start mining + claim. Return True kalau sukses."""
    headers = {"Authorization": f"Bearer {token}"}

    for attempt in range(3):
        try:
            async with CLAIM_LOCK:
                await asyncio.sleep(random.uniform(0.5, 2.0))
                # Reset mining dulu (biar session mining segar, ga perlu run ulang)
                async with session.post(
                    f"{API_BASE}{MINING_RESET_ENDPOINT}",
                    headers=headers,
                    proxy=rotator.current(),
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 429:
                        retry_after = resp.headers.get("Retry-After", "")
                        try:
                            backoff = max(float(retry_after), 30.0)
                        except ValueError:
                            backoff = random.uniform(30.0, 60.0)
                        log(acc_name, f"Reset 429, backoff {backoff:.0f}s")
                        await asyncio.sleep(backoff)
                        continue
                    log(acc_name, f"Reset mining: {resp.status}")

                # Start mining (pastikan mining aktif)
                async with session.post(
                    f"{API_BASE}/mining/start",
                    headers=headers,
                    proxy=rotator.current(),
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 429:
                        retry_after = resp.headers.get("Retry-After", "")
                        try:
                            backoff = max(float(retry_after), 30.0)
                        except ValueError:
                            backoff = random.uniform(30.0, 60.0)
                        log(acc_name, f"Start 429, backoff {backoff:.0f}s")
                        await asyncio.sleep(backoff)
                        continue

                # Claim
                async with session.post(
                    f"{API_BASE}/mining/claim",
                    headers=headers,
                    proxy=rotator.current(),
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    status = resp.status
                    body = await resp.text()
                    if status == 200:
                        try:
                            data = json.loads(body)
                            earned = data.get("earned", 0)
                            log(acc_name, f"✅ CLAIM OK! Earned: {earned} MB")
                        except Exception:
                            log(acc_name, f"✅ CLAIM OK! -> {body[:100]}")
                        return True
                    elif status == 429:
                        retry_after = resp.headers.get("Retry-After", "")
                        try:
                            backoff = max(float(retry_after), 30.0)
                        except ValueError:
                            backoff = random.uniform(30.0, 60.0)
                        log(acc_name, f"Claim 429, backoff {backoff:.0f}s")
                        await asyncio.sleep(backoff)
                        continue
                    elif status == 401:
                        log(acc_name, "Claim 401: token expired, perlu re-auth")
                        return False
                    else:
                        log(acc_name, f"Claim failed ({status}): {body[:150]}")
                        return False
        except Exception as ex:
            log(acc_name, f"Claim network error (attempt {attempt+1}): {ex}")
            rotator.rotate()
            await asyncio.sleep(5)
    return False


async def account_worker(acc, start_delay=0.0):
    """Loop claim untuk satu akun. Auth sekali, claim berulang."""
    acc_name = acc.get("name", "Account")
    session_str = acc.get("session", "")
    rotator = acc.get("_rotator") or ProxyRotator([], acc_name)

    if not session_str:
        log(acc_name, "⚠️ Session string kosong, skip. Isi di accounts.json.")
        return

    if start_delay > 0:
        await asyncio.sleep(start_delay)

    log(acc_name, f"Proxy: {rotator._mask(rotator.current())}")

    async with aiohttp.ClientSession() as session:
        token = None
        last_auth_time = 0
        
        while True:
            try:
                # Auth kalau belum punya token atau token expired
                if not token or (time.time() - last_auth_time > 7 * 3600):  # Re-auth tiap 7 jam (aman < 8 jam)
                    log(acc_name, "🔐 Authenticating...")
                    
                    # 1. Generate initData
                    init_data = await fetch_init_data(session_str, acc_name)
                    if not init_data:
                        log(acc_name, "Failed initData, retry 60s")
                        await asyncio.sleep(60)
                        continue
                    log(acc_name, f"initData OK ({len(init_data)} chars)")

                    # 2. Solve Turnstile
                    turnstile_token = await solve_turnstile(session, acc_name)
                    if not turnstile_token:
                        log(acc_name, "Failed captcha, retry 60s")
                        await asyncio.sleep(60)
                        continue

                    # 3. Auth
                    token = await do_auth(session, init_data, turnstile_token, acc_name, rotator)
                    if not token:
                        log(acc_name, "Auth failed, retry 60s")
                        await asyncio.sleep(60)
                        continue
                    log(acc_name, f"✅ Auth OK! Token: {token[:25]}...")
                    last_auth_time = time.time()

                # 4. Claim (pakai token yang sama)
                success = await do_claim(session, token, acc_name, rotator)
                
                # Kalau claim gagal 401 (token expired), force re-auth di cycle berikutnya
                if not success:
                    log(acc_name, "⚠️ Claim failed, will re-auth next cycle")
                    token = None

            except Exception as e:
                log(acc_name, f"Worker error: {e}")
                rotator.rotate()

            # Jitter interval biar nggak serentak
            sleep_time = CLAIM_INTERVAL + random.uniform(-60, 60)
            log(acc_name, f"Next claim in {sleep_time:.0f}s")
            await asyncio.sleep(sleep_time)


async def main():
    if not ACCOUNTS:
        print("No accounts found. Isi accounts.json dulu.")
        return

    # Bagi proxy: akun i dapat proxies[2*i] (utama) & proxies[2*i+1] (cadangan)
    n_acc = len(ACCOUNTS)
    for idx, acc in enumerate(ACCOUNTS):
        acc_name = acc.get("name", f"Account {idx+1}")
        if PROXIES:
            if len(PROXIES) >= 2 * n_acc:
                pair = [PROXIES[2 * idx], PROXIES[2 * idx + 1]]
            else:
                pair = [PROXIES[idx % len(PROXIES)]]
                if len(PROXIES) > 1:
                    pair.append(PROXIES[(idx + 1) % len(PROXIES)])
            acc["_rotator"] = ProxyRotator(pair, acc_name)
        else:
            acc["_rotator"] = ProxyRotator([], acc_name)

    print("=" * 50)
    print("  MB Miner Multi-Account Auto Claim")
    print(f"  Running {n_acc} accounts concurrently")
    if PROXIES:
        print(f"  {len(PROXIES)} proxies loaded (2 per account)")
    else:
        print("  No proxies — DIRECT connection")
    print("  Press Ctrl+C to stop")
    print("=" * 50)

    tasks = []
    accumulated_delay = 0.0
    for idx, acc in enumerate(ACCOUNTS):
        if idx > 0:
            accumulated_delay += random.uniform(2.0, 5.0)
        tasks.append(account_worker(acc, start_delay=accumulated_delay))

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[STOPPED] Auto claim stopped gracefully.")
