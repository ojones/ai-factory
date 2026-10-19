# The Preview Token an app honours: derived from a master secret held in the Factory and the app's name, so nothing is stored per app.
import hashlib
import hmac


def for_app(master_secret, slug):
    # Same derivation as infra/app-staging/preview-token.sh.
    return hmac.new(master_secret.encode(), slug.encode(), hashlib.sha256).hexdigest()
