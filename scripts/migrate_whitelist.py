import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import firestore
from datetime import datetime, timezone

WHITELIST_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "whitelist.txt")
COLLECTION = "users_config"
SUPERADMIN_EMAIL = "darwin.salinas@temple.com.ar"


def read_emails(path):
    emails = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            emails.append(line.lower())
    return emails


def main():
    db = firestore.Client()
    emails = read_emails(WHITELIST_PATH)

    created = 0
    skipped = 0

    for email in emails:
        ref = db.collection(COLLECTION).document(email)
        doc = ref.get()

        if doc.exists:
            print(f"SKIP    {email}")
            skipped += 1
            continue

        now = datetime.now(timezone.utc)

        if email == SUPERADMIN_EMAIL:
            data = {
                "role": "superadmin",
                "can_edit_objectives": True,
                "brands": ["*"],
                "created_at": now,
                "updated_at": now,
            }
        else:
            data = {
                "role": "viewer",
                "can_edit_objectives": False,
                "brands": ["*"],
                "created_at": now,
                "updated_at": now,
            }

        ref.set(data)
        print(f"CREATED {email}")
        created += 1

    print()
    print(f"Summary: {created} created, {skipped} skipped")


if __name__ == "__main__":
    main()
