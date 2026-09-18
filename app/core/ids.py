import random
import time


def _to_base36(n: int) -> str:
    digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if n == 0:
        return "0"
    out = []
    while n:
        n, r = divmod(n, 36)
        out.append(digits[r])
    return "".join(reversed(out))


def generate_unique_id(prefix: str) -> str:
    """Reproduit le format d'identifiant utilise par trankyl_backend_nodejs
    pour vendor_unique_id/client_unique_id (meme base MySQL partagee) :
    PREFIX-{timestamp en base36}-{5 chiffres aleatoires}. Necessaire pour
    inserer un nouveau vendor/client depuis Academy sans violer les
    contraintes NOT NULL de ces colonnes."""
    timestamp = _to_base36(int(time.time() * 1000))
    rand = random.randint(10000, 99999)
    return f"{prefix}-{timestamp}-{rand}"
