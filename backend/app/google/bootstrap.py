"""One-time bootstrap: create the notes Doc inside NOTES_FOLDER_ID (goal 7).

`drive.file` can't reach a hand-made doc, so the app creates its own notes Doc
inside the designated folder and the owner copies the printed id into `.env` as
`NOTES_DOC_ID`. This is the ONLY file-creation path in the app.

    uv run python -m app.google.bootstrap

Requires `NOTES_FOLDER_ID` in `backend/.env` (the id from the Drive folder's URL)
and a token that already carries `drive.file` (re-auth first — see
docs/goals/goal-7-owner-steps.md).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv


async def _bootstrap() -> int:
    # Standalone script: load backend/.env exactly as main.py does at boot.
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")

    from app.google import docs as docs_client

    folder_id = os.environ.get("NOTES_FOLDER_ID")
    if not folder_id:
        print(
            "ERROR: NOTES_FOLDER_ID is not set in backend/.env.\n"
            "Create/pick a Drive folder, copy its id from the URL, and set it first."
        )
        return 1

    doc_id = await docs_client.create_doc_in_folder("Dashboard — Notes", folder_id)
    print("Created notes Doc inside the folder.")
    print(f"\n  NOTES_DOC_ID={doc_id}\n")
    print("Paste that line into backend/.env, then restart the backend.")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_bootstrap()))


if __name__ == "__main__":
    main()
