#!/usr/bin/env python3
"""
Bidirectional sync daemon for Obsidian ↔ Dex
Monitors file changes and syncs task states using Work MCP
"""
import logging
import re
import sys
import time
from pathlib import Path
from typing import Set

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

_repo_root = str(Path(__file__).parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.append(_repo_root)
from core.paths import OBSIDIAN_SYNC_LOG as LOG_FILE
from core.paths import VAULT_ROOT as BASE_DIR
from core.utils.dex_logger import log_error

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TASK_PATTERN = re.compile(r'- \[([ xX])\].*?\^(task-\d{8}-\d{3})')


class DexSyncHandler(FileSystemEventHandler):
    """Handle file changes and sync task states"""

    def __init__(self, vault_root: Path = BASE_DIR):
        self.debounce_time = 1.0  # seconds
        self.pending_files: Set[Path] = set()
        self.last_process_time = time.time()
        self.last_seen_states = {}
        self.failure_counts = {}
        self._prime_last_seen_states(Path(vault_root))

    @staticmethod
    def _read_task_states(file_path: Path):
        content = file_path.read_text()
        return [
            (task_id, checkbox_state.lower() == 'x')
            for checkbox_state, task_id in TASK_PATTERN.findall(content)
        ]

    def _prime_last_seen_states(self, vault_root: Path):
        """Capture checkbox baselines before file events begin."""
        if not vault_root.exists():
            return

        for file_path in vault_root.rglob('*.md'):
            try:
                for task_id, completed in self._read_task_states(file_path):
                    self.last_seen_states[(file_path, task_id)] = completed
            except (OSError, UnicodeError) as error:
                logger.warning(f"Could not baseline task states in {file_path}: {error}")
    
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
        
        canonical_states = None
        for file_path in self.pending_files:
            try:
                canonical_states = self.sync_file_tasks(file_path, canonical_states)
            except Exception as e:
                logger.error(f"Error syncing {file_path}: {e}")
        
        self.pending_files.clear()
        self.last_process_time = time.time()
    
    def sync_file_tasks(self, file_path: Path, canonical_states=None):
        """Sync task states from a modified file"""
        task_states = self._read_task_states(file_path)
        
        if not task_states:
            return canonical_states
        
        logger.info(f"Found {len(task_states)} tasks in {file_path.name}")
        
        changed_states = []
        for task_id, completed in task_states:
            state_key = (file_path, task_id)
            previous_state = self.last_seen_states.get(state_key)

            if previous_state is None:
                self.last_seen_states[state_key] = completed
                continue
            if previous_state == completed:
                continue
            changed_states.append((state_key, task_id, completed))

        if not changed_states:
            return canonical_states

        from core.mcp import work_server

        if canonical_states is None:
            canonical_states = {
                task['task_id']: task['completed']
                for task in work_server.parse_tasks_file(work_server.get_tasks_file())
                if task.get('task_id')
            }

        # When the edit happened in Tasks.md itself, the canonical snapshot was
        # read from that same just-saved file, so it trivially matches — the
        # equality guard below would wrongly skip it. A direct Tasks.md edit is
        # exactly the case that must still propagate to the mirror pages, so we
        # bypass the equality guard for it (the last_seen guard above already
        # prevents the write-back it triggers from looping).
        try:
            edit_is_canonical_tasks_file = (
                file_path.resolve() == work_server.get_tasks_file().resolve()
            )
        except OSError:
            edit_is_canonical_tasks_file = False

        # Call Work MCP only for a newly observed transition that differs
        # from the canonical backlog.
        for state_key, task_id, completed in changed_states:
            if task_id not in canonical_states:
                logger.warning(f"Skipped {task_id}: not found in canonical Tasks.md")
                self.last_seen_states[state_key] = completed
                self._clear_sync_failure(task_id)
                continue
            if not edit_is_canonical_tasks_file and canonical_states[task_id] == completed:
                self.last_seen_states[state_key] = completed
                self._clear_sync_failure(task_id)
                continue

            status = 'd' if completed else 'n'
            # Call Work MCP update_task_status
            # This updates the task everywhere (Tasks.md, person pages, etc.)
            try:
                result = work_server.update_task_status_everywhere(task_id, completed)
                if result['success']:
                    self.last_seen_states[state_key] = completed
                    canonical_states[task_id] = completed
                    self._clear_sync_failure(task_id)
                    logger.info(f"Synced {task_id} → {status}")
                else:
                    error = result.get('error', 'unknown error')
                    logger.error(f"Failed to sync {task_id}: {error}")
                    self._record_sync_failure(task_id, error)
            except Exception as e:
                logger.error(f"Failed to sync {task_id}: {e}")
                self._record_sync_failure(task_id, str(e))

        return canonical_states

    def _clear_sync_failure(self, task_id: str):
        self.failure_counts.pop(task_id, None)

    def _record_sync_failure(self, task_id: str, error: str):
        """Surface one session-start error after a task fails repeatedly."""
        failures = self.failure_counts.get(task_id, 0) + 1
        self.failure_counts[task_id] = failures
        if failures != 3:
            return

        log_error(
            source="obsidian-sync",
            message=f"Obsidian task sync repeatedly failed for {task_id}: {error}",
            human_message=f"Obsidian changes for {task_id} could not be synced after 3 attempts",
            context={"task_id": task_id, "failures": 3},
        )

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
