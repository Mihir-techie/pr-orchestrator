def reverse_string(s: str) -> str:
    """Simple string reversal utility for lightweight Groq routing test."""
    return s[::-1]

def reverse_string_with_spaces(s:str)-> str:
    """Reverse a String and Preserve spaces"""
    return ''.join(s[i]for i in range(len(s)-1, -1, -1))
