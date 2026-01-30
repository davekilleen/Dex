#!/usr/bin/env python3
"""
Bidirectional sync daemon for Obsidian ↔ Dex
Monitors file changes and syncs task states using Work MCP
"""
import os
import time
import logging
from pathlib import Path
from typing import Set
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

BASE_DIR = Path(os.environ.get('VAULT_PATH', Path.cwd()))
LOG_FILE = BASE_DIR / 'System' / 'obsidian-sync.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class DexSyncHandler(FileSystemEventHandler):
    """Handle file changes and sync task states"""
    
    def __init__(self):
        self.debounce_time = 1.0  # seconds
        self.pending_files: Set[Path] = set()
        self.last_process_time = time.time()
    
    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith('.md'):
            return
        
        file_path = Path(event.src_path)
        self.pending_files.add(file_path)
        
        # Debounce - only process after inactivity
        current_time = time.time()
        if current_time - self.last_process_time > self.debounce_time:
            self.process_pending_files()
    
    def process_pending_files(self):
        """Process accumulated file changes"""
        if not self.pending_files:
            return
        
        logger.info(f"Processing {len(self.pending_files)} changed files")
        
        for file_path in self.pending_files:
            try:
                self.sync_file_tasks(file_path)
            except Exception as e:
                logger.error(f"Error syncing {file_path}: {e}")
        
        self.pending_files.clear()
        self.last_process_time = time.time()
    
    def sync_file_tasks(self, file_path: Path):
        """Sync task states from a modified file"""
        content = file_path.read_text()
        
        # Find all task checkboxes with IDs
        import re
        pattern = r'- \[([ xX])\].*?\^(task-\d{8}-\d{3})'
        matches = re.findall(pattern, content)
        
        if not matches:
            return
        
        logger.info(f"Found {len(matches)} tasks in {file_path.name}")
        
        # Call Work MCP to sync each task
        for checkbox_state, task_id in matches:
            status = 'd' if checkbox_state.lower() == 'x' else 'n'
            
            # Call Work MCP update_task_status
            # This updates the task everywhere (Tasks.md, person pages, etc.)
            try:
                from core.mcp.work_server import update_task_status_everywhere
                result = update_task_status_everywhere(task_id, status == 'd')
                logger.info(f"Synced {task_id} → {status}")
            except Exception as e:
                logger.error(f"Failed to sync {task_id}: {e}")

def start_daemon():
    """Start the sync daemon"""
    logger.info("Starting Dex Obsidian Sync Daemon")
    logger.info(f"Watching: {BASE_DIR}")
    logger.info(f"Log file: {LOG_FILE}")
    
    event_handler = DexSyncHandler()
    observer = Observer()
    observer.schedule(event_handler, str(BASE_DIR), recursive=True)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
            # Periodically process pending files
            if event_handler.pending_files:
                event_handler.process_pending_files()
    except KeyboardInterrupt:
        logger.info("Stopping daemon")
        observer.stop()
    
    observer.join()

if __name__ == '__main__':
    start_daemon()
