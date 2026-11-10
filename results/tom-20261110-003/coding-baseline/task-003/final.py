def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ('true', 'yes', '1'):
            return True
        if normalized in ('false', 'no', '0'):
            return False
        raise ValueError(f"Invalid boolean string: {value}")
    raise TypeError(f"Expected string or int, got {type(value).__name__}")
