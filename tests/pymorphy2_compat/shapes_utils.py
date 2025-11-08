"""
Утилиты для работы с капитализацией слов (из pymorphy2)
"""


def _make_the_same_case(word, example):
    """
    Приводит регистр слова word к регистру примера example.
    """
    if not example:
        return word.lower()

    if example.islower():
        return word.lower()
    elif example.isupper():
        return word.upper()
    elif example.istitle():
        return word.title()
    else:
        return word.lower()


def restore_capitalization(word, example):
    """
    Приводит капитализацию слова word к той же, что в примере example:

        >>> restore_capitalization('bye', 'Hello')
        'Bye'
        >>> restore_capitalization('half-an-hour', 'Minute')
        'Half-An-Hour'
        >>> restore_capitalization('usa', 'IEEE')
        'USA'
        >>> restore_capitalization('pre-world', 'anti-World')
        'pre-World'
    """
    if "-" in example:
        results = []
        word_parts = word.split("-")
        example_parts = example.split("-")

        for i, part in enumerate(word_parts):
            if len(example_parts) > i:
                results.append(_make_the_same_case(part, example_parts[i]))
            else:
                results.append(part.lower())

        return "-".join(results)

    return _make_the_same_case(word, example)
