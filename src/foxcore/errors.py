"""Concise console errors, including failures raised by asyncio task groups."""


def error_message(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        messages = list(dict.fromkeys(error_message(child) for child in error.exceptions))
        return "; ".join(messages)
    return str(error) or type(error).__name__
