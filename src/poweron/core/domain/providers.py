"""Which oblenergo a subqueue belongs to.

Ternopil subqueues keep their plain keys ("4.1"), so stored data needs no migration;
other providers' subqueues are namespaced ("voe:6.1").
"""

TOE = "toe"
VOE = "voe"
LOE = "loe"
# Dnipropetrovsk oblast has two operators whose group names collide, so each is a provider.
DNEM = "dnem"
CEK = "cek"
# The region button and catalogue shared by both Dnipropetrovsk operators.
DNIPRO = "dnipro"
# catalog_cache keys of YASNO's merged city list.
YASNO_CACHE_PREFIX = "yasno:"
LOE_CACHE_PREFIX = "loe:"
# catalog_cache keys of the Volyn lists; every import clears them.
VOE_CACHE_PREFIX = "voe:"
# The catalog_cache row whose `fetched_at` is the last Volyn catalogue import.
VOE_CATALOG_IMPORTED_KEY = VOE_CACHE_PREFIX + "imported"


# Providers that share a region; every other provider is a region of its own.
REGION_OF = {DNEM: DNIPRO, CEK: DNIPRO}


def region_of(provider: str) -> str:
    return REGION_OF.get(provider, provider)


def provider_of(cherg_gpv: str) -> str:
    prefix, separator, _ = cherg_gpv.partition(":")
    return prefix if separator else TOE


def plain_subqueue(cherg_gpv: str) -> str:
    """The subqueue as the oblenergo writes it, for display."""
    return cherg_gpv.partition(":")[2] or cherg_gpv


def scoped_subqueue(provider: str, plain: str) -> str:
    return plain if provider == TOE else f"{provider}:{plain}"
