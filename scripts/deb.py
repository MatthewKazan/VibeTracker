import io,tarfile,time,os
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'release/JobTracker-1.1.7-amd64.deb'
def tar(entries):
 b=io.BytesIO()
 with tarfile.open(fileobj=b,mode='w:gz') as t:
  for name,value,mode in entries:
   if isinstance(value,Path):
    def ownership(i):
     i.uid=i.gid=0;i.uname=i.gname='root'
     if i.name.endswith('/chrome-sandbox'):i.mode=0o4755
     return i
    t.add(value,arcname=name,filter=ownership)
   else:
    raw=value.encode();i=tarfile.TarInfo(name);i.size=len(raw);i.mode=mode;t.addfile(i,io.BytesIO(raw))
 return b.getvalue()
control=tar([('control','Package: jobtracker\nVersion: 1.1.7\nArchitecture: amd64\nMaintainer: JobTracker contributors\nDescription: Local job application tracker\nDepends: libgtk-3-0, libnss3, libasound2, libgbm1\n',0o644)])
data=tar([('opt/jobtracker',root/'release/linux-unpacked',0),('usr/bin/jobtracker','#!/bin/sh\nexec /opt/jobtracker/jobtracker "$@"\n',0o755),('usr/share/applications/jobtracker.desktop','[Desktop Entry]\nName=JobTracker\nExec=/opt/jobtracker/jobtracker %U\nIcon=jobtracker\nType=Application\nCategories=Office;\nTerminal=false\n',0o644),('usr/share/icons/hicolor/256x256/apps/jobtracker.png',root/'build/icons/256x256.png',0)])
with out.open('wb') as f:
 f.write(b'!<arch>\n')
 for name,b in [('debian-binary',b'2.0\n'),('control.tar.gz',control),('data.tar.gz',data)]:
  f.write(f'{name+"/":<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(b):<10}`\n'.encode());f.write(b)
  if len(b)%2:f.write(b'\n')
print(out)
