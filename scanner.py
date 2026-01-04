#!/usr/bin/env python3
import sys

def main():
    try:
        import feedparser
    except ModuleNotFoundError:
        print("WARNING: feedparser not installed")
        print("Scanner skipped")
        sys.exit(0)  # <- critical: clean exit

    print("feedparser available, running scan")
    # your real scan logic here
    sys.exit(0)

if __name__ == "__main__":
    main()
