"""Which oblenergo a subqueue belongs to.

Ternopil subqueues keep their plain keys ("4.1"), so stored data needs no migration;
other providers' subqueues are namespaced ("voe:6.1").
"""

TOE = "toe"
VOE = "voe"
PROVIDERS = (TOE, VOE)
# The catalog_cache row whose `fetched_at` is the last Volyn catalogue import.
VOE_CATALOG_IMPORTED_KEY = "voe:imported"


def provider_of(cherg_gpv: str) -> str:
    prefix, separator, _ = cherg_gpv.partition(":")
    return prefix if separator else TOE


def plain_subqueue(cherg_gpv: str) -> str:
    """The subqueue as the oblenergo writes it, for display."""
    return cherg_gpv.partition(":")[2] or cherg_gpv


def scoped_subqueue(provider: str, plain: str) -> str:
    return plain if provider == TOE else f"{provider}:{plain}"
