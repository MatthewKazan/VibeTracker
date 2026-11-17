"""Declarative, locally editable posting selectors. No page scripts are executed."""
import json,re,urllib.parse
from html.parser import HTMLParser
from pathlib import Path
FIELDS={'title','company','location','description'}
VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
BLOCK={'p','li','h1','h2','h3','h4','div','section','article','br','ul','ol','address'}
SKIP={'script','style','noscript','nav','footer','svg','button'}
class Node:
 def __init__(self,tag='',attrs=(),parent=None):self.tag=tag;self.attrs=dict(attrs);self.parent=parent;self.children=[]
 def text(self):
  if self.tag in SKIP or self.attrs.get('aria-hidden')=='true':return ''
  body=''.join(c if isinstance(c,str) else c.text() for c in self.children)
  return ('\n'+body+'\n') if self.tag in BLOCK else body
class Tree(HTMLParser):
 def __init__(self,raw):
  super().__init__(convert_charrefs=True);self.root=Node();self.stack=[self.root];self.nodes=[];self.feed(raw)
 def handle_starttag(self,tag,attrs):
  node=Node(tag,attrs,self.stack[-1]);self.stack[-1].children.append(node);self.nodes.append(node)
  if tag not in VOID:self.stack.append(node)
 def handle_startendtag(self,tag,attrs):
  self.handle_starttag(tag,attrs)
  if tag not in VOID:self.handle_endtag(tag)
 def handle_endtag(self,tag):
  for i in range(len(self.stack)-1,0,-1):
   if self.stack[i].tag==tag:self.stack=self.stack[:i];break
 def handle_data(self,data):self.stack[-1].children.append(data)
TOKEN=re.compile(r'(?P<tag>[a-zA-Z][\w-]*|\*)?(?P<suffix>(?:[.#][\w-]+|\[[\w-]+(?:=[\w:./-]+|="[^"\n]{1,150}"|=\x27[^\x27\n]{1,150}\x27)?\])*)$')
def tokens(selector):
 # Descendant selectors only, with tags, class/id and exact attributes.
 parts=re.findall(r'(?:[^\s\[\]]|\[[^\]]*\])+',selector)
 if not parts or ' '.join(parts)!=selector.strip() or any(not TOKEN.fullmatch(p) or not p for p in parts):raise ValueError('Use simple descendant selectors: .class, #id, tag, or [attribute="value"].')
 return parts

def matches(node,token):
 m=TOKEN.fullmatch(token);tag=m['tag']
 if tag and tag!='*' and node.tag!=tag.lower():return False
 for suffix in re.findall(r'[.#][\w-]+|\[[^\]]+\]',m['suffix']):
  if suffix[0]=='.' and suffix[1:] not in node.attrs.get('class','').split():return False
  if suffix[0]=='#' and node.attrs.get('id')!=suffix[1:]:return False
  if suffix[0]=='[':
   name,sep,value=suffix[1:-1].partition('=')
   if name not in node.attrs or sep and node.attrs[name]!=value.strip('"\x27'):return False
 return True

def select(tree,selector,scope=None):
 parts=tokens(selector);out=[]
 for node in tree.nodes:
  if not matches(node,parts[-1]):continue
  parent=node.parent;index=len(parts)-2;inside=scope is None or node is scope
  while parent and (scope is None or parent is not scope.parent):
   if parent is scope:inside=True
   if index>=0 and matches(parent,parts[index]):index-=1
   parent=parent.parent
  if index<0 and inside:out.append(node)
 return out

def text(node):return '\n'.join(' '.join(line.split()) for line in node.text().splitlines() if line.strip())
def defaults():return json.loads((Path(__file__).parent/'static/autofill-rules.json').read_text())
def validate(rules):
 if not isinstance(rules,list) or len(rules)>50:raise ValueError('Use a list of up to 50 Autofill rules.')
 for rule in rules:
  if not isinstance(rule,dict) or not {'name','host','fields'}<=rule.keys() or set(rule)-{'name','host','path_prefix','scope','fields'}:raise ValueError('Each rule needs name, host and fields; optional path_prefix and scope.')
  if not isinstance(rule['name'],str) or not 1<=len(rule['name'])<=100:raise ValueError('Rule names must be 1–100 characters.')
  if not isinstance(rule['host'],str) or not re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*',rule['host']) or len(rule['host'])>253:raise ValueError('Use an exact lowercase hostname, without https://.')
  if 'path_prefix' in rule and (not isinstance(rule['path_prefix'],str) or not rule['path_prefix'].startswith('/') or len(rule['path_prefix'])>300):raise ValueError('path_prefix must start with /.')
  if 'scope' in rule:validate_selector(rule['scope'])
  if not isinstance(rule['fields'],dict) or not rule['fields'] or set(rule['fields'])-FIELDS:raise ValueError('Supported fields: title, company, location, description.')
  for specs in rule['fields'].values():
   if not isinstance(specs,list) or not 1<=len(specs)<=10:raise ValueError('Each field needs 1–10 selectors.')
   for spec in specs:
    if not isinstance(spec,dict) or 'selector' not in spec or set(spec)-{'selector','attribute'}:raise ValueError('Each field source needs selector, with an optional attribute.')
    validate_selector(spec['selector'])
    if 'attribute' in spec and (not isinstance(spec['attribute'],str) or not re.fullmatch(r'[\w-]{1,60}',spec['attribute'])):raise ValueError('Invalid source attribute.')
 return rules

