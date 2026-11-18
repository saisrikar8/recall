"""Structured file-completion progress, aggregated over folder ancestors."""
from pathlib import Path
import time

class IndexProgress:
    def __init__(self, paths, target, report):
        self.root=Path(target).parent if Path(target).is_file() else Path(target)
        self.reporter=report;self.started=time.monotonic();self.folders={};self.file=None
        self.stage='Checking files';self.revision=0;self.completed=set()
        self.paths={str(Path(path)):self.ancestors(Path(path)) for path in paths}
        for ancestors in self.paths.values():
            for folder in ancestors:
                row=self.folders.setdefault(folder,dict(path=folder,total=0,completed=0,failed=0))
                row['total']+=1
        self.emit()
    def ancestors(self,path):
        parts=path.relative_to(self.root).parent.parts
        return ['.']+[str(Path(*parts[:i])) for i in range(1,len(parts)+1)]
    def emit(self):
        callback=getattr(self.reporter,'event',None)
        if callback:
            callback(dict(root=str(self.root),stage=self.stage,file=self.file,revision=self.revision,
                elapsed_seconds=round(time.monotonic()-self.started,1),
                total=len(self.paths),completed=len(self.completed),
                folders=[dict(row) for row in self.folders.values()]))
    def begin(self,path):
        self.file=str(path);self.stage='Checking file';self.emit()
    def report(self,message):
        self.reporter(message)
        text=str(message)
        stage=self.stage
        if text.startswith('Text embeddings'):stage='Creating search embeddings'
        elif 'scene batch' in text:stage='Embedding images'
        elif 'PDF page batch' in text:stage='Embedding PDF pages'
        elif text.startswith('OCR'):stage='Reading text from images'
        elif 'Processing ' in text:stage='Extracting content'
        if stage!=self.stage:self.stage=stage;self.emit()
    def finish(self,path,status):
        key=str(path)
        if key in self.completed:return
        self.completed.add(key)
        for folder in self.paths[key]:
            self.folders[folder]['completed']+=1
            self.folders[folder]['failed']+=status=='failed'
        if status in {'new','changed'}:self.revision+=1
        self.stage='File complete' if status!='failed' else 'File failed';self.emit()
    def done(self):
        self.stage='Complete';self.file=None;self.emit()
