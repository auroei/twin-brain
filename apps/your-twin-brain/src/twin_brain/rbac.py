"""Role-Based Access Control (RBAC) for twin-brain.

Three-role system:
- CURATOR_IDS: Admins who can tag threads + Q&A + weighted feedback (5x default) + L2 reinforcement
- TEACHER_IDS: Can Q&A + weighted feedback (5x default) + L2 reinforcement (no tagging)
- Users: Everyone else can Q&A + logged feedback (1x weight, no L2 reinforcement)

Feedback weights are configurable in config/feedback.yaml under the 'weights' section.
"""
import os
import sys


def load_rbac_config():
    """
    Load and parse RBAC configuration from environment variables.
    
    Returns:
        Tuple of (curator_ids: set, teacher_ids: set)
        
    Raises:
        SystemExit if CURATOR_IDS is not configured.
    """
    curator_ids_str = os.environ.get("CURATOR_IDS", "").strip()
    teacher_ids_str = os.environ.get("TEACHER_IDS", "").strip()
    
    # Parse CURATOR_IDS (required)
    if not curator_ids_str:
        print("❌ CRITICAL SECURITY ERROR: CURATOR_IDS not set in .env file")
        print("   The bot requires at least one curator for security.")
        print("   Please add CURATOR_IDS=U1234567890,U0987654321 to your .env file")
        sys.exit(1)
    
    curator_ids = set(
        user_id.strip() 
        for user_id in curator_ids_str.split(",") 
        if user_id.strip()
    )
    
    if not curator_ids:
        print("❌ CRITICAL SECURITY ERROR: CURATOR_IDS is empty or invalid")
        print("   Please add at least one curator ID to CURATOR_IDS in your .env file")
        sys.exit(1)
    
    # Parse TEACHER_IDS (optional)
    teacher_ids = set()
    if teacher_ids_str:
        teacher_ids = set(
            user_id.strip() 
            for user_id in teacher_ids_str.split(",") 
            if user_id.strip()
        )
        print(f"👨‍🏫 Teachers configured: {len(teacher_ids)} user(s)")
    else:
        print("👨‍🏫 Teachers: None configured (optional)")
    
    print(f"🔒 Curators configured: {len(curator_ids)} user(s)")
    print("🔓 Q&A access: Open (anyone on Slack can DM)")
    
    return curator_ids, teacher_ids


def get_user_role(user_id: str, curator_ids: set, teacher_ids: set) -> str:
    """
    Get the role of a user for RBAC.
    
    Three-role hierarchy:
    - curator: Can tag threads + Q&A + 5x weighted feedback + L2 reinforcement
    - teacher: Can Q&A + 5x weighted feedback + L2 reinforcement (no tagging)
    - user: Can Q&A + logged feedback only (no L2 reinforcement)
    
    Args:
        user_id: The Slack user ID
        curator_ids: Set of curator user IDs
        teacher_ids: Set of teacher user IDs
        
    Returns:
        'curator', 'teacher', or 'user'
    """
    if user_id in curator_ids:
        return "curator"
    if user_id in teacher_ids:
        return "teacher"
    return "user"


def can_give_weighted_feedback(user_id: str, curator_ids: set, teacher_ids: set) -> bool:
    """
    Check if user can give weighted feedback (curators and teachers only).
    
    Args:
        user_id: The Slack user ID
        curator_ids: Set of curator user IDs
        teacher_ids: Set of teacher user IDs
        
    Returns:
        True if user is a curator or teacher
    """
    role = get_user_role(user_id, curator_ids, teacher_ids)
    return role in ("curator", "teacher")

