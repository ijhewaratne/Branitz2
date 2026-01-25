import os
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

def bootstrap_env():
    """
    Deterministically load .env file from the project root.
    Walks up from this file's location to find '.env'.
    
    Should be called at the very start of entrypoint scripts.
    """
    # Current file is in src/branitz_heat_decision/ui/env.py
    # We want to find .env in /Users/.../Branitz2/ (project root)
    
    # Start search from this file's parent
    current_path = Path(__file__).resolve()
    
    # Walk up parent directories
    # 0: ui/, 1: branitz_heat_decision/, 2: src/, 3: Project Root
    found = False
    for parent in current_path.parents:
        env_path = parent / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            logger.info(f"Loaded .env from {env_path}")
            found = True
            break
            
    if not found:
        logger.warning(f"No .env file found in parent directories of {current_path}")

    # Check for GOOGLE_API_KEY
    if not os.getenv("GOOGLE_API_KEY"):
         logger.warning("GOOGLE_API_KEY not found in environment. LLM features may be disabled.")
    else:
         logger.info("GOOGLE_API_KEY detected.")
