#!/usr/bin/env python3
"""Generate a SHA-256 hash of your admin password for .env configuration."""

import hashlib
import getpass

def main():
    print("AgentForge Admin Password Hash Generator")
    print("=" * 42)
    pw = getpass.getpass("Enter admin password: ")
    if not pw:
        print("Error: password cannot be empty")
        return
    confirm = getpass.getpass("Confirm password: ")
    if pw != confirm:
        print("Error: passwords do not match")
        return
    pw_hash = hashlib.sha256(pw.encode()).hexdigest()
    print(f"\nAdd this to your .env file on the VPS:\n")
    print(f"ADMIN_PASSWORD_HASH={pw_hash}")
    print(f"\nNever share this hash or your password.")

if __name__ == "__main__":
    main()
