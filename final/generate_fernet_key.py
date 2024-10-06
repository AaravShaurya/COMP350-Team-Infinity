from cryptography.fernet import Fernet
import secrets

key = Fernet.generate_key()
print(key.decode())

secret_key = secrets.token_urlsafe(32)
print(secret_key)

