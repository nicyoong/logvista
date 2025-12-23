import random
from datetime import datetime, timedelta

OUTPUT_FILE = "mock10mb.log"
TARGET_SIZE_MB = 10
TARGET_BYTES = TARGET_SIZE_MB * 1024 * 1024

LEVELS = ["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"]

MESSAGES = [
    "User login succeeded",
    "User login failed for user_id={id}",
    "Connection timeout after {ms} ms",
    "Database query returned {rows} rows",
    "Failed to open file {path}",
    "Service started successfully",
    "Service stopped unexpectedly",
    "Retrying request attempt={n}",
    "Unhandled exception occurred",
    "Cache miss for key={key}",
]

STACK_TRACE = """Traceback (most recent call last):
  File "/app/service.py", line 142, in handle_request
    process(data)
  File "/app/processor.py", line 88, in process
    raise ValueError("Invalid payload")
ValueError: Invalid payload
"""

REPORT_EVERY_LINES = 100_000


def random_message():
    msg = random.choice(MESSAGES)
    return msg.format(
        id=random.randint(1000, 9999),
        ms=random.randint(50, 5000),
        rows=random.randint(1, 10000),
        path=f"/var/data/file_{random.randint(1, 500)}.dat",
        n=random.randint(1, 10),
        key=f"key_{random.randint(1, 100000)}",
    )


def main():
    written = 0
    line_count = 0
    now = datetime.now() - timedelta(days=1)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        while written < TARGET_BYTES:
            level = random.choices(
                LEVELS,
                weights=[30, 40, 15, 10, 5],
            )[0]

            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
            msg = random_message()

            line = f"{timestamp} [{level}] {msg}\n"
            line_count += 1

            # Occasionally add stack traces for realism
            if level in ("ERROR", "CRITICAL") and random.random() < 0.2:
                line += STACK_TRACE + "\n"
                line_count += STACK_TRACE.count("\n") + 1

            f.write(line)
            written += len(line.encode("utf-8"))
            now += timedelta(seconds=random.randint(0, 3))

            if line_count % REPORT_EVERY_LINES == 0:
                mb = written / (1024 * 1024)
                print(f"[progress] {line_count:,} lines written (~{mb:.1f} MB)")

    print(f"Generated {OUTPUT_FILE} (~{written / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
