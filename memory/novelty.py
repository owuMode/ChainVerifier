# memory/novelty.py
"""
Novelty check — decide if a conversation has new content worth extracting.

Design:
  * Pure functions. No I/O.
  * Simple token-overlap against a set of "already-seen" tokens.
  * Used to skip the extractor LLM call when nothing new happened.

A "token" here is a lowercase alphanumeric word of length >= 3 that
is not a common stopword. This is deliberately cheap — it exists only
to gate the much more expensive LLM extractor.
"""

from __future__ import annotations

import re


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+", re.UNICODE)


# Words that almost never carry memorable meaning.
_STOPWORDS = frozenset({
    # Articles, conjunctions, prepositions
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "as",
    "of", "in", "on", "at", "to", "for", "with", "by", "from",
    "this", "that", "these", "those",
    # Pronouns
    "i", "you", "he", "she", "it", "we", "they",
    "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their",
    "mine", "yours", "hers", "ours", "theirs",
    # Auxiliary verbs
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "must", "can",
    # Common short replies / chat noise
    "hi", "hey", "hello", "yo", "sup", "thanks", "thank", "thx",
    "ok", "okay", "k", "yes", "no", "yeah", "yep", "nope", "nah",
    "hmm", "hmmm", "uh", "um", "ah", "oh", "eh", "welp",
    "bye", "cya", "later", "morning", "evening", "night",
    # Hindi / Hinglish replies
    "haan", "han", "nahi", "nahin", "theek", "thik", "achha", "acha",
    "bhai", "yaar", "ji", "haji",
    # Filler words
    "very", "much", "lot", "lots", "really", "quite", "just", "only",
    "also", "too", "such", "more", "most", "some", "any", "all",
    "not", "now", "here", "there", "where", "when", "why", "how",
    "what", "which", "who", "whom", "whose",
    # Common verbs that carry little meaning in a memory
    "get", "got", "make", "made", "take", "took", "go", "going", "went",
    "come", "coming", "came", "see", "saw", "seen", "know", "knew",
    "think", "thought", "say", "said", "tell", "told", "want", "wanted",
    "need", "needed", "use", "used", "using", "try", "tried",
    "help", "helped", "helping", "ask", "asked", "asking",
})


def tokenize(text: str) -> set[str]:
    """
    Return the set of meaningful lowercase tokens in `text`.

    Tokens shorter than 3 characters or in the stopword list are
    dropped. Empty input returns an empty set.
    """
    if not text:
        return set()
    return {
        t.lower()
        for t in _TOKEN_RE.findall(text)
        if len(t) >= 3 and t.lower() not in _STOPWORDS
    }


def new_tokens(
    *,
    conversation_tokens: set[str],
    known_tokens: set[str],
) -> set[str]:
    """
    Return the tokens in the conversation that aren't in `known_tokens`.
    """
    return set(conversation_tokens) - set(known_tokens)


def is_worth_extracting(
    *,
    conversation_tokens: set[str],
    known_tokens: set[str],
    min_new_tokens: int = 3,
) -> bool:
    """
    Return True if the conversation contains at least `min_new_tokens`
    tokens that aren't already known.

    Very cheap. Used to skip the extractor LLM call on chit-chat.
    """
    if not conversation_tokens:
        return False
    return len(new_tokens(
        conversation_tokens=conversation_tokens,
        known_tokens=known_tokens,
    )) >= int(min_new_tokens)


def novelty_ratio(
    *,
    conversation_tokens: set[str],
    known_tokens: set[str],
) -> float:
    """
    Fraction of conversation tokens that are new, in [0.0, 1.0].
    Useful for logging and tuning.
    """
    if not conversation_tokens:
        return 0.0
    new = new_tokens(
        conversation_tokens=conversation_tokens,
        known_tokens=known_tokens,
    )
    return len(new) / float(len(conversation_tokens))