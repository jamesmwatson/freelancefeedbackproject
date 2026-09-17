"""Quote-location diagnostics excerpted from the original project.

A match indicates textual location, not correct speaker attribution, feedback
classification, or support for a professional claim. See docs/code-provenance.md.
"""
import re
import unicodedata


def collapse_whitespace(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def normalize_typography(value: str) -> str:
    translations = str.maketrans({
        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
        "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
        "\u2026": "...", "\u00a0": " ",
    })
    return collapse_whitespace(value.translate(translations))


def alphanumeric_signature(value: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold()))


def evidence_match_category(source_text: str, stored_quote: str, raw_quote: str) -> str:
    if stored_quote and stored_quote in source_text:
        return "verified_exact"
    quote = raw_quote.strip()
    if not collapse_whitespace(quote):
        return "missing_model_quote"
    if quote in source_text:
        return "raw_quote_exact_but_flagged"
    if collapse_whitespace(quote) in collapse_whitespace(source_text):
        return "whitespace_only"
    if collapse_whitespace(quote).casefold() in collapse_whitespace(source_text).casefold():
        return "case_or_whitespace"
    if normalize_typography(quote).casefold() in normalize_typography(source_text).casefold():
        return "typography_or_whitespace"
    quote_signature = alphanumeric_signature(quote)
    if len(quote_signature.split()) >= 3 and quote_signature in alphanumeric_signature(source_text):
        return "punctuation_or_formatting"
    return "not_locatable_by_safe_normalization"
