def chunk_array(data: list, size: int) -> list:
    """Utility to split lists into chunks for lightweight LLM testing."""
    if size <= 0:
        return [data]
    return [data[i:i + size] for i in range(0, len(data), size)]

