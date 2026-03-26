"""CLI entry point for bub-im-bridge."""

import asyncio
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m bub_im_bridge <command>")
        print()
        print("Commands:")
        print("  login    Login to WeChat (scan QR code)")
        sys.exit(1)

    command = sys.argv[1]

    if command == "login":
        from weixin_agent import login

        asyncio.run(login())
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
