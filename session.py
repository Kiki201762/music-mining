"""
Generate session string untuk MusicMining multi-account.
Tiap akun: input API_ID -> API_HASH -> OTP Telegram -> auto-save.
Loop terus sampai ketik 'q'.
"""
import os
import json
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError


def load_accounts():
    if os.path.exists("accounts.json"):
        try:
            with open("accounts.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_accounts(accounts):
    with open("accounts.json", "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2)


async def generate_one(accounts):
    """Generate 1 akun: API_ID -> API_HASH -> login -> save."""
    idx = len(accounts) + 1
    print(f"\n{'='*50}")
    print(f"  ACCOUNT #{idx}")
    print(f"{'='*50}")

    # Nama akun
    acc_name = input(f"[{idx}] Nama akun (atau 'q' untuk selesai): ").strip()
    if acc_name.lower() == 'q':
        return False
    if not acc_name:
        print("[SKIP] Nama kosong, coba lagi.")
        return True

    # Cek duplikat
    for acc in accounts:
        if acc.get("name") == acc_name:
            print(f"[WARN] '{acc_name}' sudah ada. Pakai nama lain.")
            return True

    # API_ID
    api_id_str = input(f"[{idx}] API_ID: ").strip()
    if not api_id_str or not api_id_str.isdigit():
        print("[SKIP] API_ID tidak valid, coba lagi.")
        return True
    api_id = int(api_id_str)

    # API_HASH
    api_hash = input(f"[{idx}] API_HASH: ").strip()
    if not api_hash:
        print("[SKIP] API_HASH kosong, coba lagi.")
        return True

    # Login Telegram
    print(f"\n--- Connecting to Telegram for '{acc_name}' ---")
    try:
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()

        # Masukin nomor phone
        phone = input(f"[{idx}] Nomor telepon (format +62xxx): ").strip()
        await client.send_code_request(phone)

        # OTP
        code = input(f"[{idx}] OTP code: ").strip()
        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            # 2FA aktif, minta password
            password = input(f"[{idx}] 2FA Password: ").strip()
            await client.sign_in(phone=phone, password=password)

        me = await client.get_me()
        session_str = client.session.save()
        await client.disconnect()

        print(f"✅ Logged in: {me.first_name} (@{me.username})")

        # Simpan
        accounts.append({
            "name": acc_name,
            "session": session_str
        })
        save_accounts(accounts)
        print(f"[OK] Saved! accounts.json now has {len(accounts)} account(s)")

    except Exception as e:
        print(f"[ERROR] Failed: {e}")
        try:
            await client.disconnect()
        except:
            pass

    return True


async def main():
    accounts = load_accounts()
    print(f"[INFO] Loaded {len(accounts)} existing account(s) from accounts.json")
    print("=== Generate Session (loop mode) ===")
    print("Tiap akun: API_ID -> API_HASH -> Phone -> OTP -> Save")
    print("Ketik 'q' di prompt nama untuk selesai\n")

    while True:
        cont = await generate_one(accounts)
        if not cont:
            break

    print(f"\n[DONE] Total {len(accounts)} account(s) in accounts.json")


if __name__ == "__main__":
    asyncio.run(main())
