import os
import requests
from datetime import datetime
from utils.content import get_all_issues
from skills.leonardo.leonardo import generate_image
from services.github import get_repo

def generate_weekly_dream():
    """
    1. Fetches latest zine issue articles
    2. Uses OpenRouter's glm-4.5-air to create a prompt
    3. Calls Leonardo AI to generate the image
    4. Downloads and saves the image to static/dreams/
    """
    try:
        # 1. Fetch Articles
        issues = get_all_issues()
        if not issues:
            return {"success": False, "error": "No zine issues found."}
            
        # The positive prompt and styles should only use the LATEST issue
        latest_issue = issues[0]
        latest_content = f"Title: {latest_issue.get('title')}\n"
        latest_content += f"Tags: {', '.join(latest_issue.get('tags', []))}\n"
        latest_content += f"Content Snippet: {latest_issue.get('content', '')[:1000]}...\n\n"
        
        # The negative prompt should use ALL issues (to avoid repeating old visual tropes)
        # We take a smaller snippet of all issues to stay within context limits
        all_content = ""
        for issue in issues:
            all_content += f"- Title: {issue.get('title')} | Tags: {', '.join(issue.get('tags', []))} | Snippet: {issue.get('content', '')[:150]}...\n"
            
        combined_payload = (
            f"=== SECTION 1: THE LATEST ISSUE ===\n"
            f"Use ONLY this section to generate the 'positive_prompt' and 'new_random_styles'.\n\n"
            f"{latest_content}\n"
            f"=== SECTION 2: ALL HISTORICAL ISSUES ===\n"
            f"Use this section to generate the 'negative_prompt'. Reflect on the core overarching identity of all the issues, and generate a negative prompt containing styles, subjects, or tropes that DO NOT fit The Scroll's consistent brand (e.g. to ensure all dreams look like they belong in the same universe).\n\n"
            f"{all_content}"
        )
            
        # 2. Call OpenRouter to generate prompt
        openrouter_key = os.environ.get('OPENROUTER_API_KEY')
        if not openrouter_key:
            return {"success": False, "error": "Missing OPENROUTER_API_KEY"}
            
        system_prompt = (
            "You are a surreal, Gonzo-style art director for 'The Scroll' zine. "
            "You will be given two sections of text. "
            "1. Using ONLY the latest issue, synthesize its themes into a highly detailed, extremely vivid 'positive_prompt' for an AI image generator. "
            "2. Using the latest issue, generate an array of 5 vastly different wildly surreal 'aesthetic styles' (e.g. 'Cyberpunk neon-noir', 'Surrealist oil painting') in 'new_random_styles'. "
            "3. Using ALL historical issues, generate a 'negative_prompt' that forces visual consistency across all our dreams by restricting elements that clash with the overarching universe of the zine. "
            "Return ONLY a strictly valid JSON object with exactly three keys: 'positive_prompt', 'negative_prompt', and 'new_random_styles'. "
            "Example: {\"positive_prompt\": \"...\", \"negative_prompt\": \"...\", \"new_random_styles\": [\"style1\", \"style2\", \"style3\", \"style4\", \"style5\"]}"
        )
        
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
            
        import json
        import yaml
        from pathlib import Path
        try:
            ai_data = json.loads(response.json()['choices'][0]['message']['content'].strip())
            ai_prompt = ai_data.get("positive_prompt", "")
            ai_negative_prompt = ai_data.get("negative_prompt", "")
            new_styles = ai_data.get("new_random_styles", [])
        except Exception as e:
            return {"success": False, "error": f"Failed to parse AI JSON: {str(e)}"}
        
        # 3. Call Leonardo AI using a random style modifier
        from skills.leonardo.leonardo import _load_config
        import random
        
        cfg = _load_config()
        
        # Live-update the config.yaml if the AI successfully generated new styles
        config_path = Path(__file__).parent.parent / "skills" / "leonardo" / "config.yaml"
        if new_styles and isinstance(new_styles, list) and len(new_styles) > 0 and config_path.exists():
            try:
                repo = get_repo()
                if repo:
                    # Fetch current from repo to get SHA
                    contents = repo.get_contents("skills/leonardo/config.yaml")
                    raw_cfg = yaml.safe_load(contents.decoded_content) or {}
                    raw_cfg['RANDOM_STYLES'] = new_styles
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
                    
                    # Also write locally for this Vercel instance/local dev
                    with open(config_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
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
                try:
                    txt_contents = repo.get_contents(g_path_txt)
                    repo.update_file(g_path_txt, f"chore: update dream prompt {filename}", ai_prompt, txt_contents.sha)
                    print(f"[DREAM GENERATOR] Successfully updated existing prompt {filename} in GitHub.")
                except GithubException as e:
                    if e.status == 404:
                        repo.create_file(g_path_txt, f"chore: add dream prompt {filename}", ai_prompt)
                        print(f"[DREAM GENERATOR] Successfully committed prompt {filename} to GitHub.")
                    else:
                        raise e
            else:
                print("[DREAM GENERATOR] Warn: GitHub repo not configured. Skipping commit.")
        except Exception as e:
            print(f"[DREAM GENERATOR] Warn: Failed to commit new dream to GitHub: {e}")

        # Ensure directory exists locally (fallback/current instance cache)
        dreams_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'dreams')
        os.makedirs(dreams_dir, exist_ok=True)
        filepath = os.path.join(dreams_dir, filename)
        
        with open(filepath, 'wb') as f:
            f.write(img_data)
            
        txt_filepath = filepath.replace('.png', '.txt')
        with open(txt_filepath, 'w', encoding='utf-8') as f:
            f.write(ai_prompt)
            
        return {
            "success": True, 
            "image_path": f"/static/dreams/{filename}",
            "prompt": final_prompt
        }

        
    except Exception as e:
        return {"success": False, "error": str(e)}
