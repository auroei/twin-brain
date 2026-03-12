#!/usr/bin/env python3
"""Interactive setup script for twin-brain.

Installs dependencies, validates credentials, and writes the .env file.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).parent / "apps" / "your-twin-brain"
ENV_FILE = APP_DIR / ".env"
MANIFEST_FILE = APP_DIR / "slack-app-manifest.yaml"

SLACK_ID_PATTERN = re.compile(r"^U[A-Z0-9]{8,}$")


def banner():
    print()
    print("=" * 50)
    print("  twin-brain Setup")
    print("=" * 50)
    print()


def run_cmd(cmd: list[str], label: str) -> bool:
    print(f"  > {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FAILED: {result.stderr.strip()}")
        return False
    print(f"  {label} OK")
    return True


def step_install_deps():
    print("Step 1/5: Installing dependencies")
    print("-" * 40)

    ok = run_cmd(
        [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
        "requirements.txt",
    )
    if not ok:
        print("\nFailed to install requirements.txt. Fix the error above and re-run.")
        sys.exit(1)

    ok = run_cmd(
        [sys.executable, "-m", "pip", "install", "-q", "-e", "libs/memex-core"],
        "memex-core",
    )
    if not ok:
        print("\nFailed to install memex-core. Fix the error above and re-run.")
        sys.exit(1)

    print()


def prompt_secret(label: str, prefix: str = "") -> str:
    while True:
        value = input(f"  {label}: ").strip()
        if not value:
            print("  Value cannot be empty. Try again.")
            continue
        if prefix and not value.startswith(prefix):
            print(f"  Expected value starting with '{prefix}'. Try again.")
            continue
        return value


def step_slack_bot_token() -> str:
    print("Step 2/5: Slack Bot Token")
    print("-" * 40)
    if MANIFEST_FILE.exists():
        print(f"  Create your Slack app using the manifest:")
        print(f"  {MANIFEST_FILE}")
        print(f"  (Slack API > Create New App > From a manifest)")
        print()
    print("  After creating the app, copy the Bot User OAuth Token")
    print("  from OAuth & Permissions (starts with xoxb-).")
    print()
    token = prompt_secret("Bot Token (xoxb-...)", "xoxb-")

    print("  Validating...", end=" ", flush=True)
    try:
        from slack_sdk import WebClient

        client = WebClient(token=token)
        result = client.auth_test()
        if result["ok"]:
            print(f'OK (workspace: "{result["team"]}", bot: "{result["user"]}")')
        else:
            print(f"FAILED: {result.get('error', 'unknown error')}")
            sys.exit(1)
    except ImportError:
        print("SKIPPED (slack_sdk not available yet — will validate on first run)")
    except Exception as e:
        print(f"FAILED: {e}")
        print("  Check that the token is correct and the app is installed.")
        sys.exit(1)
    print()
    return token


def step_slack_app_token() -> str:
    print("Step 3/5: Slack App-Level Token")
    print("-" * 40)
    print("  Go to Basic Information > App-Level Tokens.")
    print("  Create one with the 'connections:write' scope (starts with xapp-).")
    print()
    token = prompt_secret("App-Level Token (xapp-...)", "xapp-")
    print()
    return token


def step_gemini_key() -> str:
    print("Step 4/5: Google Gemini API Key")
    print("-" * 40)
    print("  Get one at: https://aistudio.google.com/app/apikey")
    print()
    key = prompt_secret("Gemini API Key")

    print("  Validating...", end=" ", flush=True)
    try:
        import google.generativeai as genai

        genai.configure(api_key=key)
        models = list(genai.list_models())
        flash_models = [m.name for m in models if "flash" in m.name.lower()]
        if flash_models:
            print(f"OK ({len(models)} models available)")
        else:
            print(f"OK ({len(models)} models available)")
    except ImportError:
        print("SKIPPED (google-generativeai not available yet)")
    except Exception as e:
        print(f"FAILED: {e}")
        print("  Check that the key is correct and the Generative Language API is enabled.")
        sys.exit(1)
    print()
    return key


def validate_slack_id(uid: str) -> bool:
    return bool(SLACK_ID_PATTERN.match(uid))


def prompt_user_ids(label: str, required: bool = False) -> list[str]:
    hint = "required" if required else "comma-separated, or Enter to skip"
    while True:
        raw = input(f"  {label} ({hint}): ").strip()
        if not raw:
            if required:
                print("  At least one ID is required. Try again.")
                continue
            return []

        ids = [uid.strip() for uid in raw.split(",") if uid.strip()]
        invalid = [uid for uid in ids if not validate_slack_id(uid)]
        if invalid:
            print(f"  Invalid Slack ID format: {', '.join(invalid)}")
            print("  IDs should look like U0XXXXXXXXX (Slack profile > ... > Copy member ID)")
            continue
        return ids


def step_roles() -> tuple[list[str], list[str]]:
    print("Step 5/5: Role Configuration")
    print("-" * 40)
    print("  Curators can tag threads + get weighted feedback.")
    print("  Get your Slack User ID: Profile > ... > Copy member ID")
    print()
    curator_ids = prompt_user_ids("Your Slack User ID + any other Curator IDs", required=True)
    teacher_ids = prompt_user_ids("Teacher IDs")
    print()
    return curator_ids, teacher_ids


def write_env(bot_token: str, app_token: str, gemini_key: str, curator_ids: list[str], teacher_ids: list[str]):
    lines = [
        "# Slack Credentials",
        f"SLACK_BOT_TOKEN={bot_token}",
        f"SLACK_APP_TOKEN={app_token}",
        "",
        "# Google Gemini API Key",
        f"GEMINI_API_KEY={gemini_key}",
        "",
        "# Role-Based Access Control",
        f"CURATOR_IDS={','.join(curator_ids)}",
    ]
    if teacher_ids:
        lines.append(f"TEACHER_IDS={','.join(teacher_ids)}")
    else:
        lines.append("# TEACHER_IDS=")
    lines.append("")

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("\n".join(lines))
    print(f"  .env written to {ENV_FILE}")


def main():
    os.chdir(Path(__file__).parent)
    banner()

    if ENV_FILE.exists():
        overwrite = input(f"  .env already exists at {ENV_FILE}. Overwrite? [y/N]: ").strip().lower()
        if overwrite != "y":
            print("  Keeping existing .env. Run the bot with:")
            print(f"  bash apps/your-twin-brain/run.sh")
            return
        print()

    step_install_deps()
    bot_token = step_slack_bot_token()
    app_token = step_slack_app_token()
    gemini_key = step_gemini_key()
    curator_ids, teacher_ids = step_roles()

    write_env(bot_token, app_token, gemini_key, curator_ids, teacher_ids)

    print()
    print("=" * 50)
    print("  Setup complete!")
    print("=" * 50)
    print()
    print("  Start the bot:")
    print(f"    bash apps/your-twin-brain/run.sh")
    print()


if __name__ == "__main__":
    main()
