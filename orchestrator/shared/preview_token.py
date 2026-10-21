import hashlib
import hmac


def for_app(master_secret, slug):
    return hmac.new(master_secret.encode(), slug.encode(), hashlib.sha256).hexdigest()
