from email_validator import EmailNotValidError, validate_email


def normalize_email(value):
    try:
        info = validate_email(
            str(value or "").strip(),
            check_deliverability=False,
        )
        return info.normalized.lower()
    except EmailNotValidError:
        return None


def clean_name(value):
    name = " ".join(str(value or "").split())

    if len(name) < 2 or len(name) > 60 or not name.isprintable():
        return None

    return name