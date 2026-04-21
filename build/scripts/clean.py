"""
Clean build artifacts and temporary files
"""
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

def clean_build_outputs():
    """Remove build output directories"""
    print("Cleaning build outputs...")

    dirs_to_remove = [
        PROJECT_ROOT / 'build' / 'output' / 'dist',
        PROJECT_ROOT / 'build' / 'output' / 'build',
        PROJECT_ROOT / 'build' / 'output' / 'release',
        PROJECT_ROOT / 'dist',
        PROJECT_ROOT / 'build' / '__pycache__',
    ]

    for dir_path in dirs_to_remove:
        if dir_path.exists():
            print(f"  Removing: {dir_path}")
            shutil.rmtree(dir_path, ignore_errors=True)

    print("✓ Build outputs cleaned")


def clean_python_cache():
    """Remove Python cache files"""
    print("Cleaning Python cache...")

    count = 0
    for root, dirs, files in os.walk(PROJECT_ROOT):
        # Remove __pycache__ directories
        if '__pycache__' in dirs:
            cache_dir = Path(root) / '__pycache__'
            shutil.rmtree(cache_dir, ignore_errors=True)
            count += 1

        # Remove .pyc files
        for file in files:
            if file.endswith('.pyc'):
                os.remove(Path(root) / file)
                count += 1

    print(f"✓ Removed {count} cache files/directories")


def main():
    print("="*60)
    print("  EzPrint Build Cleanup")
    print("="*60)
    print()

    clean_build_outputs()
    clean_python_cache()

    print()
    print("="*60)
    print("  Cleanup complete!")
    print("="*60)


if __name__ == "__main__":
    main()
