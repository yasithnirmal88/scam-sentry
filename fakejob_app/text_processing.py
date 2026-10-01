"""
text_processing.py
-------------------
Lightweight NLP preprocessing pipeline (tokenization, stop-word removal,
lowercasing, punctuation removal, normalization) implemented with plain
Python + regex so the project has no heavyweight external NLP dependency
to install. This mirrors the "Natural Language Processing (NLP)" stage
described in the project proposal.
"""

import re

# A compact but effective English stop-word list.
STOPWORDS = set("""
a about above after again against all am an and any are aren't as at be
because been before being below between both but by can't cannot could
couldn't did didn't do does doesn't doing don't down during each few for
from further had hadn't has hasn't have haven't having he he'd he'll he's
her here here's hers herself him himself his how how's i i'd i'll i'm i've
if in into is isn't it it's its itself let's me more most mustn't my
myself no nor not of off on once only or other ought our ours ourselves
out over own same shan't she she'd she'll she's should shouldn't so some
such than that that's the their theirs them themselves then there there's
these they they'd they'll they're they've this those through to too under
until up very was wasn't we we'd we'll we're we've were weren't what
what's when when's where where's which while who who's whom why why's
with won't would wouldn't you you'd you'll you're you've your yours
yourself yourselves
""".split())

_TOKEN_RE = re.compile(r"[a-zA-Z]+")


def clean_text(text):
    """Lowercase, strip punctuation/digits-as-noise, normalize whitespace."""
    if not text:
        return ""
    text = text.replace("\u00a0", " ")
    text = re.sub(r"http\S+|www\.\S+", " ", text)          # strip URLs
    text = re.sub(r"[^A-Za-z\s]", " ", text)                # strip punctuation/numbers
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def tokenize(text):
    return _TOKEN_RE.findall(text.lower())


def remove_stopwords(tokens):
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def preprocess(text):
    """
    Full pipeline: tokenization -> stop-word removal -> lowercase ->
    punctuation removal -> normalization. Returns a cleaned string
    suitable for TF-IDF vectorization.
    """
    cleaned = clean_text(text)
    tokens = tokenize(cleaned)
    tokens = remove_stopwords(tokens)
    return " ".join(tokens)
