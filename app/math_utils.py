def calculate_percentage(part: float, whole: float) -> float:
    """Calculate simple percentage for lightweight testing."""
    if whole == 0:
        return 0.0
    return (part / whole) * 100.0

