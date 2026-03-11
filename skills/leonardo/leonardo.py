"""Leonardo AI skill

Provides a simple wrapper around the Leonardo image generation API.
The configuration is stored in ``skills/leonardo/config.yaml`` and can be
overridden at call time.

On Vercel (ephemeral filesystem), config is read from GitHub to get the latest
RANDOM_STYLES. On local dev, it reads from the local file.

Usage example::

    from skills.leonardo.leonardo import generate_image
    result = generate_image(prompt="A cyberpunk city at night")
    print(result)

The function returns the parsed JSON response from the API.  If the request
fails a ``RuntimeError`` is raised with the error details.
"""

import os
import yaml
import requests
from pathlib import Path
from typing import Dict, Any, Optional

# ---------------------------------------------------------------------------
# Helper to load configuration
# ---------------------------------------------------------------------------
CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

def _load_config() -> Dict[str, Any]:
    """Load the YAML configuration.

    On Vercel, tries to fetch from GitHub first (to get latest RANDOM_STYLES).
    Falls back to local file for local development.
    
    The configuration may contain the following keys:
        - ``API_KEY`` (required)
        - ``DEFAULT_PROMPT`` (optional)
        - ``IMAGE_WIDTH`` (optional, default 512)
        - ``IMAGE_HEIGHT`` (optional, default 512)
        - ``STYLE`` (optional)
        - ``RANDOM_STYLES`` (optional, list of style prompts)
    Environment variables ``LEONARDO_API_KEY`` etc. take precedence over the
    file values.
    """
    cfg: Dict[str, Any] = {}
    
    # Try GitHub first (for Vercel - ephemeral filesystem)
    try:
        from services.github import get_repo
        repo = get_repo()
        if repo:
            contents = repo.get_contents("skills/leonardo/config.yaml")
            cfg = yaml.safe_load(contents.decoded_content) or {}
            print("[LEONARDO] Loaded config from GitHub")
    except Exception as e:
        print(f"[LEONARDO] Could not load from GitHub: {e}")
        # Fall back to local file
        if CONFIG_PATH.is_file():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            print("[LEONARDO] Loaded config from local file")
    
    # If still no config and local file exists (fallback)
    if not cfg and CONFIG_PATH.is_file():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    
    # Override with environment variables if they exist
    cfg["API_KEY"] = os.getenv("LEONARDO_API_KEY", cfg.get("API_KEY"))
    cfg["DEFAULT_PROMPT"] = os.getenv(
        "LEONARDO_DEFAULT_PROMPT", cfg.get("DEFAULT_PROMPT", "A futuristic cityscape")
    )
    cfg["IMAGE_WIDTH"] = int(
        os.getenv("LEONARDO_IMAGE_WIDTH", cfg.get("IMAGE_WIDTH", 512))
    )
    cfg["IMAGE_HEIGHT"] = int(
        os.getenv("LEONARDO_IMAGE_HEIGHT", cfg.get("IMAGE_HEIGHT", 512))
    )
    cfg["STYLE"] = os.getenv("LEONARDO_STYLE", cfg.get("STYLE", "surreal"))
    cfg["MODEL_ID"] = os.getenv("LEONARDO_MODEL_ID", cfg.get("MODEL_ID", "1e60896f-3c26-4296-8ecc-53e2afecc132"))
    cfg["NEGATIVE_PROMPT"] = os.getenv("LEONARDO_NEGATIVE_PROMPT", cfg.get("NEGATIVE_PROMPT", "blurry, low quality, distorted, watermark"))
    return cfg

# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------
def generate_image(
    prompt: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    style: Optional[str] = None,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate an image with Leonardo AI.

    Parameters
    ----------
    prompt: str, optional
        Text prompt for the image. If omitted the ``DEFAULT_PROMPT`` from the
        configuration is used.
    width, height: int, optional
        Desired dimensions. Defaults come from the configuration.
    style: str, optional
        Optional style identifier supported by Leonardo.

    Returns
    -------
    dict
        Parsed JSON response from the Leonardo API.
    """
    cfg = _load_config()
    api_key = cfg.get("API_KEY")
    if not api_key:
        raise RuntimeError("Leonardo API key is not configured.")

    payload: Dict[str, Any] = {
        "prompt": prompt or cfg["DEFAULT_PROMPT"],
        "width": width or cfg["IMAGE_WIDTH"],
        "height": height or cfg["IMAGE_HEIGHT"],
        "negative_prompt": negative_prompt or cfg.get("NEGATIVE_PROMPT", "")
    }
    
    if cfg.get("MODEL_ID"):
        payload["modelId"] = cfg["MODEL_ID"]

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    # The official endpoint – adjust if your plan uses a different URL
    endpoint = os.getenv(
        "LEONARDO_API_ENDPOINT", "https://cloud.leonardo.ai/api/rest/v1/generations"
    )

    response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
    if response.status_code != 200:
        # Include the response body for easier debugging
        raise RuntimeError(
            f"Leonardo API error {response.status_code}: {response.text}"
        )
    return response.json()

# ---------------------------------------------------------------------------
# Simple CLI entry point – useful for quick manual tests
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Leonardo AI image generation")
    parser.add_argument("-p", "--prompt", help="Prompt text")
    parser.add_argument("-w", "--width", type=int, help="Image width")
    parser.add_argument("-t", "--height", type=int, help="Image height")
    parser.add_argument("-s", "--style", help="Style identifier")
    args = parser.parse_args()
    try:
        result = generate_image(
            prompt=args.prompt,
            width=args.width,
            height=args.height,
            style=args.style,
        )
        print("Success:")
        print(result)
    except Exception as e:
        print(f"Error: {e}")