def validate_selector(value):
 if not isinstance(value,str) or not 1<=len(value)<=300:raise ValueError('Selectors must be 1–300 characters.')
 tokens(value)

def apply(tree,url,rules):
 parsed=urllib.parse.urlparse(url)
 for rule in rules:
  if parsed.hostname!=rule['host'] or not parsed.path.startswith(rule.get('path_prefix','/')):continue
  scope=None
  if rule.get('scope'):
   scopes=select(tree,rule['scope'])
   if len(scopes)!=1:continue  # Never guess between competing role containers.
   scope=scopes[0]
  result={}
  for field,specs in rule['fields'].items():
   values=[]
   for spec in specs:
    for node in select(tree,spec['selector'],scope):
     value=node.attrs.get(spec['attribute'],'').strip() if spec.get('attribute') else text(node)
     if value and value not in values:values.append(value)
   if field in ('title','company') and len(values)>1:continue
   if values:result[field]=('\n\n' if field=='description' else '; ').join(values)
  if result:return result,rule['name']
 return {},''

def semantic_location(tree):
 for selector in ['[itemprop="jobLocation"]','[data-automation-id="locations"]','.job__location','.job-location','.posting-categories .location','.location']:
  nodes=select(tree,selector);values=[]
  for node in nodes:
   address=[]
   for field in ['addressLocality','addressRegion','addressCountry']:
    parts=select(tree,'[itemprop="'+field+'"]',node)
    address.extend(n.attrs.get('content') or text(n) for n in parts if n.attrs.get('content') or text(n))
   value=', '.join(address) if address else node.attrs.get('content') or text(node)
   value=re.sub(r'^(?:Job )?Location\s*:\s*','',value,flags=re.I).strip()
   if value and value not in values:values.append(value)
  if values and len(values)<=10 and all(len(v)<=160 for v in values):return '; '.join(values)
 # Explicit Location labels only: never mine unrelated cities from the entire page.
 lines=text(tree.root).splitlines()
 for i,line in enumerate(lines):
  m=re.fullmatch(r'(?:Job )?Location\s*:\s*(.{2,160})',line,re.I)
  if m:return m[1]
  if re.fullmatch(r'(?:Job )?Location\s*:',line,re.I) and i+1<len(lines) and 1<len(lines[i+1])<=160:return lines[i+1]
 return ''

def choose_posting(candidates,url):
 if len(candidates)<=1:return candidates[0] if candidates else None
 target=urllib.parse.urlparse(url);path=target.path.rstrip('/');ids=set(re.findall(r'\d{5,}',path))
 exact=[];by_id=[]
 for item in candidates:
  links=[item.get('url'),item.get('@id'),item.get('mainEntityOfPage')]
  if any(isinstance(link,str) and urllib.parse.urlparse(urllib.parse.urljoin(url,link)).path.rstrip('/')==path for link in links):exact.append(item);continue
  ident=item.get('identifier',{});ident=ident.get('value') if isinstance(ident,dict) else ident
  if ids and str(ident) in ids:by_id.append(item)
 hits=exact or by_id
 return hits[0] if len(hits)==1 else None

def structured_locations(posting):
 raw=posting.get('jobLocation',[]);raw=raw if isinstance(raw,list) else [raw];values=[]
 for location in raw:
  if isinstance(location,str):values.append(location);continue
  if not isinstance(location,dict):continue
  address=location.get('address',location)
  if isinstance(address,str):values.append(address);continue
  if isinstance(address,dict):
   parts=[]
   for key in ['addressLocality','addressRegion','addressCountry']:
    value=address.get(key)
    if isinstance(value,dict):value=value.get('name') or value.get('addressCountry')
    if isinstance(value,str) and value.strip():parts.append(value.strip())
   if parts:values.append(', '.join(parts))
   elif isinstance(location.get('name'),str):values.append(location['name'])
 remote=posting.get('jobLocationType')=='TELECOMMUTE'
 if remote:
  eligible=posting.get('applicantLocationRequirements',[]);eligible=eligible if isinstance(eligible,list) else [eligible]
  names=[e.get('name') for e in eligible if isinstance(e,dict) and isinstance(e.get('name'),str)]
  values.insert(0,'Remote'+(' — '+', '.join(names) if names else ''))
 return '; '.join(dict.fromkeys(values))
