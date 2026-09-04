import argparse
import json

def parse_time(t):
    # format: MM:SS.mmm
    m, rest = t.split(":")
    s, ms = rest.split(".")
    total = int(m) * 60 + int(s) + int(ms) / 1000
    return total

def to_srt_time(s):
    ms = int((s % 1) * 1000)
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"

parser = argparse.ArgumentParser(description="Convert word-timed transcript JSON to SRT.")
parser.add_argument("transcript")
parser.add_argument("output")
args = parser.parse_args()

with open(args.transcript, encoding="utf-8") as f:
    data = json.load(f)

with open(args.output, "w", encoding="utf-8") as out:
    for i, entry in enumerate(data):
        start_str, end_str = entry["timestamp"].split("-")
        start = parse_time(start_str)
        end = parse_time(end_str)
        out.write(f"{i+1}\n")
        out.write(f"{to_srt_time(start)} --> {to_srt_time(end)}\n")
        out.write(f"{entry['text'].strip()}\n\n")

print(f"Done -- {len(data)} words written to {args.output}")
