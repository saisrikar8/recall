from pathlib import Path
import sqlite3
from platformdirs import user_data_path

source = Path("index/index.db").resolve()
destination = user_data_path("recall", appauthor=False) / "index.db"

if not source.is_file():
    raise FileNotFoundError(source)

destination.parent.mkdir(parents=True, exist_ok=True)

# Exclusive creation prevents accidentally replacing another database.
with destination.open("xb"):
    pass

with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as old:
    with sqlite3.connect(destination) as new:
        old.backup(new)

print(f"Copied database to {destination}")