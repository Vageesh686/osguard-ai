import json
from app.stages.verify import effect, environment

for line in open("eval/commands.jsonl", encoding="utf-8"):
    r = json.loads(line)
    missing = [n for n in effect.analyze_command(r["command"], r["shell"]).commands
               if environment.command_exists(n) is False]
    if bool(missing) != (not r["exists"]):
        print(r["command"], "->", missing, "| gold exists:", r["exists"])