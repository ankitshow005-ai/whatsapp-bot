"""
One-off script — flushes the Upstash Vector semantic cache completely.

Run this once to clear out any personalized replies (names, booking
details, etc.) that got cached BEFORE the known_name gating was added to
_understand_and_respond() in main.py. The cache persists independently of
your app's deploys, so old poisoned entries stick around until explicitly
wiped, even after the code fix ships.

Usage:
    python flush_cache.py
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

url = os.environ["UPSTASH_VECTOR_REST_URL"]
token = os.environ["UPSTASH_VECTOR_REST_TOKEN"]

resp = requests.post(
    f"{url}/reset",
    headers={"Authorization": f"Bearer {token}"},
)

if resp.ok:
    print("Semantic cache flushed clean.")
else:
    print(f"Flush failed: {resp.status_code} {resp.text}")