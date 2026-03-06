import bleach

# Define global whitelists for sanitization
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'a', 'hr',
    'table', 'thead', 'tbody', 'tr', 'th', 'td', 'img'
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'code': ['class'],
    'pre': ['class'],
    '*': ['id']
}

def sanitize_html(html, tags=None, attributes=None):
    """
    Sanitize HTML using bleach with the defined whitelists.
    """
    if html is None:
        return ""
    
    return bleach.clean(
        html,
        tags=tags or ALLOWED_TAGS,
        attributes=attributes or ALLOWED_ATTRIBUTES,
        strip=True
    )

def sanitize_bio(text):
    """
    Specifically for bios, we allow a more restricted set of tags.
    """
    if text is None:
        return ""
        
    bio_tags = ['p', 'br', 'strong', 'em', 'ul', 'li', 'ol']
    return bleach.clean(text, tags=bio_tags, strip=True)

def strip_all_tags(text):
    """
    Completely strip all HTML tags. Useful for terminal previews.
    """
    if text is None:
        return ""
    return bleach.clean(text, tags=[], strip=True)
