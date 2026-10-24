"""Deterministic condition terminology matching; original observations stay intact."""

import re
import unicodedata

MATCHER_VERSION = "condition-aliases-v1"


def label_key(value):
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    # Remove only terminology semantic tags, never clinical qualifiers or history.
    text = re.sub(r"\s*\((?:disorder|finding|situation)\)\s*$", "", text)
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


ALIASES = {
    "pre diabetes": "prediabetes",
    "pre diabetic": "prediabetes",
    "prediabetic": "prediabetes",
    "htn": "hypertension",
    "type 2 diabetes": "type 2 diabetes mellitus",
    "type ii diabetes": "type 2 diabetes mellitus",
    "type ii diabetes mellitus": "type 2 diabetes mellitus",
    "t2dm": "type 2 diabetes mellitus",
    "t2d": "type 2 diabetes mellitus",
    "type 2 diabetes mellitus at risk of hypoglycemia": (
        "type 2 diabetes mellitus at risk of hypoglycaemia"
    ),
    "essential primary hypertension": "essential hypertension",
    "primary hypertension": "essential hypertension",
    "unspecified essential hypertension": "essential hypertension",
}

# Direction matters: a specific recorded diagnosis satisfies a broader rule;
# the broader diagnosis never establishes a complication or a risk subtype.
PARENTS = {
    "essential hypertension": {"hypertension"},
    "type 2 diabetes mellitus with unspecified complications": {"type 2 diabetes mellitus"},
    "type 2 diabetes mellitus at risk of hypoglycaemia": {"type 2 diabetes mellitus"},
}


def canonical_condition(value):
    key = label_key(value)
    return ALIASES.get(key, key)


def condition_matches(actual, expected):
    actual, expected = canonical_condition(actual), canonical_condition(expected)
    return actual == expected or expected in PARENTS.get(actual, set())
