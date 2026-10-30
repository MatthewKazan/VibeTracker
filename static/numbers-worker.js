importScripts('/vendor/xlsx.full.min.js');
self.onmessage=({data})=>{
 try{
  if(data.byteLength>25_000_000)throw Error('The file exceeds 25 MB. Export a smaller table from Numbers.');
  const magic=new Uint8Array(data);if(magic[0]!==80||magic[1]!==75)throw Error('This is not a modern Numbers archive.');
  const wb=XLSX.read(data,{type:'array',cellDates:false,cellFormula:false,cellHTML:false});
  // Dates are read as day serials and rounded to the nearest day. SheetJS's Date objects for Numbers cells
  // carry a time-zone offset, so converting them gave the previous day for users east of the Americas.
  const base=wb.Workbook?.WBProps?.date1904?1462:0;
  for(const ws of Object.values(wb.Sheets))for(const [ref,c] of Object.entries(ws))if(ref[0]!=='!'&&c.t==='n'&&c.z&&XLSX.SSF.is_date(c.z)){c.t='s';c.v=c.w=new Date(Date.UTC(1899,11,30)+Math.round(c.v+base)*864e5).toISOString().slice(0,10);delete c.z;}
  const tables=wb.SheetNames.map(name=>{const ws=wb.Sheets[name],range=ws['!ref']?XLSX.utils.decode_range(ws['!ref']):null;if(range&&(range.e.r>10000||range.e.c>199))throw Error('The table exceeds 10,000 rows or 200 columns. Export a smaller table from Numbers.');return {name,rows:XLSX.utils.sheet_to_json(ws,{header:1,raw:true,defval:'',blankrows:false}).map(row=>row.map(v=>String(v??'')))}}).filter(t=>t.rows.length);
  if(!tables.length)throw Error('No populated tables were found.');
  self.postMessage({tables});
 }catch(e){self.postMessage({error:'Could not read this Numbers file. '+e.message+' Open it in Numbers and save an unencrypted, current-format copy, or export as .xlsx/CSV.'})}
};
