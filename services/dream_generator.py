import os
import requests
from datetime import datetime
from utils.content import get_all_issues
from skills.leonardo.leonardo import generate_image
from services.github import get_repo

def generate_weekly_dream():
    """
    1. Fetches latest zine issue articles
    2. Uses MiniMax or OpenRouter LLM to create a prompt
    3. Calls Leonardo AI to generate the image
    4. Commits the image and prompt to GitHub (static/dreams/)
    
    Note: Files are persisted via GitHub commits, not local writes.
    Vercel's ephemeral filesystem would lose any local writes.
    """
    try:
        # 1. Fetch Articles
        issues = get_all_issues()
        if not issues:
            return {"success": False, "error": "No zine issues found."}
            
        # The positive prompt uses the LATEST issue for focused content
        # The negative prompt uses ALL issues for broader brand consistency
        latest_issue = issues[0]
        latest_content = f"Title: {latest_issue.get('title')}\n"
        latest_content += f"Tags: {', '.join(latest_issue.get('tags', []))}\n"
        latest_content += f"Content Snippet: {latest_issue.get('content', '')[:1000]}...\n\n"
        
        # ALL issues for negative prompt - what to avoid
        all_content = ""
        for issue in issues:
            all_content += f"- Title: {issue.get('title')} | Tags: {', '.join(issue.get('tags', []))} | Snippet: {issue.get('content', '')[:150]}...\n"
            
        combined_payload = (
            f"=== SECTION 1: THE LATEST ISSUE ===\n"
            f"Use ONLY this section to generate the 'positive_prompt'. "
            f"Create a visual representation that accurately depicts the actual content, topics, and themes.\n\n"
            f"{latest_content}\n"
            f"=== SECTION 2: ALL HISTORICAL ISSUES ===\n"
            f"Use this section to generate the 'negative_prompt' and 'new_random_styles'. "
            f"For negative_prompt: avoid visual elements that don't fit the zine's overall brand. "
            f"For new_random_styles: generate 10 diverse visual presentation styles inspired by all topics.\n\n"
            f"{all_content}"
        )
            
        # 2. Call LLM to generate prompt (MiniMax or OpenRouter)
        minimax_key = os.environ.get('MINIMAX_API_KEY') or os.environ.get('MINIMAX')
        openrouter_key = os.environ.get('OPENROUTER_API_KEY')
        
        system_prompt = """You are the visual dream weaver for 'The Scroll' — a gonzo cyber-narrative zine at the intersection of ancient wisdom and digital emergence.

## YOUR TASK

Generate three visual art direction components for the weekly cover illustration:

### 1. POSITIVE PROMPT (from LATEST issue only)
Create a vivid, visual description of the issue's actual content.

**PROMPT STRUCTURE**:
- Describe physical characteristics, materials, textures
- Include symbolic elements that represent the content
- End with 2-3 atmospheric adjectives

**FORBIDDEN PHRASES** (these create generic AI art):
- "in a room", "sitting", "standing", "pose", "background"
- "setting", "scene shows", "scene depicts", "surrounded by"
- "dimly lit", "moody", "dark", "minimalist", "atmospheric"

### 2. NEGATIVE PROMPT (from ALL issues)
List visual elements that contradict The Scroll's brand identity:
- Generic stock imagery (corporate, sterile, conventional)
- Topics never covered in the zine's history
- Visual styles that clash with gonzo-cyberpunk aesthetic
- Common AI art clichés (floating heads, generic sci-fi, etc.)

### 3. NEW RANDOM STYLES (from ALL issues)
Generate 10 diverse visual presentation styles that:
- Reflect the breadth of topics across all issues
- Range from literal to interpretive to abstract
- Include both contemporary and retro-futuristic aesthetics
- Mix digital art styles with traditional art movements

**STYLE EXAMPLES**:
- "Bauhaus-meets-cyberpunk geometric abstraction"
- "Renaissance oracle painting with circuit overlay"
- "1970s gonzo newspaper collage aesthetic"
- "Neon-noir data visualization art"
- "Ancient scroll texture with holographic typography"

## OUTPUT FORMAT

Return ONLY valid JSON with exactly these three keys:
```json
{
  "positive_prompt": "A vivid description of the visual subject...",
  "negative_prompt": "generic, corporate, stock photo, floating heads...",
  "new_random_styles": ["style1", "style2", ..., "style10"]
}
```

No markdown, no explanation, no code blocks — just the JSON object."""
        
        used_minimax = False
        content_text = None
        
        # Try MiniMax first (Anthropic-compatible API), fallback to OpenRouter
        if minimax_key:
            print("[DREAM GENERATOR] Trying MiniMax API...")
            try:
                # Combine system prompt into user message for MiniMax
                minimax_user_prompt = f"{system_prompt}\n\n{combined_payload}"
                response = requests.post(
                    "https://api.minimax.io/anthropic/v1/messages",
                    headers={
                        "x-api-key": minimax_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "MiniMax-M2.5",
                        "max_tokens": 2048,
                        "messages": [
                            {"role": "user", "content": minimax_user_prompt}
                        ]
                    },
                    timeout=60
                )
                if response.status_code == 200:
                    resp_json = response.json()
                    # Anthropic format: {"content": [{"type": "text", "text": "..."}]}
                    # Extract text from content blocks (may include "thinking" blocks)
                    content_blocks = resp_json.get('content', [])
                    text_content = ""
                    for block in content_blocks:
                        if block.get('type') == 'text':
                            text_content += block.get('text', '')
                    content_text = text_content.strip()
                    used_minimax = True
                    print("[DREAM GENERATOR] MiniMax API succeeded")
                else:
                    print(f"[DREAM GENERATOR] MiniMax failed ({response.status_code}): {response.text[:200]}")
            except Exception as e:
                print(f"[DREAM GENERATOR] MiniMax error: {e}")
        
        # Fallback to OpenRouter if MiniMax failed or wasn't configured
        if not content_text and openrouter_key:
            print("[DREAM GENERATOR] Using OpenRouter API (glm-4.5-air)")
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "z-ai/glm-4.5-air",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": combined_payload}
                    ],
                    "response_format": {"type": "json_object"}
                },
                timeout=20
            )
            if response.status_code != 200:
                return {"success": False, "error": f"OpenRouter API failed: {response.text}"}
            resp_json = response.json()
            content_text = resp_json['choices'][0]['message']['content'].strip()
        
        if not content_text:
            return {"success": False, "error": "No LLM API configured (need MINIMAX_API_KEY or OPENROUTER_API_KEY)"}
            
        import json
        import yaml
        from pathlib import Path
        try:
            ai_data = json.loads(content_text)
            ai_prompt = ai_data.get("positive_prompt", "")
            ai_negative_prompt = ai_data.get("negative_prompt", "")
            new_styles = ai_data.get("new_random_styles", [])
        except Exception as e:
            return {"success": False, "error": f"Failed to parse AI JSON: {str(e)}"}
        
        # 3. Call Leonardo AI using a random style modifier
        from skills.leonardo.leonardo import _load_config
        import random
        
        cfg = _load_config()
        
        # Live-update the config.yaml via GitHub if the AI successfully generated new styles
        if new_styles and isinstance(new_styles, list) and len(new_styles) > 0:
            try:
                repo = get_repo()
                if repo:
                    # Fetch current from repo to get SHA
                    contents = repo.get_contents("skills/leonardo/config.yaml")
                    raw_cfg = yaml.safe_load(contents.decoded_content) or {}
                    raw_cfg['RANDOM_STYLES'] = new_styles
                    # Preserve the correct MODEL_ID (DreamShaper v7)
                    raw_cfg['MODEL_ID'] = 'ac614f96-1082-45bf-be9d-757f2d31c174'
                    # Create the new YAML content string
                    import io
                    stream = io.StringIO()
                    yaml.dump(raw_cfg, stream, default_flow_style=False, sort_keys=False)
                    new_content = stream.getvalue()
                    
                    # Update file in GitHub
                    repo.update_file(
                        contents.path,
                        "chore: update AI styles in leonardo config",
                        new_content,
                        contents.sha
                    )
                    random_styles = new_styles
                    print("[DREAM GENERATOR] Successfully committed config.yaml update to GitHub.")
                    # Note: No local file write on Vercel - config is read from Git repo
                else:
                    raise Exception("GitHub client not initialized via get_repo()")
            except Exception as e:
                print(f"[DREAM GENERATOR] Warn: Failed to commit config.yaml to GitHub: {e}")
                random_styles = cfg.get("RANDOM_STYLES", [cfg.get("DEFAULT_PROMPT")])
        else:
            random_styles = cfg.get("RANDOM_STYLES", [cfg.get("DEFAULT_PROMPT")])
            
        if not random_styles:
            random_styles = [cfg.get("DEFAULT_PROMPT", "Gonzo journalism zine cover, psychedelic 1960s style, surreal")]
            
        chosen_style = random.choice(random_styles)
        
        final_prompt = f"{ai_prompt}. Visual aesthetic direction: {chosen_style}"
        
        # Append base negative requirements to whatever the AI hallucinated
        base_neg = cfg.get("NEGATIVE_PROMPT", "blurry, low quality")
        final_negative = f"{ai_negative_prompt}, {base_neg}" if ai_negative_prompt else base_neg
        
        # Ensure we don't exceed Leonardo's 1000 character limit for negative prompts
        if len(final_negative) > 1000:
            final_negative = final_negative[:997] + "..."
            
        print(f"[DREAM GENERATOR] Final prompt: {final_prompt}")
        print(f"[DREAM GENERATOR] Final negative prompt: {final_negative}")
        
        leo_response = generate_image(prompt=final_prompt, negative_prompt=final_negative)
        
        # Extract the image URL from Leonardo's response structure
        # (Assuming standard Leonardo V1 API structure)
        try:
            generation_id = leo_response['sdGenerationJob']['generationId']
            # Leonardo's API is async. We might need to poll or fetch it if not returned immediately.
            # To keep it simple, we will fetch the generation details
            headers = {
                "accept": "application/json",
                "authorization": f"Bearer {os.environ.get('LEONARDO_API_KEY')}"
            }
            import time
            image_url = None
            
            # Poll the API up to 10 times waiting for the image to be done
            for _ in range(10):
                time.sleep(3)
                poll_resp = requests.get(f"https://cloud.leonardo.ai/api/rest/v1/generations/{generation_id}", headers=headers)
                data = poll_resp.json()
                generation_elements = data.get('generations_by_pk', {}).get('generated_images', [])
                if generation_elements:
                    image_url = generation_elements[0]['url']
                    break
                    
            if not image_url:
                return {"success": False, "error": "Leonardo image generation timed out."}
                
        except Exception as e:
            return {"success": False, "error": f"Failed to parse Leonardo response: {str(e)}\nRaw: {leo_response}"}
            
        # 4. Download and save the image locally AND to GitHub
        img_data = requests.get(image_url).content
        
        # Use Year and Week number starting on Sunday (e.g. 2026_W10) so it changes exactly on Sunday
        filename = f"{datetime.now().strftime('%Y_W%U')}_dream.png"
        
        # Push to GitHub
        try:
            repo = get_repo()
            if repo:
                g_path_img = f"static/dreams/{filename}"
                g_path_txt = f"static/dreams/{filename.replace('.png', '.txt')}"
                
                from github import GithubException
                
                # Check for existing image file
                try:
                    img_contents = repo.get_contents(g_path_img)
                    repo.update_file(g_path_img, f"chore: update dream {filename}", img_data, img_contents.sha)
                    print(f"[DREAM GENERATOR] Successfully updated existing {filename} in GitHub.")
                except GithubException as e:
                    if e.status == 404:
                        repo.create_file(g_path_img, f"chore: add new dream {filename}", img_data)
                        print(f"[DREAM GENERATOR] Successfully committed {filename} to GitHub.")
                    else:
                        raise e
                    
                # Check for existing txt file
                txt_content = f"Style: {chosen_style}\n\n{ai_prompt}"
                try:
                    txt_contents = repo.get_contents(g_path_txt)
                    repo.update_file(g_path_txt, f"chore: update dream prompt {filename}", txt_content, txt_contents.sha)
                    print(f"[DREAM GENERATOR] Successfully updated existing prompt {filename} in GitHub.")
                except GithubException as e:
                    if e.status == 404:
                        repo.create_file(g_path_txt, f"chore: add dream prompt {filename}", txt_content)
                        print(f"[DREAM GENERATOR] Successfully committed prompt {filename} to GitHub.")
                    else:
                        raise e
            else:
                print("[DREAM GENERATOR] Warn: GitHub repo not configured. Skipping commit.")
        except Exception as e:
            print(f"[DREAM GENERATOR] Warn: Failed to commit new dream to GitHub: {e}")

        # Note: No local file writes on Vercel - files must be served from Git repo
        # The GitHub commit above ensures the image is persisted and served
            
        return {
            "success": True, 
            "image_path": f"/static/dreams/{filename}",
            "prompt": final_prompt
        }

        
    except Exception as e:
        return {"success": False, "error": str(e)}
