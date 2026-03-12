"""
Prompts module for memex-core.
Provides externalized prompt templates using Jinja2 for easy iteration.

Supports app-level prompt overrides: if an app provides a prompts directory,
templates there take precedence over library defaults.

Usage:
    from memex_core.prompts import load_prompt, render_prompt, set_app_prompts_dir
    
    # Set app-level prompts directory (optional)
    set_app_prompts_dir("/path/to/app/config/prompts")
    
    # Load a prompt template (checks app dir first, then library)
    template = load_prompt("classify")
    
    # Render with variables
    prompt = template.render(
        thread_text=thread_text,
        role_definition=role_def_str,
        similar_examples=examples
    )
"""

from pathlib import Path
from typing import Optional, Dict, Any, List

from jinja2 import Environment, FileSystemLoader, Template, TemplateNotFound, ChoiceLoader


# Directory containing library prompt templates
_LIBRARY_PROMPTS_DIR = Path(__file__).parent

# App-level prompts directory (set by app at runtime)
_app_prompts_dir: Optional[Path] = None


def set_app_prompts_dir(prompts_dir: str) -> None:
    """
    Set the app-level prompts directory for template overrides.
    
    Templates in this directory take precedence over library defaults.
    Call this once during app initialization before loading any prompts.
    
    Args:
        prompts_dir: Path to the app's prompts directory
    """
    global _app_prompts_dir
    path = Path(prompts_dir)
    if path.exists() and path.is_dir():
        _app_prompts_dir = path
        print(f"✅ App prompts directory set: {prompts_dir}")
    else:
        print(f"⚠️  App prompts directory not found: {prompts_dir}")
        _app_prompts_dir = None


def _get_jinja_env() -> Environment:
    """
    Get the Jinja2 environment configured for prompt templates.
    
    Uses a ChoiceLoader that checks app-level prompts first,
    then falls back to library prompts.
    
    Returns:
        Configured Jinja2 Environment
    """
    loaders = []
    
    # App-level prompts take precedence
    if _app_prompts_dir and _app_prompts_dir.exists():
        loaders.append(FileSystemLoader(str(_app_prompts_dir)))
    
    # Library prompts as fallback
    loaders.append(FileSystemLoader(str(_LIBRARY_PROMPTS_DIR)))
    
    return Environment(
        loader=ChoiceLoader(loaders),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True
    )


def load_prompt(template_name: str) -> Template:
    """
    Load a prompt template by name.
    
    Checks app-level prompts directory first, then falls back to library.
    
    Args:
        template_name: Name of the template (without .jinja2 extension)
        
    Returns:
        Jinja2 Template object
        
    Raises:
        TemplateNotFound: If template doesn't exist in either location
    """
    env = _get_jinja_env()
    return env.get_template(f"{template_name}.jinja2")


def render_prompt(template_name: str, **kwargs) -> str:
    """
    Load and render a prompt template in one call.
    
    Args:
        template_name: Name of the template (without .jinja2 extension)
        **kwargs: Variables to pass to the template
        
    Returns:
        Rendered prompt string
    """
    template = load_prompt(template_name)
    return template.render(**kwargs)


def list_available_prompts() -> Dict[str, List[str]]:
    """
    List all available prompt templates from both app and library.
    
    Returns:
        Dict with 'app' and 'library' keys containing template names
    """
    result = {
        "app": [],
        "library": []
    }
    
    # List library prompts
    result["library"] = [
        f.stem for f in _LIBRARY_PROMPTS_DIR.glob("*.jinja2")
    ]
    
    # List app prompts
    if _app_prompts_dir and _app_prompts_dir.exists():
        result["app"] = [
            f.stem for f in _app_prompts_dir.glob("*.jinja2")
        ]
    
    return result


def get_prompt_source(template_name: str) -> str:
    """
    Get the source (app or library) for a given template.
    
    Useful for debugging which template is being used.
    
    Args:
        template_name: Name of the template (without .jinja2 extension)
        
    Returns:
        "app", "library", or "not_found"
    """
    # Check app first
    if _app_prompts_dir:
        app_path = _app_prompts_dir / f"{template_name}.jinja2"
        if app_path.exists():
            return "app"
    
    # Check library
    lib_path = _LIBRARY_PROMPTS_DIR / f"{template_name}.jinja2"
    if lib_path.exists():
        return "library"
    
    return "not_found"
