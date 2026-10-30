"""Conservative normalization of job locations; never infer a state from the model alone."""
import json,re,threading,time,urllib.parse
STATES=dict(zip(('Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|District of Columbia|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming').split('|'),('AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY').split()))
US={'united states of america','united states','usa','us','u.s.','u.s.a.'}
LOCK=threading.Lock();CACHE={};LAST=0

def city_label(value):
 return re.sub(r'\s+(?:office|campus|headquarters|hq)(?:\s*\([^)]*\))?\s*$','',value,flags=re.I).strip()

def lookup(city,fetch):
 global LAST
 with LOCK:
  key=city.casefold()
  if key in CACHE:return CACHE[key]
  time.sleep(max(0,1.1-(time.monotonic()-LAST)));LAST=time.monotonic()
  url='https://nominatim.openstreetmap.org/search?'+urllib.parse.urlencode({'city':city,'countrycodes':'us','format':'json','addressdetails':1,'limit':5})
  candidates=[]
  for r in json.loads(fetch(url)):
   a=r.get('address',{});name=next((a[k] for k in ('city','town','village','municipality') if a.get(k)),'')
   code=a.get('ISO3166-2-lvl4','').removeprefix('US-') if hasattr(str,'removeprefix') else a.get('ISO3166-2-lvl4','')[3:]
   if name.casefold()==key and a.get('country_code')=='us' and code in STATES.values():candidates.append((float(r.get('importance',0)),code))
  candidates.sort(reverse=True)
  # Refuse similarly prominent namesakes; an office's actual state is not proven by popularity.
  other=next((x for x in candidates[1:] if x[1]!=candidates[0][1]),None) if candidates else None
  result=candidates[0][1] if candidates and (not other or candidates[0][0]-other[0]>=.15) else None
  if result:CACHE[key]=result
  return result

def normalize(value,description='',fetch=None):
 parts=value.split(';');out=[];looked_up=False;unresolved=False
 for raw in parts:
  pieces=[p.strip() for p in raw.split(',') if p.strip()]
  if not pieces:continue
  city=city_label(pieces[0]);country=pieces[-1].casefold() in US
  tail=pieces[1:-1] if country else pieces[1:]
  if re.search(r'\b(remote|hybrid|multiple|various)\b',city,re.I):out.append(raw.strip());continue
  state=next((STATES.get(p) or (p if p in STATES.values() else None) for p in tail if p in STATES or p in STATES.values()),None)
  if not state and len(pieces)<=2:
   pattern=r'\b'+re.escape(city)+r',\s*('+ '|'.join(map(re.escape,sorted(STATES,key=len,reverse=True)))+r'|'+ '|'.join(STATES.values())+r')\b'
   matches={STATES.get(m.group(1),m.group(1)) for m in re.finditer(pattern,description)}
   if len(matches)==1:state=matches.pop()
  if state:out.append(city+', '+state);continue
  if country and not tail and fetch and len(parts)<=4 and re.fullmatch(r"[\w .'-]{2,80}",city):
   try:
    state=lookup(city,fetch)
    if state:out.append(city+', '+state);looked_up=True;continue
   except Exception:pass
   unresolved=True
  out.append(', '.join([city]+tail+(['United States'] if country else [])))
 return '; '.join(dict.fromkeys(out)),looked_up,unresolved
