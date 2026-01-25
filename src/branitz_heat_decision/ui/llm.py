import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import google.generativeai as genai
import json
from .services import JobService
from .registry import SCENARIO_REGISTRY


logger = logging.getLogger(__name__)


# Environment is assumed to be loaded by the entrypoint (app.py or scripts) via bootstrap_env()

KEYWORD_ALIASES = {

    "cha": ["district heat", "dh", "network", "cha", "pipeline", "district heating"],
    "dha": ["heat pump", "hp", "grid", "electricity", "dha", "power"],
    "economics": ["cost", "price", "lcoh", "money", "expensive", "economics", "euro"],
    "decision": ["decide", "compare", "recommend", "best", "decision", "feasibility"],
    "uhdc": ["report", "summary", "explain", "uhdc"]
}


class LLMRouter:
    def __init__(self, job_service: JobService):
        self.job_service = job_service
        self.api_key = os.environ.get("GOOGLE_API_KEY")
        self.model = None
        
        if self.api_key:
            genai.configure(api_key=self.api_key)
            # Use a fast model for routing
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        else:
            logger.warning("GOOGLE_API_KEY not found. LLM Router will use keyword fallback.")

    def route_intent(self, prompt: str, cluster_id: str) -> Dict[str, Any]:
        """
        Interpret user prompt and determine plan.
        Returns dict with keys: 'plan' (list of steps), 'message'.
        """
        if not cluster_id:
            return {"plan": [], "message": "Please select a street cluster first."}

        # 1. Try LLM first
        llm_response = None
        if self.model:
            try:
                llm_response = self._query_llm(prompt, cluster_id)
                # If LLM returned a valid plan with steps, use it
                if llm_response and llm_response.get("plan"):
                    return llm_response
                # Otherwise, fall through to keyword fallback
            except Exception as e:
                logger.error(f"LLM routing failed: {e}")
                # Fall through to keyword fallback
                
        # 2. Keyword Fallback (simple plan generation)
        # This runs if LLM is unavailable, returned empty plan, or failed
        plan = []
        prompt_low = prompt.lower()
        
        # Check against registry aliases
        for key, aliases in KEYWORD_ALIASES.items():
            for alias in aliases:
                if alias in prompt_low:
                     # Avoid duplicates
                     if not any(step['tool'] == key for step in plan):
                         plan.append({"tool": key, "reason": f"Keyword '{alias}' detected"})
                     break

        
        if plan:
             return {"plan": plan, "message": f"I detected keywords for these actions. Shall we proceed?"}
        
        # 3. Final fallback: use LLM message if available, otherwise generic message
        if llm_response and llm_response.get("message"):
            return llm_response
            
        return {"plan": [], "message": "I didn't understand. I can help you plan simulations like CHA, DHA, or Economics."}


    def _query_llm(self, prompt: str, cluster_id: str) -> Dict[str, Any]:
        """
        Ask LLM to generate a plan.
        """
        # Build tools description
        tools_desc = "\n".join([f"- {key}: {val['title']} ({val['description']})" for key, val in SCENARIO_REGISTRY.items()])
        
        system_prompt = f"""
        You are an expert municipal planner assistant for the Branitz Heat Decision system.
        The user is asking about street cluster: {cluster_id}.
        
        Your Goal: Understand the user's intent and propose a PLAN of actions.
        
        Available Tools (Allowlist):
        {tools_desc}
        
        GUARDRAILS:
        1. You CANNOT make decisions yourself. You can only propose running the 'decision' tool.
        2. You CANNOT invent new tools. Only proper IDs from the list allowed.
        3. Explain your plan clearly to a non-technical municipal user.
        
        Output JSON ONLY:
        {{
            "plan": [
                {{"tool": "cha", "reason": "To check hydraulic feasibility..."}},
                {{"tool": "economics", "reason": "To estimate costs..."}}
            ],
            "message": "I recommend running the technical feasibility checks first..."
        }}
        
        If no tool is needed (just valid chit-chat), return empty "plan": [].
        """
        
        response = self.model.generate_content(f"{system_prompt}\nUser: {prompt}")
        text = response.text
        
        # Clean markdown code blocks if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
            
        try:
            return json.loads(text.strip())
        except:
            return {"plan": [], "message": f"I couldn't process that request properly. Raw: {text[:50]}..."}
