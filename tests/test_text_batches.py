import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine,event,select,func
from src import database as db,indexing,semantic_search
from src.models import Embedding,Extraction

class TextBatchTests(unittest.TestCase):
    def test_default_indexer_uses_bounded_length_grouped_batches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'sample.py').write_text('\n'.join(f'def value_{i}(): return {i}' for i in range(12)))
            engine=create_engine('sqlite://');event.listen(engine,'connect',db.register_functions)
            batches=[]
            def encode(values):batches.append(values);return [[1.,0.] for _ in values]
            with patch.dict(os.environ,{'RECALL_TEXT_BATCH_SIZE':'2'}),patch.object(db,'engine',engine),patch.object(semantic_search,'get_code_embeddings',side_effect=encode):
                counts=indexing.update_index(root,report=lambda _:None)
                self.assertEqual(counts['new'],1)
                self.assertTrue(batches)
                self.assertTrue(all(len(batch)<=2 for batch in batches))
                lengths=[len(value) for batch in batches for value in batch]
                self.assertEqual(lengths,sorted(lengths))
                with db.get_db() as session:
                    self.assertEqual(session.scalar(select(Extraction.status)),'complete')
                    self.assertEqual(session.scalar(select(func.count()).select_from(Embedding)),sum(map(len,batches)))
            engine.dispose()
