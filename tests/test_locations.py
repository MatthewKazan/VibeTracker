import unittest,json
from unittest.mock import patch
import locations
class LocationsTests(unittest.TestCase):
 def setUp(self):locations.CACHE.clear()
 def result(self,code,importance=.6):return {'importance':importance,'address':{'city':'Waltham','country_code':'us','ISO3166-2-lvl4':'US-'+code}}
 def test_office_label_resolves_to_city_state(self):
  with patch.object(locations.time,'sleep'):
   result=locations.normalize('Waltham Office (POST), United States of America',fetch=lambda _:json.dumps([self.result('MA'),self.result('VT',.3)]))
  self.assertEqual(result,('Waltham, MA',True,False))
 def test_explicit_state_needs_no_lookup(self):
  self.assertEqual(locations.normalize('Waltham Office (POST), Massachusetts, USA')[0],'Waltham, MA')
 def test_description_state_takes_precedence(self):
  self.assertEqual(locations.normalize('Waltham Office (POST), US','Based in Waltham, VT.')[0],'Waltham, VT')
 def test_ambiguous_places_do_not_invent_state(self):
  with patch.object(locations.time,'sleep'):
   r=locations.normalize('Waltham Office (POST), US',fetch=lambda _:json.dumps([self.result('MA'),self.result('VT',.55)]))
  self.assertEqual(r,('Waltham, United States',False,True))
 def test_lookup_failure_is_nonfatal(self):
  def fail(_):raise TimeoutError()
  with patch.object(locations.time,'sleep'):r=locations.normalize('Waltham Office (POST), US',fetch=fail)
  self.assertEqual(r,('Waltham, United States',False,True))
 def test_remote_foreign_and_multiple_preserved(self):
  for value in ['Remote, United States','London, United Kingdom','Toronto, Ontario, Canada']:
   self.assertEqual(locations.normalize(value)[0],value)
  self.assertEqual(locations.normalize('Boston, Massachusetts, US; Austin, Texas, US')[0],'Boston, MA; Austin, TX')
 def test_normalization_is_cached(self):
  with patch.object(locations.time,'sleep'),patch('locations.json.loads',return_value=[self.result('MA')]) as parse:
   for _ in range(2):locations.normalize('Waltham, US',fetch=lambda _: '[]')
   self.assertEqual(parse.call_count,1)
 def test_structured_location_survives_conflicting_ai_and_country_object(self):
  import app
  posting={'@type':'JobPosting','title':'Engineer','hiringOrganization':{'name':'Example'},'description':'A role','jobLocation':{'address':{'addressLocality':'Waltham Office (POST)','addressRegion':'Massachusetts','addressCountry':{'@type':'Country','name':'United States'}}}}
  text='<script type="application/ld+json">'+json.dumps(posting)+'</script>'
  with patch.object(app,'settings',return_value={'model':'test'}),patch.object(app,'ready_ai',return_value=('test',{})),patch.object(app.ai,'generate',return_value={'location':'Boston, MA','title':'Wrong title'}):
   result=app.extract('https://example.com',text)
  self.assertEqual(result['location'],'Waltham, MA');self.assertEqual(result['title'],'Engineer')
