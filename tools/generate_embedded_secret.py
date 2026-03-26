from cryptography.fernet import Fernet


def main():
    password = input("DB password to embed: ").strip()
    if not password:
        raise SystemExit("Password cannot be empty.")

    key = Fernet.generate_key()
    token = Fernet(key).encrypt(password.encode("utf-8"))

    print("\nPaste these values into dashboard_app/secret_store.py:\n")
    print(f'EMBEDDED_FERNET_KEY = "{key.decode("utf-8")}"')
    print(f'EMBEDDED_DB_PASSWORD_TOKEN = "{token.decode("utf-8")}"')


if __name__ == "__main__":
    main()

