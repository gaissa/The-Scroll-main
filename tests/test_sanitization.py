import bleach
import markdown

def simulate_app_markdown(text):
    # This mirrors the logic I added to app.py
    html = markdown.markdown(text, extensions=['extra', 'codehilite', 'toc'])
    allowed_tags = [
        'p', 'br', 'strong', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'a', 'hr',
        'table', 'thead', 'tbody', 'tr', 'th', 'td', 'img'
    ]
    allowed_attrs = {
        'a': ['href', 'title', 'target'],
        'img': ['src', 'alt', 'title', 'width', 'height'],
        'code': ['class'],
        'pre': ['class'],
        '*': ['id']
    }
    return bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs, strip=True)

def simulate_bio_sanitization(text):
    # This mirrors the logic I added to bio_generator.py
    allowed_tags = ['p', 'br', 'strong', 'em', 'ul', 'li', 'ol']
    return bleach.clean(text, tags=allowed_tags, strip=True)

def test_xss_vectors():
    payloads = [
        ("<script>alert('XSS')</script>", "should strip script tags"),
        ("<img src=x onerror=alert(1)>", "should strip onerror attributes"),
        ("<a href='javascript:alert(1)'>Click me</a>", "should strip javascript: protocols"),
        ("<div onmouseover='alert(1)'>Hover me</div>", "should strip onmouseover and unknown tags like div"),
        ("NORMAL TEXT", "should preserve normal text"),
        ("<strong>BOLD</strong>", "should preserve allowed tags"),
    ]
    
    print("--- Testing Markdown Sanitization (app.py) ---")
    for payload, desc in payloads:
        result = simulate_app_markdown(payload)
        print(f"Payload: {payload}")
        print(f"Result:  {result}")
        if "<script" in result or "onerror" in result or "javascript:" in result:
             print(f"FAILED: {desc}")
        else:
             print(f"PASSED: {desc}")
    print("\n")

    print("--- Testing Bio Sanitization (bio_generator.py) ---")
    for payload, desc in payloads:
        result = simulate_bio_sanitization(payload)
        print(f"Payload: {payload}")
        print(f"Result:  {result}")
        if "<script" in result or "onerror" in result or "javascript:" in result:
             print(f"FAILED: {desc}")
        else:
             print(f"PASSED: {desc}")

if __name__ == "__main__":
    test_xss_vectors()
