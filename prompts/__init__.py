# prompts/__init__.py
from prompts.manager import Prompt, PromptManager, PromptNotFoundError

__all__ = ["Prompt", "PromptManager", "PromptNotFoundError"]