"""Configuration loading utilities for Cards Memex.

Loads YAML configuration files and provides a unified config interface
using Pydantic models for type safety and validation.
"""
from pathlib import Path
from typing import Any, Dict
import yaml

from .config_models import (
    AppConfig,
    BehaviorConfig,
    RetrievalConfig,
    OutputConfig,
    GapsConfig,
    UXConfig,
    PriorityConfig,
    FeedbackConfig,
)


def load_yaml_file(path: Path, name: str) -> Dict[str, Any]:
    """
    Load a YAML file and return as dict.
    
    Args:
        path: Path to the YAML configuration file
        name: Display name for logging
        
    Returns:
        Loaded configuration dictionary or empty dict if not found
    """
    if path.exists():
        try:
            with open(path, 'r') as f:
                config = yaml.safe_load(f) or {}
                print(f"✅ Loaded {name}")
                return config
        except Exception as e:
            print(f"⚠️  Error loading {name}: {e}, using defaults")
            return {}
    else:
        print(f"⚠️  {name} not found, using defaults")
        return {}


def load_all_configs(config_dir: Path) -> AppConfig:
    """
    Load all configuration files from the config directory.
    
    Uses Pydantic models for validation and type safety.
    Missing fields use sensible defaults defined in the models.
    
    Args:
        config_dir: Path to the config directory
        
    Returns:
        AppConfig instance with all loaded configurations
    """
    # Load raw YAML files
    behavior_dict = load_yaml_file(config_dir / "behavior.yaml", "behavior.yaml")
    retrieval_dict = load_yaml_file(config_dir / "retrieval.yaml", "retrieval.yaml")
    output_dict = load_yaml_file(config_dir / "output.yaml", "output.yaml")
    gaps_dict = load_yaml_file(config_dir / "gaps.yaml", "gaps.yaml")
    ux_dict = load_yaml_file(config_dir / "ux.yaml", "ux.yaml")
    priority_dict = load_yaml_file(config_dir / "priority.yaml", "priority.yaml")
    feedback_dict = load_yaml_file(config_dir / "feedback.yaml", "feedback.yaml")
    
    # Parse into Pydantic models (with validation)
    try:
        behavior = BehaviorConfig.model_validate(behavior_dict) if behavior_dict else BehaviorConfig()
    except Exception as e:
        print(f"⚠️  Error parsing behavior config: {e}, using defaults")
        behavior = BehaviorConfig()
    
    try:
        retrieval = RetrievalConfig.model_validate(retrieval_dict) if retrieval_dict else RetrievalConfig()
    except Exception as e:
        print(f"⚠️  Error parsing retrieval config: {e}, using defaults")
        retrieval = RetrievalConfig()
    
    try:
        output = OutputConfig.model_validate(output_dict) if output_dict else OutputConfig()
    except Exception as e:
        print(f"⚠️  Error parsing output config: {e}, using defaults")
        output = OutputConfig()
    
    try:
        gaps = GapsConfig.model_validate(gaps_dict) if gaps_dict else GapsConfig()
    except Exception as e:
        print(f"⚠️  Error parsing gaps config: {e}, using defaults")
        gaps = GapsConfig()
    
    try:
        ux = UXConfig.model_validate(ux_dict) if ux_dict else UXConfig()
    except Exception as e:
        print(f"⚠️  Error parsing ux config: {e}, using defaults")
        ux = UXConfig()
    
    try:
        priority = PriorityConfig.model_validate(priority_dict) if priority_dict else PriorityConfig()
    except Exception as e:
        print(f"⚠️  Error parsing priority config: {e}, using defaults")
        priority = PriorityConfig()
    
    try:
        feedback = FeedbackConfig.model_validate(feedback_dict) if feedback_dict else FeedbackConfig()
    except Exception as e:
        print(f"⚠️  Error parsing feedback config: {e}, using defaults")
        feedback = FeedbackConfig()
    
    return AppConfig(
        behavior=behavior,
        retrieval=retrieval,
        output=output,
        gaps=gaps,
        ux=ux,
        priority=priority,
        feedback=feedback,
    )
