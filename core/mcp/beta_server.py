#!/usr/bin/env python3
"""
MCP Server for Dex Beta Features System

Provides tools for:
- Beta code validation and activation
- Feature status checking
- Feedback submission
- Beta feature management

Security:
- Activation codes are hashed with SHA-256
- Salted hashes prevent rainbow table attacks
- No codes stored in plain text
"""

import os
import sys
import json
import logging
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, date

try:
    import yaml
except ImportError:
    yaml = None

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Custom JSON encoder for handling date/datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


# Configuration - Vault paths
BASE_DIR = Path(os.environ.get('VAULT_PATH', Path.cwd()))
BETA_FEATURES_FILE = BASE_DIR / '.claude' / 'config' / 'beta-features.yaml'
BETA_TEMPLATES_DIR = BASE_DIR / '.claude' / 'reference' / 'beta-templates'
USER_PROFILE_FILE = BASE_DIR / 'System' / 'user-profile.yaml'


def setup_pi_integration() -> bool:
    """Set up Pi integration when activated - creates .pi/ folder, installs Pi, and documentation"""
    import subprocess

    try:
        # Check if Pi is already installed
        pi_installed = False
        try:
            result = subprocess.run(['pi', '--version'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                pi_installed = True
                logger.info(f"Pi already installed: {result.stdout.strip()}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Install Pi via npm if not present
        if not pi_installed:
            logger.info("Installing Pi via npm...")
            try:
                result = subprocess.run(
                    ['npm', 'install', '-g', '@mariozechner/pi-coding-agent'],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if result.returncode == 0:
                    logger.info("Pi installed successfully")
                else:
                    logger.warning(f"Pi installation may have issues: {result.stderr}")
            except Exception as e:
                logger.warning(f"Could not auto-install Pi: {e}. User may need to install manually.")

        # Create .pi directory structure
        pi_dir = BASE_DIR / '.pi'
        (pi_dir / 'extensions').mkdir(parents=True, exist_ok=True)
        (pi_dir / 'skills').mkdir(parents=True, exist_ok=True)
        (pi_dir / 'prompts').mkdir(parents=True, exist_ok=True)

        # Copy AGENTS.md if template exists
        agents_template = BETA_TEMPLATES_DIR / 'pi' / 'AGENTS.md'
        agents_dest = pi_dir / 'AGENTS.md'
        if agents_template.exists() and not agents_dest.exists():
            import shutil
            shutil.copy(agents_template, agents_dest)
        elif not agents_dest.exists():
            # Create minimal AGENTS.md if no template
            agents_dest.write_text("""# Dex Context for Pi

You are working in a Dex vault - a personal knowledge management system.

## Key Paths
- Tasks: 03-Tasks/Tasks.md
- People: 05-Areas/People/
- Projects: 04-Projects/
- Inbox: 00-Inbox/

## Important
- Use the dex-mcp-bridge extension for task and calendar operations
- Preserve existing file formats and conventions
""")

        # Copy MCP bridge extension if template exists
        bridge_template = BETA_TEMPLATES_DIR / 'pi' / 'dex-mcp-bridge.ts'
        bridge_dest = pi_dir / 'extensions' / 'dex-mcp-bridge.ts'
        if bridge_template.exists() and not bridge_dest.exists():
            import shutil
            shutil.copy(bridge_template, bridge_dest)

        # Create System/Beta/pi/ with documentation
        beta_dir = BASE_DIR / 'System' / 'Beta' / 'pi'
        beta_dir.mkdir(parents=True, exist_ok=True)

        # Copy documentation templates
        for doc_file in ['README.md', 'changelog.md', 'troubleshooting.md', 'examples.md']:
            template = BETA_TEMPLATES_DIR / 'pi' / doc_file
            dest = beta_dir / doc_file
            if template.exists() and not dest.exists():
                import shutil
                shutil.copy(template, dest)

        # Copy Pi-related skills to user's skills folder
        skills_template_dir = BETA_TEMPLATES_DIR / 'pi' / 'skills'
        skills_dest_dir = BASE_DIR / '.claude' / 'skills'
        if skills_template_dir.exists():
            import shutil
            for skill_dir in skills_template_dir.iterdir():
                if skill_dir.is_dir():
                    dest_skill_dir = skills_dest_dir / skill_dir.name
                    if not dest_skill_dir.exists():
                        shutil.copytree(skill_dir, dest_skill_dir)
                        logger.info(f"Copied Pi skill: {skill_dir.name}")

        # Copy Pi-related hooks to user's hooks folder
        hooks_template_dir = BETA_TEMPLATES_DIR / 'pi' / 'hooks'
        hooks_dest_dir = BASE_DIR / '.claude' / 'hooks'
        if hooks_template_dir.exists():
            hooks_dest_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            for hook_file in hooks_template_dir.iterdir():
                if hook_file.is_file() and hook_file.suffix in ['.cjs', '.js', '.sh']:
                    dest_hook = hooks_dest_dir / hook_file.name
                    if not dest_hook.exists():
                        shutil.copy(hook_file, dest_hook)
                        # Make executable
                        dest_hook.chmod(dest_hook.stat().st_mode | 0o111)
                        logger.info(f"Copied Pi hook: {hook_file.name}")

        logger.info("Pi integration setup complete")
        return True
    except Exception as e:
        logger.error(f"Error setting up Pi integration: {e}")
        return False


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def create_success_response(data: Any, message: str = None) -> Dict:
    """Create a standardized success response"""
    response = {"success": True, "data": data}
    if message:
        response["message"] = message
    return response


def create_error_response(error: str, suggestion: str = None) -> Dict:
    """Create a standardized error response"""
    response = {"success": False, "error": error}
    if suggestion:
        response["suggestion"] = suggestion
    return response


def load_beta_features() -> Optional[Dict]:
    """Load beta features configuration"""
    if not BETA_FEATURES_FILE.exists():
        return None

    try:
        with open(BETA_FEATURES_FILE, 'r') as f:
            return yaml.safe_load(f) if yaml else None
    except Exception as e:
        logger.error(f"Error loading beta features: {e}")
        return None


def load_user_profile() -> Optional[Dict]:
    """Load user profile"""
    if not USER_PROFILE_FILE.exists():
        return None

    try:
        with open(USER_PROFILE_FILE, 'r') as f:
            return yaml.safe_load(f) if yaml else None
    except Exception as e:
        logger.error(f"Error loading user profile: {e}")
        return None


def save_user_profile(profile: Dict) -> bool:
    """Save user profile"""
    try:
        with open(USER_PROFILE_FILE, 'w') as f:
            yaml.dump(profile, f, default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        logger.error(f"Error saving user profile: {e}")
        return False


def hash_code(salt: str, code: str) -> str:
    """Generate SHA-256 hash of salt:code"""
    combined = f"{salt}:{code}"
    return hashlib.sha256(combined.encode()).hexdigest()


def validate_code(code: str) -> tuple[Optional[str], Optional[Dict]]:
    """
    Validate activation code against all beta features.
    Returns (feature_key, feature_config) if valid, (None, None) otherwise.
    """
    beta_config = load_beta_features()
    if not beta_config:
        return None, None

    if not beta_config.get('settings', {}).get('enabled', True):
        return None, None

    features = beta_config.get('features', {})

    for feature_key, feature in features.items():
        if feature.get('status') != 'active':
            continue

        salt = feature.get('code_salt', '')
        expected_hash = feature.get('code_hash', '')

        if hash_code(salt, code) == expected_hash:
            return feature_key, feature

    return None, None


def is_feature_activated(feature_key: str) -> bool:
    """Check if a specific feature is activated for the user"""
    profile = load_user_profile()
    if not profile:
        return False

    beta = profile.get('beta', {})
    # Handle case where beta might be a bool instead of dict
    if not isinstance(beta, dict):
        beta = {}
    activated = beta.get('activated', {})

    return feature_key in activated


def get_feature_instructions(feature_key: str) -> Optional[str]:
    """Get the instructions file content for a feature"""
    beta_config = load_beta_features()
    if not beta_config:
        return None

    feature = beta_config.get('features', {}).get(feature_key)
    if not feature:
        return None

    instructions_path = feature.get('instructions_file')
    if not instructions_path:
        return None

    full_path = BASE_DIR / instructions_path
    if not full_path.exists():
        return None

    try:
        return full_path.read_text()
    except Exception as e:
        logger.error(f"Error reading instructions: {e}")
        return None


# ============================================================================
# MCP SERVER
# ============================================================================

app = Server("dex-beta-mcp")


@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available tools"""
    return [
        types.Tool(
            name="validate_beta_code",
            description="Check if a beta activation code is valid. Returns feature info if valid, error if not.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The beta activation code to validate"
                    }
                },
                "required": ["code"]
            }
        ),
        types.Tool(
            name="activate_beta_feature",
            description="Activate a beta feature using an activation code. Saves activation to user profile.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The beta activation code"
                    }
                },
                "required": ["code"]
            }
        ),
        types.Tool(
            name="get_beta_status",
            description="Get list of all activated beta features for the current user",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="check_beta_enabled",
            description="Check if a specific beta feature is activated",
            inputSchema={
                "type": "object",
                "properties": {
                    "feature": {
                        "type": "string",
                        "description": "The feature key to check (e.g., 'pi')"
                    }
                },
                "required": ["feature"]
            }
        ),
        types.Tool(
            name="get_beta_instructions",
            description="Get the setup/usage instructions for a beta feature",
            inputSchema={
                "type": "object",
                "properties": {
                    "feature": {
                        "type": "string",
                        "description": "The feature key (e.g., 'pi')"
                    }
                },
                "required": ["feature"]
            }
        ),
        types.Tool(
            name="list_available_betas",
            description="List all available beta features (active, not yet activated)",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@app.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls"""
    arguments = arguments or {}

    if name == "validate_beta_code":
        code = arguments.get('code', '').strip()

        if not code:
            result = create_error_response(
                "No activation code provided",
                suggestion="Enter your beta activation code"
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        feature_key, feature = validate_code(code)

        if feature_key:
            # Check if already activated
            already_activated = is_feature_activated(feature_key)

            result = create_success_response({
                "valid": True,
                "feature_key": feature_key,
                "feature_name": feature.get('name'),
                "description": feature.get('description'),
                "version": feature.get('version'),
                "already_activated": already_activated,
                "capabilities": feature.get('capabilities', [])
            }, f"Valid code for {feature.get('name')}")
        else:
            beta_config = load_beta_features()
            behavior = beta_config.get('settings', {}).get('invalid_code_behavior', 'warn') if beta_config else 'warn'

            if behavior == 'silent':
                result = create_error_response("Invalid activation code")
            else:
                result = create_error_response(
                    "Invalid activation code",
                    suggestion="Check your code and try again. Contact support if the issue persists."
                )

        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "activate_beta_feature":
        code = arguments.get('code', '').strip()

        if not code:
            result = create_error_response("No activation code provided")
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        feature_key, feature = validate_code(code)

        if not feature_key:
            result = create_error_response(
                "Invalid activation code",
                suggestion="Double-check your code and try again"
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        # Load user profile
        profile = load_user_profile()
        if not profile:
            result = create_error_response(
                "Could not load user profile",
                suggestion="Run onboarding first to create your profile"
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        # Initialize beta section if needed
        if 'beta' not in profile:
            profile['beta'] = {
                'beta_user': True,
                'activated': {},
                'feedback_history': []
            }

        # Check if already activated
        if feature_key in profile['beta'].get('activated', {}):
            result = create_success_response({
                "feature_key": feature_key,
                "feature_name": feature.get('name'),
                "already_activated": True,
                "activated_at": profile['beta']['activated'][feature_key].get('activated_at')
            }, f"{feature.get('name')} is already activated!")
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

        # Activate the feature
        profile['beta']['beta_user'] = True
        if 'activated' not in profile['beta']:
            profile['beta']['activated'] = {}

        profile['beta']['activated'][feature_key] = {
            'activated_at': datetime.now().isoformat(),
            'version_at_activation': feature.get('version'),
            'capabilities': feature.get('capabilities', [])
        }

        # Run feature-specific setup
        if feature_key == 'pi':
            if not setup_pi_integration():
                logger.warning("Pi integration setup had issues, but activation continues")

        # Save profile
        if not save_user_profile(profile):
            result = create_error_response("Failed to save activation")
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        # Get instructions path
        instructions_path = feature.get('instructions_file')

        result = create_success_response({
            "feature_key": feature_key,
            "feature_name": feature.get('name'),
            "description": feature.get('description'),
            "version": feature.get('version'),
            "capabilities": feature.get('capabilities', []),
            "instructions_file": instructions_path,
            "activated_at": profile['beta']['activated'][feature_key]['activated_at']
        }, f"Successfully activated {feature.get('name')}! Welcome to the beta.")

        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

    elif name == "get_beta_status":
        profile = load_user_profile()
        beta_config = load_beta_features()

        if not profile:
            result = create_success_response({
                "is_beta_user": False,
                "activated_features": [],
                "message": "No user profile found"
            })
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        beta = profile.get('beta', {})
        # Handle case where beta might be a bool instead of dict
        if not isinstance(beta, dict):
            beta = {}
        activated = beta.get('activated', {})

        # Enrich with feature details
        activated_features = []
        for feature_key, activation_info in activated.items():
            feature_details = {
                "key": feature_key,
                "activated_at": activation_info.get('activated_at'),
                "version_at_activation": activation_info.get('version_at_activation'),
                "capabilities": activation_info.get('capabilities', [])
            }

            # Add current feature info from config
            if beta_config:
                feature = beta_config.get('features', {}).get(feature_key, {})
                feature_details["name"] = feature.get('name', feature_key)
                feature_details["current_version"] = feature.get('version')
                feature_details["status"] = feature.get('status')

            activated_features.append(feature_details)

        result = create_success_response({
            "is_beta_user": beta.get('beta_user', False),
            "activated_features": activated_features,
            "total_activated": len(activated_features),
            "feedback_submitted": len(beta.get('feedback_history', []))
        })

        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

    elif name == "check_beta_enabled":
        feature = arguments.get('feature', '').strip()

        if not feature:
            result = create_error_response("No feature key provided")
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        is_enabled = is_feature_activated(feature)

        # Get feature details
        beta_config = load_beta_features()
        feature_info = {}
        if beta_config:
            feature_config = beta_config.get('features', {}).get(feature)
            if feature_config:
                feature_info = {
                    "name": feature_config.get('name'),
                    "version": feature_config.get('version'),
                    "status": feature_config.get('status')
                }

        result = create_success_response({
            "feature": feature,
            "enabled": is_enabled,
            "feature_info": feature_info
        })

        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "get_beta_instructions":
        feature = arguments.get('feature', '').strip()

        if not feature:
            result = create_error_response("No feature key provided")
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        # Check if activated
        if not is_feature_activated(feature):
            result = create_error_response(
                f"Feature '{feature}' is not activated",
                suggestion="Activate the beta feature first using your activation code"
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        instructions = get_feature_instructions(feature)

        if instructions:
            result = create_success_response({
                "feature": feature,
                "instructions": instructions
            })
        else:
            result = create_error_response(
                "Instructions not found",
                suggestion="The instructions file may not exist yet. Check back later."
            )

        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "list_available_betas":
        beta_config = load_beta_features()
        profile = load_user_profile()

        if not beta_config:
            result = create_success_response({
                "available_features": [],
                "message": "Beta features configuration not found"
            })
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        if not beta_config.get('settings', {}).get('enabled', True):
            result = create_success_response({
                "available_features": [],
                "message": "Beta features system is currently disabled"
            })
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        # Get activated features
        activated = set()
        if profile and 'beta' in profile:
            activated = set(profile['beta'].get('activated', {}).keys())

        # List available (active, not activated)
        available = []
        for feature_key, feature in beta_config.get('features', {}).items():
            if feature.get('status') != 'active':
                continue

            feature_info = {
                "key": feature_key,
                "name": feature.get('name'),
                "description": feature.get('description'),
                "version": feature.get('version'),
                "activated": feature_key in activated
            }
            available.append(feature_info)

        result = create_success_response({
            "available_features": available,
            "total_available": len(available),
            "total_activated": len(activated)
        })

        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def _main():
    """Async main entry point for the MCP server"""
    logger.info("Starting Dex Beta Features MCP Server")
    logger.info(f"Vault path: {BASE_DIR}")
    logger.info(f"Beta features file: {BETA_FEATURES_FILE}")

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-beta-mcp",
                server_version="1.0.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main():
    """Sync entry point for console script"""
    import asyncio
    asyncio.run(_main())


if __name__ == "__main__":
    main()
