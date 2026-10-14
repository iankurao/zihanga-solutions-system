"""Password rules shared by the web app and the admin script."""

COMMON_PASSWORDS = frozenset({
    'password', 'password1', 'password123', '12345678', '123456789', '1234567890',
    'qwerty123', 'qwertyuiop', 'iloveyou', 'admin123', 'welcome1', 'letmein123',
    'zehunger', 'zehunger123', 'blacksoldierfly', 'changeme', 'passw0rd',
})


def password_problem(password, *, email=None, username=None):
    """Return why ``password`` is not acceptable, or None.

    One rule for every way a password is set: at least 10 characters, at most
    128, not a well-known password and not the user's own name or email.
    """
    if not isinstance(password, str) or len(password) < 10:
        return 'Password must be at least 10 characters long'
    if len(password) > 128:
        return 'Password must be at most 128 characters long'
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(password)) < 4:
        return 'Password is too easy to guess; choose a longer or less common one'
    for own in (username, (email or '').split('@')[0]):
        if own and len(own) >= 3 and own.lower() in lowered:
            return 'Password must not contain your username or email'
    return None
