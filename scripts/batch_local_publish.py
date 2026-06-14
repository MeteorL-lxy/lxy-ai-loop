#!/usr/bin/env python3
"""
Batch publish local videos with promotion links to Facebook accounts
20 accounts × 3 videos = 60 posts
"""

import os
import json
import subprocess
import time

# Video to promotion link mapping (found from drama database)
VIDEO_MAP = [
    {
        "file": "GoodShort Prescribed One Immortal Boyfriend第3集.mp4",
        "link": "https://test-short.inbeidou.ai/link/goodshort/serial/TlOqE5EQyzR2xIHeUipq4g==",
        "hashtag": "#GoodShort"
    },
    {
        "file": "GoodShort You Can Live Well Alone第3集.mp4",
        "link": "https://test-short.inbeidou.ai/link/goodshort/serial/TUYKVujKRtMlSBeI96v1hw==",
        "hashtag": "#GoodShort"
    },
    {
        "file": "MoboReels The Heart He Hates Is Her Only Gift第6集.mp4",
        "link": "https://test-short.inbeidou.ai/link/moboreels/serial/45893322",
        "hashtag": "#MoboReels"
    },
    {
        "file": "SnackShort 7-Year Itch_ Trap for Cheaters第4集.mp4",
        "link": "https://test-short.inbeidou.ai/link/snackshort/serial/RkJhTE0xVTk3TEJwYUl3MDE5aVZwZz09",
        "hashtag": "#SnackShort"
    },
    {
        "file": "SnackShort CEO's Contract Marriage第4集.mp4",
        "link": "https://test-short.inbeidou.ai/link/snackshort/serial/eXdIWVg0Q0Z0VUl1NTdZMG1ER2t0dz09",
        "hashtag": "#SnackShort"
    },
    {
        "file": "SnackShort Clash of Crowns第5集.mp4",
        "link": "https://test-short.inbeidou.ai/link/snackshort/serial/WlpHdS8xQ1BHN3cwaTllNE1wQXFsZz09",
        "hashtag": "#SnackShort"
    },
    {
        "file": "SnackShort Double Joy Turns to Betrayal第5集.mp4",
        "link": "https://test-short.inbeidou.ai/link/snackshort/serial/a3ZEdE9mTkdJd0NUaVd5clJGQWx4UT09",
        "hashtag": "#SnackShort"
    },
    {
        "file": "SnackShort Fake Debt Killed My Mom第5集.mp4",
        "link": "https://test-short.inbeidou.ai/link/snackshort/serial/TGN4bmd2S2pXZ2tWVkFKU1c3TzRjZz09",
        "hashtag": "#SnackShort"
    },
]

BATCH_DIR = "/Users/xinyuliu/Desktop/work/barry-video/data/flywheel/clipped/batch"

def get_accounts():
    """Get Facebook account IDs"""
    cmd = 'python3 ~/.openclaw/extensions/barry-video/backend/inbeidou_cli.py publish accounts --json'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    accounts = json.loads(result.stdout)
    fb_accounts = [a for a in accounts if a.get('type') == 'FACEBOOK']
    return [(a['id'], a['social_name']) for a in fb_accounts]

def publish_video(file_path, account_id, link, hashtag):
    """Publish one video to one account"""
    text = f"Watch the full series! 👉 {link}\n🌟 Continue the story here\n📲 Find the full series on the app\n#ShortDrama {hashtag}"

    cmd = f'''python3 ~/.openclaw/extensions/barry-video/backend/flywheel_cli.py run-local \
        --file "{file_path}" \
        --account-id {account_id} \
        --publish-platform FACEBOOK \
        --text "{text}" \
        --timeout 600'''

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
    return result.returncode == 0, result.stdout + result.stderr

def main():
    accounts = get_accounts()
    print(f"Found {len(accounts)} Facebook accounts")

    # Build upload list: 20 accounts × (cycle through 8 videos) = expand to 60
    # Actually we'll use each account 3 times with different videos
    uploads = []
    for i in range(20):
        acc_id, acc_name = accounts[i]
        for j in range(3):
            video = VIDEO_MAP[(i + j) % len(VIDEO_MAP)]
            uploads.append({
                "account_id": acc_id,
                "account_name": acc_name,
                "file": os.path.join(BATCH_DIR, video["file"]),
                "link": video["link"],
                "hashtag": video["hashtag"]
            })

    print(f"Total uploads: {len(uploads)}")
    print("Starting batch publish...")

    success_count = 0
    fail_count = 0

    for idx, upload in enumerate(uploads):
        print(f"[{idx+1}/{len(uploads)}] {upload['account_name']} <- {upload['file']}")
        try:
            ok, msg = publish_video(
                upload["file"],
                upload["account_id"],
                upload["link"],
                upload["hashtag"]
            )
            if ok:
                success_count += 1
                print(f"  ✓ Success")
            else:
                fail_count += 1
                print(f"  ✗ Failed: {msg[:100]}")
        except Exception as e:
            fail_count += 1
            print(f"  ✗ Error: {e}")

        time.sleep(2)  # Rate limit

    print(f"\n=== Complete ===")
    print(f"Success: {success_count}, Failed: {fail_count}")

if __name__ == "__main__":
    main()