# test_chat.py
# ---------------------------------------------------------
# Quick terminal chat to test the bot locally without needing
# Twilio/WhatsApp. Hits the /test/message endpoint in main.py.
#
# Usage:
#   1. Run the bot:      uvicorn main:app --reload --port 8001
#   2. Run this, in a separate terminal:  python test_chat.py
# ---------------------------------------------------------

import requests

API_URL = "http://localhost:8001/test/message"
USER_NUMBER = "whatsapp:+911111111111"  # fake number, just needs to stay consistent for state

print("=" * 50)
print("  FYNLO BOT — LOCAL TEST CHAT")
print("  Type 'exit' or 'quit' to end, 'reset' for a fresh number.")
print("=" * 50 + "\n")

while True:
    try:
        user_msg = input("You: ").strip()
        if not user_msg:
            continue
        if user_msg.lower() in ("exit", "quit"):
            break
        if user_msg.lower() == "reset":
            USER_NUMBER = f"whatsapp:+91{__import__('random').randint(1000000000, 9999999999)}"
            print(f"\n[Starting fresh as {USER_NUMBER}]\n")
            continue

        response = requests.post(
            API_URL,
            json={"message": user_msg, "user_number": USER_NUMBER},
            timeout=20,
        )

        if response.status_code == 200:
            data = response.json()
            print(f"\nBot: {data.get('reply')}\n")
        else:
            print(f"\nError ({response.status_code}): {response.text}\n")

    except KeyboardInterrupt:
        break
    except requests.exceptions.ConnectionError:
        print("\nCouldn't connect — is the bot running? (uvicorn main:app --reload --port 8001)\n")
        break
    except Exception as e:
        print(f"\nFailed: {e}\n")

print("\nBye!")