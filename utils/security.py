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
    
    cleaned = bleach.clean(
        html,
        tags=tags or ALLOWED_TAGS,
        attributes=attributes or ALLOWED_ATTRIBUTES,
        strip=True
    )
    
    # Link safety for external targets
    if 'rel' not in ALLOWED_ATTRIBUTES.get('a', []):
        try:
             import re
             cleaned = re.sub(r'<a\s+([^>]*target=["\']_blank["\'][^>]*)>', r'<a \1 rel="noopener noreferrer">', cleaned)
        except:
             pass
             
    return cleaned

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

def error_response(message, status_code=500, exc=None):
    """
    Standardize API error responses and log internal details without leaking them.
    """
    import logging
    if exc:
        logging.error(f"API Error [{status_code}]: {message} | Internal: {str(exc)}")
    
    # In production, we might want to be even more vague for 500s
    return {"error": message}, status_code
