def greet(name):
    """Create a friendly greeting for someone."""
    return f"Hello, {name}!"


def calculate_total(prices):
    """Add up the prices in a shopping cart."""
    return sum(prices)


def find_long_words(words, min_length=5):
    """Find words that have at least the requested number of letters."""
    return [word for word in words if len(word) >= min_length]
