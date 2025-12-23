import os
import sys

ALLOWED_EXTENSION = ".log"

def is_safe_log_file(path: str) -> bool:
    """
    Strict validation:
    - Must exist
    - Must be a regular file (not dir, not symlink)
    - Must end with .log (case-insensitive)
    - Must not be root or empty path
    """
    if not path:
        return False

    real_path = os.path.realpath(path)

    if not os.path.exists(real_path):
        print("❌ File does not exist.")
        return False

    if not os.path.isfile(real_path):
        print("❌ Not a regular file.")
        return False

    if os.path.islink(path):
        print("❌ Symlinks are not allowed.")
        return False

    if not real_path.lower().endswith(ALLOWED_EXTENSION):
        print(f"❌ Only '{ALLOWED_EXTENSION}' files may be deleted.")
        return False

    return True


def delete_permanently(path: str):
    if not is_safe_log_file(path):
        return

    real_path = os.path.realpath(path)
    size_mb = os.path.getsize(real_path) / (1024 * 1024)

    print(f"Target file : {real_path}")
    print(f"File size  : {size_mb:.2f} MB")
    print("⚠️  This deletion is PERMANENT and bypasses the recycle bin.")

    confirm = input(
        "Type exactly DELETE_LOG to confirm: "
    )

    if confirm != "DELETE_LOG":
        print("❎ Cancelled.")
        return

    os.remove(real_path)
    print("✅ Log file deleted permanently.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python logdel.py <file.log>")
        sys.exit(1)

    delete_permanently(sys.argv[1])
