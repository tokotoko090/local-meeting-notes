from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--backend":
        from backend import meeting_notes

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        return meeting_notes.main()

    from backend import server

    return server.main()


if __name__ == "__main__":
    raise SystemExit(main())
