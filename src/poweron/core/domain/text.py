import re

# Apostrophes, Ukrainian/Russian spelling variants and Latin letters typed instead of Cyrillic
SPELLING = str.maketrans(
    {"ʼ": "'", "’": "'", "‘": "'", "`": "'", "ё": "е", "є": "е"}
    | dict(zip("aeiocpxk", "аеіосрхк", strict=True))
)
TYPE_PREFIX = re.compile(r"^(вул|просп|пров|бул|пл|м|с|смт|буд)\.?\s+")


def normalise(text: str) -> str:
    text = text.casefold().translate(SPELLING)
    return TYPE_PREFIX.sub("", " ".join(text.split()))
