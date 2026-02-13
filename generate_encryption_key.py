"""Generate a Fernet encryption key for MoltGrid encrypted storage."""
from cryptography.fernet import Fernet

key = Fernet.generate_key().decode()
print("\nGenerated encryption key:\n")
print(f"  ENCRYPTION_KEY={key}\n")
print("Add this line to your .env file on the VPS.")
print("WARNING: If you lose this key, encrypted data cannot be recovered.\n")
