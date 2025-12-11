#!/usr/bin/env python3
"""
Test script to export all conversations in history to PDF.

This script attempts to export every conversation file in the history directory
to PDF format, reporting successes and failures. Useful for testing PDF export
functionality and identifying problematic conversations.
"""

import sys
import os
from pathlib import Path

# Add src directory to path so modules in src can import each other directly
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# Import modules (src/ is in path, so we can import directly)
from config import HISTORY_DIR  # type: ignore
from utils import load_chat_history, list_chat_histories  # type: ignore
from latex_utils import export_chat_to_pdf  # type: ignore


def test_export_all_conversations(output_dir=None, verbose=False):
    """
    Attempt to export all conversations in history to PDF.
    
    Args:
        output_dir: Directory to save test PDFs (default: test_exports/)
        verbose: If True, print detailed information for each conversation
    """
    if output_dir is None:
        output_dir = Path(__file__).parent / "test_exports"
    else:
        output_dir = Path(output_dir)
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Testing PDF export for all conversations")
    print(f"History directory: {HISTORY_DIR}")
    print(f"Output directory: {output_dir}")
    print(f"{'='*70}\n")
    
    # Get all conversation files
    try:
        chat_histories = list_chat_histories()
        chat_files = [h['filename'] for h in chat_histories]
    except Exception as e:
        print(f"ERROR: Failed to list chat files: {e}")
        return
    
    if not chat_files:
        print("No conversation files found in history directory.")
        return
    
    print(f"Found {len(chat_files)} conversation file(s)\n")
    
    # Track results
    successes = []  # List of (chat_name, engine_name) tuples
    failures = []
    skipped = []
    
    for i, chat_file in enumerate(chat_files, 1):
        chat_name = chat_file.replace('.json', '')
        print(f"[{i}/{len(chat_files)}] Processing: {chat_name}")
        
        # Load conversation
        try:
            conversation = load_chat_history(chat_name, messages_only=True)
        except Exception as e:
            print(f"  ERROR: Failed to load conversation: {e}")
            failures.append((chat_name, f"Load error: {e}"))
            print()
            continue
        
        if not conversation:
            print(f"  SKIP: Empty conversation")
            skipped.append((chat_name, "Empty conversation"))
            print()
            continue
        
        # Get title from metadata or use chat name
        try:
            full_data = load_chat_history(chat_name, messages_only=False)
            metadata = full_data.get("metadata", {})
            title = metadata.get("title") or chat_name
        except Exception:
            title = chat_name
        
        # Generate output filename
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        if not safe_title:
            safe_title = chat_name
        output_filename = output_dir / f"test_{safe_title}.pdf"
        
        if verbose:
            print(f"  Title: {title}")
            print(f"  Messages: {len(conversation)}")
            print(f"  Output: {output_filename}")
        
        # Attempt export
        try:
            result = export_chat_to_pdf(
                conversation=conversation,
                filename=str(output_filename),
                title=title,
                chat_id=chat_name
            )
            
            # Handle both tuple (success, engine_name) and bool return formats
            if isinstance(result, tuple):
                success, engine_name = result
            else:
                success = result
                engine_name = None
            
            if success:
                engine_info = f" ({engine_name})" if engine_name else ""
                print(f"  ✓ SUCCESS: Exported to {output_filename.name}{engine_info}")
                successes.append((chat_name, engine_name))
            else:
                print(f"  ✗ FAILED: Export returned False")
                failures.append((chat_name, "Export returned False"))
        except Exception as e:
            print(f"  ✗ FAILED: Exception during export: {e}")
            failures.append((chat_name, f"Exception: {e}"))
            if verbose:
                import traceback
                traceback.print_exc()
        
        print()
    
    # Print summary
    print(f"{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    print(f"Total conversations: {len(chat_files)}")
    print(f"  ✓ Successful: {len(successes)}")
    print(f"  ✗ Failed: {len(failures)}")
    print(f"  ⊘ Skipped: {len(skipped)}")
    print()
    
    if successes:
        print(f"Successful exports ({len(successes)}):")
        # Count engines used
        engine_counts = {}
        for name, engine_name in successes:
            engine_display = engine_name if engine_name else "Unknown"
            engine_counts[engine_display] = engine_counts.get(engine_display, 0) + 1
            print(f"  ✓ {name} [{engine_display}]")
        print()
        
        # Print engine usage summary
        if engine_counts:
            print(f"Engine usage summary:")
            for engine, count in sorted(engine_counts.items()):
                print(f"  {engine}: {count}")
            print()
    
    if failures:
        print(f"Failed exports ({len(failures)}):")
        for name, reason in failures:
            print(f"  ✗ {name}: {reason}")
        print()
    
    if skipped:
        print(f"Skipped conversations ({len(skipped)}):")
        for name, reason in skipped:
            print(f"  ⊘ {name}: {reason}")
        print()
    
    # Return status code
    return 0 if len(failures) == 0 else 1


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Test PDF export for all conversations in history"
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default=None,
        help="Directory to save test PDFs (default: test_exports/)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print detailed information for each conversation"
    )
    
    args = parser.parse_args()
    
    sys.exit(test_export_all_conversations(
        output_dir=args.output_dir,
        verbose=args.verbose
    ))
