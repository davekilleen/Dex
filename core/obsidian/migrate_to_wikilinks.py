#!/usr/bin/env python3
"""
Migrate existing Dex vault to Obsidian wiki link format
Zero AI tokens - pure regex pattern matching
"""
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple
from datetime import datetime

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

BASE_DIR = Path(os.environ.get('VAULT_PATH', Path.cwd()))

# Build indices for smart conversion
def build_person_index() -> dict:
    """Build index of all person filenames"""
    people_dir = BASE_DIR / '05-Areas' / 'People'
    index = {}
    
    if people_dir.exists():
        for person_file in people_dir.rglob('*.md'):
            name = person_file.stem  # e.g., John_Doe
            rel_path = person_file.relative_to(BASE_DIR)
            index[name] = str(rel_path)
    
    return index

def build_project_index() -> dict:
    """Build index of all projects"""
    projects_dir = BASE_DIR / '04-Projects'
    index = {}
    
    if projects_dir.exists():
        for proj_file in projects_dir.rglob('*.md'):
            name = proj_file.stem
            rel_path = proj_file.relative_to(BASE_DIR)
            index[name] = str(rel_path)
    
    return index

def build_company_index() -> dict:
    """Build index of all companies"""
    companies_dir = BASE_DIR / '05-Areas' / 'Companies'
    index = {}
    
    if companies_dir.exists():
        for comp_file in companies_dir.rglob('*.md'):
            name = comp_file.stem
            rel_path = comp_file.relative_to(BASE_DIR)
            index[name] = str(rel_path)
    
    return index

def convert_references_in_file(content: str, person_idx: dict, 
                               project_idx: dict, company_idx: dict) -> Tuple[str, int]:
    """Convert plain text references to wiki links. Returns (new_content, num_changes)"""
    changes = 0
    
    # Skip code blocks
    code_blocks = []
    def save_code_block(match):
        code_blocks.append(match.group(0))
        return f"__CODE_BLOCK_{len(code_blocks)-1}__"
    
    content = re.sub(r'```.*?```', save_code_block, content, flags=re.DOTALL)
    
    # Convert person references (Firstname_Lastname pattern)
    for person_name, person_path in person_idx.items():
        # Only convert if not already a wiki link
        pattern = rf'(?<!\[\[)\b({re.escape(person_name)})\b(?!\]\])'
        matches = len(re.findall(pattern, content))
        if matches > 0:
            content = re.sub(pattern, rf'[[\1]]', content)
            changes += matches
    
    # Convert project references (04-Projects/Project_Name)
    for project_name, project_path in project_idx.items():
        pattern = rf'(?<!\[\[)\b({re.escape(project_path)})\b(?!\]\])'
        matches = len(re.findall(pattern, content))
        if matches > 0:
            content = re.sub(pattern, rf'[[\1]]', content)
            changes += matches
    
    # Convert company references
    for company_name, company_path in company_idx.items():
        pattern = rf'(?<!\[\[)\b({re.escape(company_name)})\b(?!\]\])'
        matches = len(re.findall(pattern, content))
        if matches > 0:
            content = re.sub(pattern, rf'[[\1]]', content)
            changes += matches
    
    # Convert task ID references (^task-YYYYMMDD-XXX)
    pattern = r'(?<!\[\[)\^(task-\d{8}-\d{3})(?!\]\])'
    matches = len(re.findall(pattern, content))
    if matches > 0:
        content = re.sub(pattern, r'[[^\1]]', content)
        changes += matches
    
    # Restore code blocks
    for i, block in enumerate(code_blocks):
        content = content.replace(f"__CODE_BLOCK_{i}__", block)
    
    return content, changes

def estimate_migration(files: List[Path]) -> str:
    """Estimate migration time"""
    num_files = len(files)
    est_seconds = num_files / 30  # ~30 files/sec
    
    if est_seconds < 60:
        return f"~{int(est_seconds)} seconds"
    else:
        minutes = int(est_seconds / 60)
        return f"~{minutes} minute{'s' if minutes > 1 else ''}"

def migrate_vault(dry_run: bool = False):
    """Main migration function"""
    print("Dex Obsidian Migration\n" + "="*50)
    
    # Build indices
    print("Building indices...")
    person_idx = build_person_index()
    project_idx = build_project_index()
    company_idx = build_company_index()
    print(f"  Found {len(person_idx)} people")
    print(f"  Found {len(project_idx)} projects")
    print(f"  Found {len(company_idx)} companies")
    
    # Find all markdown files
    print("\nScanning vault...")
    md_files = list(BASE_DIR.rglob('*.md'))
    print(f"  Found {len(md_files)} markdown files")
    print(f"  Estimated time: {estimate_migration(md_files)}")
    
    if dry_run:
        print("\n[DRY RUN MODE] - No files will be modified")
    
    input("\nPress Enter to continue...")
    
    # Create backup via git
    if not dry_run:
        print("\nCreating backup...")
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        os.system(f'cd "{BASE_DIR}" && git add -A && git commit -m "Backup before Obsidian migration - {timestamp}"')
    
    # Process files
    print("\nConverting files...")
    total_changes = 0
    files_modified = 0
    
    iterator = tqdm(md_files, desc="Processing") if HAS_TQDM else md_files
    
    for md_file in iterator:
        try:
            content = md_file.read_text()
            new_content, changes = convert_references_in_file(
                content, person_idx, project_idx, company_idx
            )
            
            if changes > 0:
                if not dry_run:
                    md_file.write_text(new_content)
                files_modified += 1
                total_changes += changes
        except Exception as e:
            print(f"\nError processing {md_file}: {e}")
    
    # Summary
    print("\n" + "="*50)
    print("Migration Complete!")
    print(f"  Files scanned: {len(md_files)}")
    print(f"  Files modified: {files_modified}")
    print(f"  Total conversions: {total_changes}")
    
    if not dry_run:
        print(f"\nBackup saved. To revert: git reset --hard HEAD~1")
        
        # macOS notification
        os.system(f'''
            osascript -e 'display notification "{files_modified} files converted with wiki links" 
            with title "Dex Obsidian Migration Complete" sound name "Glass"'
        ''')
        
        # Sound
        os.system('afplay /System/Library/Sounds/Glass.aiff')
    else:
        print("\n[DRY RUN] No files were modified. Run without --dry-run to apply changes.")

if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    migrate_vault(dry_run=dry_run)
