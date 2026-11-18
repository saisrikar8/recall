"""One database target shared by the application and migrations."""
import os
from pathlib import Path

from platformdirs import user_data_path
from sqlalchemy import URL

override = os.environ.get('RECALL_DB_PATH')
DATABASE_PATH = (Path(override).expanduser().resolve() if override
                 else user_data_path('recall', appauthor=False) / 'index.db')
DATABASE_URL = URL.create('sqlite', database=str(DATABASE_PATH))
