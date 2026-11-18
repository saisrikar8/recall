"""Create an isolated, explicitly synthetic desktop test library."""
import os
from pathlib import Path
from unittest.mock import patch
import sys
root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=True)
os.environ['RECALL_DB_PATH']=str(root/'index.db')
files=root/'Field notes';files.mkdir(exist_ok=True)
(files/'A note on remembering.md').write_text('# A note on remembering\n\nGood retrieval starts with a small question.\n\n## Leave a trail\n\nKeep the original file close. Search by meaning, then return to the source.\n\n> A little less looking. A little more finding.\n\n- Notes and documents\n- Code and ideas\n')
(files/'retrieval.py').write_text('"""A small retrieval example."""\n\ndef find_memory(query: str):\n    # Keep the source close to the result.\n    memories = ["a thought", "a note", "an idea"]\n    return [item for item in memories if query in item]\n')
import pymupdf
with pymupdf.open() as document:
 for title in ['Field notes / 01','A thought, rediscovered.']:
  page=document.new_page(width=595,height=842)
  page.insert_text((60,100),title,fontsize=26,color=(.20,.36,.26))
  page.insert_text((60,160),'Semantic retrieval connects ideas to their original context.',fontsize=12)
  page.insert_text((60,190),'Search by meaning. Keep what matters.',fontsize=12)
 document.save(files/'Field notes.pdf')
from PIL import Image,ImageDraw
with Image.new('RGB',(800,550),'#edf1e4') as image:
 draw=ImageDraw.Draw(image);draw.ellipse((200,80,600,480),outline='#345c42',width=8);draw.line((100,275,700,275),fill='#b9c7a3',width=3);image.save(files/'Connections.png')
from src import indexing,visual
with patch.object(indexing,'get_code_embedding',return_value=[1.] + [0.]*767),patch.object(visual,'embed_images',side_effect=lambda images:[[[1.] + [0.]*127] for _ in images]),patch.object(visual,'embed_image',return_value=[[1.] + [0.]*127]),patch.object(visual,'ocr_image',return_value='Connections between ideas'),patch('src.scene_search.encode_images',side_effect=lambda images:[[1.] + [0.]*511 for _ in images]):
 result=indexing.update_index(files)
 assert result['failed']==0,result
print(root/'index.db')
