import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine,event,select,text
from src import database as db,indexing,pipeline
from src.models import Embedding
from src.vector_cache import candidates,clear

class VectorCacheTests(unittest.TestCase):
    def setUp(self):
        clear();self.addCleanup(clear)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        engine=create_engine('sqlite:///'+str(self.root/'index.db'));self.addCleanup(engine.dispose)
        event.listen(engine,'connect',db.register_functions)
        self.enterContext(patch.object(db,'engine',engine))
        (self.root/'a.py').write_text('def x(): return 1')
        with patch.object(indexing,'get_code_embedding',return_value=[1.,0.]):indexing.update_index(self.root,report=lambda _:None)
    def test_matches_cosine_and_invalidates_on_updates(self):
        with db.get_db() as session:
            first=candidates(session,pipeline.MODEL_KEY,[1.,0.],None,10,-1)
        self.assertTrue(first);self.assertTrue(all(abs(value-1)<1e-6 for value in first.values()))
        with db.get_db() as session,session.begin():
            for vector in session.scalars(select(Embedding)):vector.vector=[0.,1.]
        with db.get_db() as session:
            after=candidates(session,pipeline.MODEL_KEY,[1.,0.],None,10,-1)
        self.assertTrue(all(abs(value)<1e-6 for value in after.values()))
    def test_external_connection_changes_are_seen(self):
        with db.get_db() as session:candidates(session,pipeline.MODEL_KEY,[1.,0.],None,10,-1)
        import sqlite3
        with sqlite3.connect(self.root/'index.db') as connection:connection.execute('UPDATE embeddings SET vector=?',(json.dumps([-1.,0.]),))
        connection.close()
        with db.get_db() as session:
            after=candidates(session,pipeline.MODEL_KEY,[1.,0.],None,10,-1)
        self.assertTrue(all(value<-.99 for value in after.values()))
